from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

try:
    import redis
except Exception:  # pragma: no cover - dependency optional for tests
    redis = None


def _get_redis_url() -> str:
    return os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")


def get_redis_client():
    if redis is None:
        raise RuntimeError("redis package not installed; please install 'redis' or set up a fake client for tests")
    return redis.from_url(_get_redis_url())


def _history_key(session_id: str) -> str:
    return f"sess:{session_id}:history"


def _retrieval_key(session_id: str) -> str:
    return f"sess:{session_id}:last_retrieved"


def _events_stream_key() -> str:
    return os.getenv("REDIS_EVENTS_STREAM", "rag:events")


def _events_group_name() -> str:
    return os.getenv("REDIS_EVENTS_GROUP", "rag-persist-workers")


def _events_consumer_name() -> str:
    return os.getenv("REDIS_EVENTS_CONSUMER", f"consumer-{os.getpid()}")


def _index_events_stream_key() -> str:
    return os.getenv("REDIS_INDEX_EVENTS_STREAM", "rag:index-events")


def _index_events_group_name() -> str:
    return os.getenv("REDIS_INDEX_EVENTS_GROUP", "rag-index-workers")


def _index_events_consumer_name() -> str:
    return os.getenv("REDIS_INDEX_EVENTS_CONSUMER", f"index-consumer-{os.getpid()}")


def save_message(session_id: str, role: str, text: str, max_len: int = 20, ttl: int = 86400) -> None:
    """保存一条会话消息（role: user|assistant|system）。"""
    client = get_redis_client()
    key = _history_key(session_id)
    entry = json.dumps({"role": role, "text": text})
    client.lpush(key, entry)
    client.ltrim(key, 0, max_len - 1)
    client.expire(key, ttl)


def get_recent_messages(session_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    """返回按时间升序（旧->新）的最近消息列表。"""
    client = get_redis_client()
    key = _history_key(session_id)
    raw = client.lrange(key, 0, limit - 1)
    # raw is newest->oldest; reverse to chronological
    items = []
    for b in reversed(raw):
        try:
            items.append(json.loads(b))
        except Exception:
            items.append({"role": "unknown", "text": b.decode() if isinstance(b, (bytes, bytearray)) else str(b)})
    return items


def save_retrieval_snapshot(session_id: str, snapshot: List[Dict[str, Any]], ttl: int = 86400) -> None:
    client = get_redis_client()
    key = _retrieval_key(session_id)
    client.set(key, json.dumps(snapshot))
    client.expire(key, ttl)


def get_retrieval_snapshot(session_id: str) -> Optional[List[Dict[str, Any]]]:
    client = get_redis_client()
    key = _retrieval_key(session_id)
    raw = client.get(key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def clear_session(session_id: str) -> None:
    client = get_redis_client()
    client.delete(_history_key(session_id))
    client.delete(_retrieval_key(session_id))


def append_qa_turn_event(
    *,
    session_id: str,
    trace_id: str,
    question: str,
    answer: str,
    conversation_title: str | None = None,
    user_message_id: str | None = None,
    assistant_message_id: str | None = None,
    user_metadata: Dict[str, Any] | None = None,
    assistant_metadata: Dict[str, Any] | None = None,
    snapshot: List[Dict[str, Any]] | None = None,
    stream_key: str | None = None,
) -> str:
    """把一次 QA 结果写入 Redis Stream，供后台 worker 做可靠落库。"""
    client = get_redis_client()
    key = stream_key or _events_stream_key()
    payload = {
        "event_type": "qa_turn",
        "session_id": session_id,
        "trace_id": trace_id,
        "question": question,
        "answer": answer,
        "conversation_title": conversation_title or "",
        "user_message_id": user_message_id or "",
        "assistant_message_id": assistant_message_id or "",
        "user_metadata": json.dumps(user_metadata or {}, ensure_ascii=False),
        "assistant_metadata": json.dumps(assistant_metadata or {}, ensure_ascii=False),
        "snapshot": json.dumps(snapshot or [], ensure_ascii=False),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return client.xadd(key, payload)


def ensure_events_group(stream_key: str | None = None, group_name: str | None = None) -> None:
    """确保消费组存在，流不存在时会先创建一个空流种子。"""
    client = get_redis_client()
    key = stream_key or _events_stream_key()
    group = group_name or _events_group_name()
    try:
        client.xgroup_create(name=key, groupname=group, id="0-0", mkstream=True)
    except Exception as exc:
        message = str(exc).lower()
        if "busygroup" in message or "group name already exists" in message:
            return
        raise


def read_qa_turn_events(
    count: int = 10,
    block_ms: int = 1000,
    stream_key: str | None = None,
    group_name: str | None = None,
    consumer_name: str | None = None,
) -> List[tuple[str, List[tuple[str, Dict[str, Any]]]]]:
    client = get_redis_client()
    key = stream_key or _events_stream_key()
    group = group_name or _events_group_name()
    consumer = consumer_name or _events_consumer_name()
    ensure_events_group(stream_key=key, group_name=group)
    return client.xreadgroup(groupname=group, consumername=consumer, streams={key: ">"}, count=count, block=block_ms)


def ack_qa_turn_event(event_id: str, stream_key: str | None = None, group_name: str | None = None) -> int:
    client = get_redis_client()
    key = stream_key or _events_stream_key()
    group = group_name or _events_group_name()
    return client.xack(key, group, event_id)


def append_index_chunk_event(
    *,
    chunk_text: str,
    chunk_metadata: Dict[str, Any],
    trace_id: str | None = None,
    collection_name: str,
    persist_directory: str | None = None,
    backend: str = "chroma",
    embedding_model: str | None = None,
    stream_key: str | None = None,
) -> str:
    """把一个待向量化的 chunk 写入 Redis Stream。"""
    client = get_redis_client()
    key = stream_key or _index_events_stream_key()
    payload = {
        "event_type": "index_chunk",
        "trace_id": trace_id or "",
        "collection_name": collection_name,
        "backend": backend,
        "persist_directory": persist_directory or "",
        "embedding_model": embedding_model or "",
        "chunk_text": chunk_text,
        "chunk_metadata": json.dumps(chunk_metadata, ensure_ascii=False),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return client.xadd(key, payload)


def ensure_index_events_group(stream_key: str | None = None, group_name: str | None = None) -> None:
    client = get_redis_client()
    key = stream_key or _index_events_stream_key()
    group = group_name or _index_events_group_name()
    try:
        client.xgroup_create(name=key, groupname=group, id="0-0", mkstream=True)
    except Exception as exc:
        message = str(exc).lower()
        if "busygroup" in message or "group name already exists" in message:
            return
        raise


def read_index_chunk_events(
    count: int = 10,
    block_ms: int = 1000,
    stream_key: str | None = None,
    group_name: str | None = None,
    consumer_name: str | None = None,
) -> List[tuple[str, List[tuple[str, Dict[str, Any]]]]]:
    client = get_redis_client()
    key = stream_key or _index_events_stream_key()
    group = group_name or _index_events_group_name()
    consumer = consumer_name or _index_events_consumer_name()
    ensure_index_events_group(stream_key=key, group_name=group)
    return client.xreadgroup(groupname=group, consumername=consumer, streams={key: ">"}, count=count, block=block_ms)


def ack_index_chunk_event(event_id: str, stream_key: str | None = None, group_name: str | None = None) -> int:
    client = get_redis_client()
    key = stream_key or _index_events_stream_key()
    group = group_name or _index_events_group_name()
    return client.xack(key, group, event_id)
