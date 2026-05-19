from __future__ import annotations

import argparse
import json
import os
from typing import Any

from rag.memory.redis_memory import get_redis_client


def _default_source_stream(dlq_stream: str) -> str:
    if dlq_stream.endswith(":dlq"):
        return dlq_stream[: -len(":dlq")]
    return dlq_stream


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay dead-letter Redis Stream entries back to the source stream")
    parser.add_argument("--dlq-stream", default=os.getenv("REDIS_INDEX_EVENTS_DLQ_STREAM") or os.getenv("REDIS_EVENTS_DLQ_STREAM") or "rag:events:dlq")
    parser.add_argument("--source-stream", default=None)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args(argv)

    client = get_redis_client()
    dlq_stream = args.dlq_stream
    source_stream = args.source_stream or _default_source_stream(dlq_stream)
    entries = client.xrange(dlq_stream, count=args.limit)
    replayed = 0
    for entry_id, fields in entries:
        payload: dict[str, Any] = {}
        for key, value in fields.items():
            k = key.decode("utf-8", errors="ignore") if isinstance(key, bytes) else str(key)
            if isinstance(value, bytes):
                payload[k] = value.decode("utf-8", errors="ignore")
            else:
                payload[k] = value

        original_payload = payload.get("payload")
        if isinstance(original_payload, str):
            try:
                original_payload = json.loads(original_payload)
            except Exception:
                original_payload = {}
        if not isinstance(original_payload, dict):
            original_payload = {}

        original_payload["replayed_from_dlq"] = True
        original_payload["replayed_dlq_entry_id"] = entry_id.decode("utf-8", errors="ignore") if isinstance(entry_id, bytes) else str(entry_id)
        client.xadd(source_stream, original_payload)
        replayed += 1

    print(f"replayed={replayed} source_stream={source_stream} dlq_stream={dlq_stream}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
