from __future__ import annotations

import argparse
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from ..memory.redis_memory import (
    ack_qa_turn_event,
    ensure_events_group,
    get_redis_client,
    read_qa_turn_events,
)
from ..observability import bind_trace_id, configure_logging
from ..storage import record_chat_turn
from .reliability import (
    clear_retry,
    compute_backoff_seconds,
    compute_idempotency_key,
    default_dlq_stream_for,
    increment_retry,
    is_already_processed,
    mark_processed,
    send_to_dead_letter,
)


LOGGER = logging.getLogger(__name__)


def _event_id_to_text(event_id: Any) -> str:
    if isinstance(event_id, bytes):
        return event_id.decode("utf-8", errors="ignore")
    return str(event_id)


@dataclass(slots=True)
class PersistWorker:
    stream_key: str | None = None
    group_name: str | None = None
    consumer_name: str | None = None
    block_ms: int = 1000
    batch_size: int = 10
    claim_min_idle_ms: int = 60_000
    max_retries: int = 5
    backoff_base_seconds: float = 1.0
    backoff_max_seconds: float = 30.0
    idempotency_ttl_seconds: int = 7 * 24 * 3600
    dlq_stream: str | None = None

    def _parse_fields(self, fields: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key, value in fields.items():
            k = key.decode("utf-8", errors="ignore") if isinstance(key, bytes) else str(key)
            normalized[k] = value

        def _get_text(key: str, default: str = "") -> str:
            value = normalized.get(key)
            if isinstance(value, bytes):
                return value.decode("utf-8", errors="ignore")
            if value is None:
                return default
            return str(value)

        def _loads_json(key: str, default):
            raw = _get_text(key, "")
            if not raw:
                return default
            try:
                return json.loads(raw)
            except Exception:
                return default

        return {
            "event_type": _get_text("event_type"),
            "session_id": _get_text("session_id"),
            "trace_id": _get_text("trace_id") or None,
            "question": _get_text("question"),
            "answer": _get_text("answer"),
            "conversation_title": _get_text("conversation_title") or None,
            "user_message_id": _get_text("user_message_id") or None,
            "assistant_message_id": _get_text("assistant_message_id") or None,
            "user_metadata": _loads_json("user_metadata", {}),
            "assistant_metadata": _loads_json("assistant_metadata", {}),
            "snapshot": _loads_json("snapshot", []),
            "idempotency_key": _get_text("idempotency_key") or None,
        }

    def _calc_idempotency_key(self, payload: dict[str, Any]) -> str:
        if payload.get("idempotency_key"):
            return str(payload["idempotency_key"])
        strong_key = f"{payload.get('session_id')}|{payload.get('user_message_id')}|{payload.get('assistant_message_id')}"
        if payload.get("user_message_id") and payload.get("assistant_message_id"):
            return compute_idempotency_key(
                "qa_turn", {"message_pair": strong_key}, fallback=strong_key
            )
        return compute_idempotency_key(
            "qa_turn",
            {
                "session_id": payload.get("session_id"),
                "question": payload.get("question"),
                "answer": payload.get("answer"),
            },
            fallback=payload.get("session_id") or "unknown",
        )

    def _process_payload(
        self, event_id: Any, payload: dict[str, Any], ack_direct: bool = False
    ) -> int:
        stream_key = self.stream_key or os.getenv("REDIS_EVENTS_STREAM", "rag:events")
        event_id_text = _event_id_to_text(event_id)

        if payload.get("event_type") != "qa_turn":
            if ack_direct:
                get_redis_client().xack(
                    stream_key,
                    self.group_name or os.getenv("REDIS_EVENTS_GROUP", "rag-persist-workers"),
                    event_id,
                )
            else:
                ack_qa_turn_event(event_id, stream_key=self.stream_key, group_name=self.group_name)
            return 0

        session_id = payload.get("session_id")
        if not session_id:
            if ack_direct:
                get_redis_client().xack(
                    stream_key,
                    self.group_name or os.getenv("REDIS_EVENTS_GROUP", "rag-persist-workers"),
                    event_id,
                )
            else:
                ack_qa_turn_event(event_id, stream_key=self.stream_key, group_name=self.group_name)
            return 0

        trace_id = payload.get("trace_id")
        idem_key = self._calc_idempotency_key(payload)
        if is_already_processed(idem_key):
            if ack_direct:
                get_redis_client().xack(
                    stream_key,
                    self.group_name or os.getenv("REDIS_EVENTS_GROUP", "rag-persist-workers"),
                    event_id,
                )
            else:
                ack_qa_turn_event(event_id, stream_key=self.stream_key, group_name=self.group_name)
            clear_retry(stream_key, event_id_text)
            LOGGER.info(
                "qa_event_duplicate_skipped",
                extra={
                    "event": "qa_event_duplicate_skipped",
                    "event_id": event_id_text,
                    "session_id": session_id,
                },
            )
            return 0

        with bind_trace_id(trace_id) as bound_trace:
            try:
                ok = record_chat_turn(
                    session_id=session_id,
                    user_text=payload.get("question") or "",
                    assistant_text=payload.get("answer") or "",
                    conversation_title=payload.get("conversation_title"),
                    user_message_id=payload.get("user_message_id"),
                    assistant_message_id=payload.get("assistant_message_id"),
                    trace_id=bound_trace,
                    idempotency_key=idem_key,
                    user_metadata={
                        **payload.get("user_metadata", {}),
                        "redis_event_id": event_id_text,
                        "trace_id": bound_trace,
                        "idempotency_key": idem_key,
                    },
                    assistant_metadata={
                        **payload.get("assistant_metadata", {}),
                        "redis_event_id": event_id_text,
                        "trace_id": bound_trace,
                        "idempotency_key": idem_key,
                        "snapshot": payload.get("snapshot", []),
                    },
                )
                if not ok:
                    raise RuntimeError("MySQL persistence unavailable; skip ack to avoid data loss")

                mark_processed(idem_key, event_id_text, ttl_seconds=self.idempotency_ttl_seconds)
                clear_retry(stream_key, event_id_text)
                if ack_direct:
                    get_redis_client().xack(
                        stream_key,
                        self.group_name or os.getenv("REDIS_EVENTS_GROUP", "rag-persist-workers"),
                        event_id,
                    )
                else:
                    ack_qa_turn_event(
                        event_id, stream_key=self.stream_key, group_name=self.group_name
                    )
                LOGGER.info(
                    "qa_event_persisted",
                    extra={
                        "event": "qa_event_persisted",
                        "event_id": event_id_text,
                        "session_id": session_id,
                    },
                )
                return 1
            except Exception as exc:
                attempts = increment_retry(stream_key, event_id_text)
                if attempts >= self.max_retries:
                    dlq_stream = self.dlq_stream or default_dlq_stream_for(stream_key)
                    dlq_id = send_to_dead_letter(
                        source_stream=stream_key,
                        dlq_stream=dlq_stream,
                        event_id=event_id_text,
                        payload={**payload, "idempotency_key": idem_key},
                        attempts=attempts,
                        error=str(exc),
                        trace_id=bound_trace,
                    )
                    if ack_direct:
                        get_redis_client().xack(
                            stream_key,
                            self.group_name
                            or os.getenv("REDIS_EVENTS_GROUP", "rag-persist-workers"),
                            event_id,
                        )
                    else:
                        ack_qa_turn_event(
                            event_id, stream_key=self.stream_key, group_name=self.group_name
                        )
                    clear_retry(stream_key, event_id_text)
                    LOGGER.exception(
                        "qa_event_dead_lettered",
                        extra={
                            "event": "qa_event_dead_lettered",
                            "event_id": event_id_text,
                            "session_id": session_id,
                            "dlq_stream": dlq_stream,
                            "dlq_id": dlq_id,
                            "attempts": attempts,
                        },
                    )
                    return 0

                backoff = compute_backoff_seconds(
                    attempts,
                    base_seconds=self.backoff_base_seconds,
                    max_seconds=self.backoff_max_seconds,
                )
                LOGGER.warning(
                    "qa_event_retry_scheduled",
                    extra={
                        "event": "qa_event_retry_scheduled",
                        "event_id": event_id_text,
                        "session_id": session_id,
                        "attempts": attempts,
                        "backoff_seconds": backoff,
                    },
                )
                time.sleep(backoff)
                return 0

    def process_once(self) -> int:
        processed = self._claim_and_process_pending()
        batches = read_qa_turn_events(
            count=self.batch_size,
            block_ms=self.block_ms,
            stream_key=self.stream_key,
            group_name=self.group_name,
            consumer_name=self.consumer_name,
        )
        for _, messages in batches:
            for event_id, fields in messages:
                payload = self._parse_fields(fields) if isinstance(fields, dict) else {}
                processed += self._process_payload(event_id, payload, ack_direct=False)
        return processed

    def _claim_and_process_pending(self) -> int:
        claimed_processed = 0
        client = get_redis_client()
        key = self.stream_key or os.getenv("REDIS_EVENTS_STREAM", "rag:events")
        group = self.group_name or os.getenv("REDIS_EVENTS_GROUP", "rag-persist-workers")
        consumer = self.consumer_name or os.getenv(
            "REDIS_EVENTS_CONSUMER", f"consumer-{os.getpid()}"
        )
        ensure_events_group(stream_key=key, group_name=group)
        try:
            result = client.xautoclaim(
                name=key,
                groupname=group,
                consumername=consumer,
                min_idle_time=self.claim_min_idle_ms,
                start_id="0-0",
                count=self.batch_size,
            )
            if not result:
                return claimed_processed
            messages = result[1] if len(result) > 1 else []
            for message_id, fields in messages:
                payload = self._parse_fields(fields if isinstance(fields, dict) else {})
                claimed_processed += self._process_payload(message_id, payload, ack_direct=True)
        except Exception as exc:
            LOGGER.exception("xautoclaim failed: %s", exc)
        return claimed_processed


def run_once(
    batch_size: int = 10,
    claim_min_idle_ms: int = 60_000,
    stream_key: str | None = None,
    group_name: str | None = None,
    consumer_name: str | None = None,
) -> int:
    worker = PersistWorker(
        batch_size=batch_size,
        claim_min_idle_ms=claim_min_idle_ms,
        stream_key=stream_key,
        group_name=group_name,
        consumer_name=consumer_name,
    )
    return worker.process_once()


def consume_forever(poll_interval: float = 1.0, batch_size: int = 10) -> None:
    worker = PersistWorker(batch_size=batch_size)
    while True:
        processed = worker.process_once()
        if processed == 0:
            time.sleep(poll_interval)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Consume Redis QA events and persist them into MySQL"
    )
    parser.add_argument("--once", action="store_true", help="Process one batch and exit")
    parser.add_argument("--batch-size", type=int, default=10, help="Redis stream batch size")
    parser.add_argument(
        "--claim-min-idle-ms",
        type=int,
        default=60_000,
        help="Minimum idle ms before claiming pending messages",
    )
    parser.add_argument(
        "--poll-interval", type=float, default=1.0, help="Polling interval in seconds"
    )
    parser.add_argument("--stream-key", default=None, help="Redis stream key for QA events")
    parser.add_argument("--group-name", default=None, help="Redis consumer group name")
    parser.add_argument("--consumer-name", default=None, help="Redis consumer name")
    args = parser.parse_args(argv)

    configure_logging()
    if args.once:
        count = run_once(
            batch_size=args.batch_size,
            claim_min_idle_ms=args.claim_min_idle_ms,
            stream_key=args.stream_key,
            group_name=args.group_name,
            consumer_name=args.consumer_name,
        )
        print(count)
        return 0

    worker = PersistWorker(
        batch_size=args.batch_size,
        claim_min_idle_ms=args.claim_min_idle_ms,
        stream_key=args.stream_key,
        group_name=args.group_name,
        consumer_name=args.consumer_name,
    )
    while True:
        processed = worker.process_once()
        if processed == 0:
            time.sleep(args.poll_interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
