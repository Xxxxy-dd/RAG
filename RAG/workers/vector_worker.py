from __future__ import annotations

import argparse
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document

from ..indexes import DEFAULT_COLLECTION_NAME, DEFAULT_PERSIST_DIRECTORY, load_index
from ..memory.redis_memory import ack_index_chunk_event, ensure_index_events_group, get_redis_client, read_index_chunk_events
from ..observability import bind_trace_id, configure_logging
from ..storage import (
    get_mysql_store,
    make_document_key,
    make_vector_id,
    resolve_embedding_dimension,
    resolve_embedding_model_name,
)
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


@dataclass(slots=True)
class VectorWorker:
    collection_name: str = DEFAULT_COLLECTION_NAME
    persist_directory: str | None = None
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

    def _event_id_text(self, event_id: Any) -> str:
        if isinstance(event_id, bytes):
            return event_id.decode("utf-8", errors="ignore")
        return str(event_id)

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
            "trace_id": _get_text("trace_id") or None,
            "collection_name": _get_text("collection_name") or self.collection_name,
            "backend": _get_text("backend") or "chroma",
            "persist_directory": _get_text("persist_directory") or self.persist_directory,
            "embedding_model": _get_text("embedding_model") or None,
            "chunk_text": _get_text("chunk_text"),
            "chunk_metadata": _loads_json("chunk_metadata", {}),
            "idempotency_key": _get_text("idempotency_key") or None,
        }

    def _load_vector_store(self, persist_directory: str | None = None):
        return load_index(
            collection_name=self.collection_name,
            persist_directory=persist_directory or self.persist_directory or DEFAULT_PERSIST_DIRECTORY,
        )

    def _persist_to_mysql(
        self,
        document: Document,
        vector_id: str,
        embedding_model: str | None,
        trace_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> None:
        store = get_mysql_store()
        if store is None:
            return

        document_key = make_document_key(document, self.collection_name)
        document_row = store.save_document(
            document_key=document_key,
            content=document.page_content,
            source=str(document.metadata.get("source")) if document.metadata.get("source") is not None else None,
            title_path=str(document.metadata.get("title_path")) if document.metadata.get("title_path") is not None else None,
            trace_id=trace_id,
            idempotency_key=idempotency_key,
            metadata={
                **dict(document.metadata or {}),
                "collection_name": self.collection_name,
                "document_key": document_key,
                "vector_id": vector_id,
                "trace_id": trace_id,
            },
        )
        store.save_embedding(
            document_id=int(document_row["id"]),
            vector_id=vector_id,
            model=resolve_embedding_model_name(embedding_model),
            dimension=resolve_embedding_dimension(embedding_model),
            trace_id=trace_id,
            idempotency_key=idempotency_key,
            metadata={
                "collection_name": self.collection_name,
                "document_key": document_key,
                "trace_id": trace_id,
            },
        )

    def _upsert_vector(self, vector_store, document: Document, vector_id: str) -> None:
        try:
            vector_store.add_documents(documents=[document], ids=[vector_id])
        except Exception:
            vector_store.update_documents(ids=[vector_id], documents=[document])

    def _process_event(self, event_id: Any, payload: dict[str, Any], vector_store) -> tuple[int, Any]:
        stream_key = self.stream_key or "rag:index-events"
        event_id_text = self._event_id_text(event_id)

        if payload.get("event_type") != "index_chunk":
            ack_index_chunk_event(event_id, stream_key=self.stream_key, group_name=self.group_name)
            return 0, vector_store

        chunk_text = payload.get("chunk_text") or ""
        chunk_metadata = dict(payload.get("chunk_metadata") or {})
        trace_id = payload.get("trace_id") or chunk_metadata.get("trace_id")
        if not chunk_text:
            ack_index_chunk_event(event_id, stream_key=self.stream_key, group_name=self.group_name)
            return 0, vector_store

        document = Document(page_content=chunk_text, metadata=chunk_metadata)
        document_key = make_document_key(document, payload["collection_name"])
        vector_id = make_vector_id(document_key)

        idem_key = payload.get("idempotency_key") or compute_idempotency_key(
            "index_chunk",
            {"collection_name": payload["collection_name"], "document_key": document_key, "vector_id": vector_id},
            fallback=vector_id,
        )

        if is_already_processed(idem_key):
            ack_index_chunk_event(event_id, stream_key=self.stream_key, group_name=self.group_name)
            clear_retry(stream_key, event_id_text)
            LOGGER.info(
                "index_chunk_duplicate_skipped",
                extra={"event": "index_chunk_duplicate_skipped", "event_id": event_id_text, "vector_id": vector_id},
            )
            return 0, vector_store

        document.metadata = {
            **dict(document.metadata or {}),
            "collection_name": payload["collection_name"],
            "document_key": document_key,
            "vector_id": vector_id,
            "trace_id": trace_id,
            "idempotency_key": idem_key,
        }

        with bind_trace_id(trace_id):
            try:
                if vector_store is None:
                    vector_store = self._load_vector_store(payload.get("persist_directory"))
                self._upsert_vector(vector_store, document, vector_id)
                self._persist_to_mysql(document, vector_id, payload.get("embedding_model"), trace_id=trace_id, idempotency_key=idem_key)
                mark_processed(idem_key, event_id_text, ttl_seconds=self.idempotency_ttl_seconds)
                clear_retry(stream_key, event_id_text)
                ack_index_chunk_event(event_id, stream_key=self.stream_key, group_name=self.group_name)
                LOGGER.info(
                    "index_chunk_upserted",
                    extra={
                        "event": "index_chunk_upserted",
                        "event_id": event_id_text,
                        "vector_id": vector_id,
                        "collection_name": payload["collection_name"],
                    },
                )
                return 1, vector_store
            except Exception as exc:
                attempts = increment_retry(stream_key, event_id_text)
                if attempts >= self.max_retries:
                    dlq_stream = self.dlq_stream or default_dlq_stream_for(stream_key)
                    dlq_id = send_to_dead_letter(
                        source_stream=stream_key,
                        dlq_stream=dlq_stream,
                        event_id=event_id_text,
                        payload={
                            **payload,
                            "document_key": document_key,
                            "vector_id": vector_id,
                            "idempotency_key": idem_key,
                        },
                        attempts=attempts,
                        error=str(exc),
                        trace_id=trace_id,
                    )
                    ack_index_chunk_event(event_id, stream_key=self.stream_key, group_name=self.group_name)
                    clear_retry(stream_key, event_id_text)
                    LOGGER.exception(
                        "index_chunk_dead_lettered",
                        extra={
                            "event": "index_chunk_dead_lettered",
                            "event_id": event_id_text,
                            "vector_id": vector_id,
                            "dlq_stream": dlq_stream,
                            "dlq_id": dlq_id,
                            "attempts": attempts,
                        },
                    )
                    return 0, vector_store

                backoff = compute_backoff_seconds(
                    attempts,
                    base_seconds=self.backoff_base_seconds,
                    max_seconds=self.backoff_max_seconds,
                )
                LOGGER.warning(
                    "index_chunk_retry_scheduled",
                    extra={
                        "event": "index_chunk_retry_scheduled",
                        "event_id": event_id_text,
                        "vector_id": vector_id,
                        "attempts": attempts,
                        "backoff_seconds": backoff,
                    },
                )
                time.sleep(backoff)
                return 0, vector_store

    def _claim_and_process_pending(self) -> int:
        claimed_processed = 0
        client = get_redis_client()
        key = self.stream_key or "rag:index-events"
        group = self.group_name or "rag-index-workers"
        consumer = self.consumer_name or f"index-consumer-{os.getpid()}"
        ensure_index_events_group(stream_key=key, group_name=group)
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
            if not messages:
                return claimed_processed

            vector_store = None
            for event_id, fields in messages:
                payload = self._parse_fields(fields) if isinstance(fields, dict) else {}
                count, vector_store = self._process_event(event_id, payload, vector_store)
                claimed_processed += count
        except Exception as exc:
            LOGGER.exception("xautoclaim failed: %s", exc)
        return claimed_processed

    def process_once(self) -> int:
        LOGGER.info(
            "vector_worker_config",
            extra={
                "event": "vector_worker_config",
                "collection": self.collection_name,
                "persist_directory": self.persist_directory or DEFAULT_PERSIST_DIRECTORY,
                "stream": self.stream_key or "rag:index-events",
                "group": self.group_name or "rag-index-workers",
                "consumer": self.consumer_name or f"index-consumer-{os.getpid()}",
            },
        )
        processed = self._claim_and_process_pending()
        batches = read_index_chunk_events(
            count=self.batch_size,
            block_ms=self.block_ms,
            stream_key=self.stream_key,
            group_name=self.group_name,
            consumer_name=self.consumer_name,
        )
        normal_processed = 0
        vector_store = None
        for _, messages in batches:
            for event_id, fields in messages:
                payload = self._parse_fields(fields) if isinstance(fields, dict) else {}
                count, vector_store = self._process_event(event_id, payload, vector_store)
                normal_processed += count
        return processed + normal_processed


def run_once(batch_size: int = 10, collection_name: str = DEFAULT_COLLECTION_NAME, persist_directory: str | None = None) -> int:
    worker = VectorWorker(batch_size=batch_size, collection_name=collection_name, persist_directory=persist_directory)
    return worker.process_once()


def consume_forever(
    poll_interval: float = 1.0,
    batch_size: int = 10,
    collection_name: str = DEFAULT_COLLECTION_NAME,
    persist_directory: str | None = None,
) -> None:
    worker = VectorWorker(batch_size=batch_size, collection_name=collection_name, persist_directory=persist_directory)
    while True:
        processed = worker.process_once()
        if processed == 0:
            time.sleep(poll_interval)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Consume Redis index chunk events and upsert them into Chroma + MySQL")
    parser.add_argument("--once", action="store_true", help="Process one batch and exit")
    parser.add_argument("--batch-size", type=int, default=10, help="Redis stream batch size")
    parser.add_argument("--poll-interval", type=float, default=1.0, help="Polling interval in seconds")
    parser.add_argument("--collection-name", default=DEFAULT_COLLECTION_NAME, help="Chroma collection name")
    parser.add_argument("--persist-directory", default=None, help="Chroma persist directory")
    args = parser.parse_args(argv)

    configure_logging()
    if args.once:
        count = run_once(
            batch_size=args.batch_size,
            collection_name=args.collection_name,
            persist_directory=args.persist_directory,
        )
        print(count)
        return 0

    consume_forever(
        poll_interval=args.poll_interval,
        batch_size=args.batch_size,
        collection_name=args.collection_name,
        persist_directory=args.persist_directory,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
