from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Protocol
import time

from ..memory.redis_memory import get_redis_client


class _KVStoreProtocol(Protocol):
    def get(self, key: str) -> Any: ...

    def set(self, key: str, value: Any, ex: int | None = None) -> Any: ...

    def incr(self, key: str) -> int: ...

    def expire(self, key: str, ttl: int) -> Any: ...

    def delete(self, key: str) -> Any: ...


def _safe_json(data: dict[str, Any]) -> str:
    try:
        return json.dumps(data, ensure_ascii=False, sort_keys=True)
    except Exception:
        return "{}"


def compute_idempotency_key(namespace: str, payload: dict[str, Any], fallback: str) -> str:
    raw = _safe_json(payload) + "|" + fallback
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"rag:idem:{namespace}:{digest}"


# Pluggable KV store used for idempotency/retry counters. By default we use
# the Redis client returned by `get_redis_client()`, but tests can inject an
# in-memory store via `set_idempotency_store()` so they don't need to monkeypatch
# large parts of the worker logic.
_STORE: _KVStoreProtocol | None = None


def _default_store() -> _KVStoreProtocol:
    client = get_redis_client()
    return client  # type: ignore[return-value]


def get_idempotency_store() -> _KVStoreProtocol:
    global _STORE
    if _STORE is not None:
        return _STORE
    return _default_store()


def set_idempotency_store(store: _KVStoreProtocol) -> None:
    global _STORE
    _STORE = store


def reset_idempotency_store() -> None:
    global _STORE
    _STORE = None


class InMemoryStore:
    """A tiny in-memory KV store with TTL semantics for tests."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[Any, float | None]] = {}

    def _purge_expired(self) -> None:
        now = time.time()
        to_del = [k for k, (_, exp) in self._data.items() if exp is not None and exp < now]
        for k in to_del:
            self._data.pop(k, None)

    def get(self, key: str) -> Any:
        self._purge_expired()
        v = self._data.get(key)
        return v[0] if v is not None else None

    def set(self, key: str, value: Any, ex: int | None = None) -> None:
        exp = time.time() + ex if ex is not None else None
        self._data[key] = (value, exp)

    def incr(self, key: str) -> int:
        self._purge_expired()
        cur = self.get(key) or 0
        try:
            n = int(cur) + 1
        except Exception:
            n = 1
        self.set(key, n, None)
        return n

    def expire(self, key: str, ttl: int) -> None:
        v = self._data.get(key)
        if v is not None:
            self._data[key] = (v[0], time.time() + ttl)

    def delete(self, key: str) -> None:
        self._data.pop(key, None)


_DEFAULT_INMEM = InMemoryStore()


def use_inmemory_store_for_tests() -> InMemoryStore:
    set_idempotency_store(_DEFAULT_INMEM)
    return _DEFAULT_INMEM


def clear_inmemory_store() -> None:
    global _DEFAULT_INMEM
    _DEFAULT_INMEM = InMemoryStore()
    set_idempotency_store(_DEFAULT_INMEM)


def is_already_processed(idempotency_key: str) -> bool:
    client = get_idempotency_store()
    return bool(client.get(idempotency_key))


def mark_processed(idempotency_key: str, event_id: str, ttl_seconds: int = 7 * 24 * 3600) -> None:
    client = get_idempotency_store()
    client.set(idempotency_key, event_id, ex=ttl_seconds)


def retry_count_key(stream_key: str, event_id: str) -> str:
    return f"rag:retry:{stream_key}:{event_id}"


def increment_retry(stream_key: str, event_id: str, ttl_seconds: int = 2 * 24 * 3600) -> int:
    client = get_idempotency_store()
    key = retry_count_key(stream_key, event_id)
    attempts = int(client.incr(key))
    client.expire(key, ttl_seconds)
    return attempts


def clear_retry(stream_key: str, event_id: str) -> None:
    client = get_idempotency_store()
    client.delete(retry_count_key(stream_key, event_id))


def compute_backoff_seconds(attempt: int, base_seconds: float = 1.0, max_seconds: float = 60.0) -> float:
    if attempt <= 1:
        return base_seconds
    value = base_seconds * (2 ** (attempt - 1))
    return min(value, max_seconds)


def send_to_dead_letter(
    *,
    source_stream: str,
    dlq_stream: str,
    event_id: str,
    payload: dict[str, Any],
    attempts: int,
    error: str,
    trace_id: str | None,
) -> str:
    client = get_redis_client()
    message = {
        "source_stream": source_stream,
        "original_event_id": str(event_id),
        "attempts": str(attempts),
        "error": error,
        "trace_id": trace_id or "",
        "payload": _safe_json(payload),
        "failed_at": datetime.now(timezone.utc).isoformat(),
    }
    return str(client.xadd(dlq_stream, message))


def default_dlq_stream_for(source_stream: str) -> str:
    if source_stream == os.getenv("REDIS_EVENTS_STREAM", "rag:events"):
        return os.getenv("REDIS_EVENTS_DLQ_STREAM", "rag:events:dlq")
    if source_stream == os.getenv("REDIS_INDEX_EVENTS_STREAM", "rag:index-events"):
        return os.getenv("REDIS_INDEX_EVENTS_DLQ_STREAM", "rag:index-events:dlq")
    return f"{source_stream}:dlq"
