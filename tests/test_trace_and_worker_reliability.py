from __future__ import annotations

from fastapi.testclient import TestClient
from langchain_core.documents import Document

from rag.api import routes, service
from rag.indexes import index_manager
from rag.main import app
from rag.observability import bind_trace_id
from rag.workers import persist_worker, vector_worker


class DummyChatClient:
    def complete(self, prompt: str, system_prompt: str = "") -> str:
        return "推荐使用三层CNN加池化层进行验证码识别。"


class DummyVectorStore:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list[tuple[str, list[str], list[str]]] = []

    def add_documents(self, documents, ids):
        self.calls.append(("add_documents", list(ids), [doc.page_content for doc in documents]))
        if self.fail:
            raise RuntimeError("vector add failed")

    def update_documents(self, ids, documents):
        self.calls.append(("update_documents", list(ids), [doc.page_content for doc in documents]))
        if self.fail:
            raise RuntimeError("vector update failed")


class DummyMySQLStore:
    def __init__(self):
        self.documents: list[dict] = []
        self.embeddings: list[dict] = []

    def save_document(self, **kwargs):
        self.documents.append(kwargs)
        return {"id": 11}

    def save_embedding(self, **kwargs):
        self.embeddings.append(kwargs)
        return {"id": 22}


class DummyQAStore:
    def __init__(self):
        self.calls: list[dict] = []

    def record(self, **kwargs):
        self.calls.append(kwargs)
        return True


class DummyRedis:
    def __init__(self):
        self.streams: dict[str, list[tuple[str, dict]]] = {}
        self.acks: list[tuple[str, str, str]] = []
        self.values: dict[str, object] = {}
        self.incr_values: dict[str, int] = {}

    def xadd(self, key, payload):
        self.streams.setdefault(key, []).append((f"{key}-1", payload))
        return f"{key}-1"

    def xgroup_create(self, *args, **kwargs):
        return True

    def xreadgroup(self, *args, **kwargs):
        return []

    def xautoclaim(self, *args, **kwargs):
        return ("0-0", [])

    def xack(self, key, group, event_id):
        self.acks.append((key, group, str(event_id)))
        return 1

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, ex=None):
        self.values[key] = value
        return True

    def incr(self, key):
        value = self.incr_values.get(key, 0) + 1
        self.incr_values[key] = value
        return value

    def expire(self, key, ttl):
        return True

    def delete(self, key):
        self.values.pop(key, None)
        return 1

    def xrange(self, key, count=None):
        return [("dlq-1", self.streams.get(key, [])[0][1])] if self.streams.get(key) else []


class FailingQAStore:
    def __init__(self):
        self.calls = 0

    def __call__(self, **kwargs):
        self.calls += 1
        return False


class FailingVectorStore:
    def add_documents(self, documents, ids):
        raise RuntimeError("boom")

    def update_documents(self, ids, documents):
        raise RuntimeError("boom")


def test_api_request_propagates_trace_id_header(monkeypatch) -> None:
    captured = {}

    def fake_answer_question(*args, **kwargs):
        captured.update(kwargs)
        return routes.QAServiceResult(question="Q", rewritten_question="Q", answer="A", contexts=[])

    monkeypatch.setattr(routes, "answer_question", fake_answer_question)
    client = TestClient(app)
    response = client.post(
        "/api/qa",
        headers={"x-trace-id": "trace-123"},
        json={"question": "测试问题", "session_id": "sess-1"},
    )

    assert response.status_code == 200
    assert response.headers["x-trace-id"] == "trace-123"
    assert captured["trace_id"] == "trace-123"


def test_answer_question_enqueues_qa_turn_with_trace_id(monkeypatch) -> None:
    captured = {}

    monkeypatch.setattr(service, "get_recent_messages", lambda session_id, limit=10: [])
    monkeypatch.setattr(service, "save_message", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "save_retrieval_snapshot", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "rewrite_query", lambda question, history=None: question)
    monkeypatch.setattr(service, "retrieve_documents_with_scores", lambda **kwargs: [])
    monkeypatch.setattr(service, "rerank_with_details", lambda **kwargs: [])
    monkeypatch.setattr(
        service,
        "append_qa_turn_event",
        lambda **kwargs: captured.update(kwargs) or "evt-1",
    )

    result = service.answer_question(
        question="验证码怎么识别？",
        session_id="sess-qa",
        trace_id="trace-qa-001",
        use_query_rewrite=False,
        chat_client=DummyChatClient(),
    )

    assert result.answer == "推荐使用三层CNN加池化层进行验证码识别。"
    assert captured["trace_id"] == "trace-qa-001"
    assert captured["user_metadata"]["trace_id"] == "trace-qa-001"
    assert captured["assistant_metadata"]["trace_id"] == "trace-qa-001"


def test_enqueue_index_from_file_propagates_trace_id(monkeypatch) -> None:
    chunks = [
        Document(
            page_content="三层CNN用于验证码识别。",
            metadata={"source": "demo.docx", "title_path": "方法 > 模型结构"},
        ),
    ]
    captured = []

    monkeypatch.setattr(index_manager, "ingest_file", lambda path, chunking_config=None: chunks)
    monkeypatch.setattr(
        index_manager,
        "append_index_chunk_event",
        lambda **kwargs: captured.append(kwargs) or "evt-1",
    )

    with bind_trace_id("trace-index-001"):
        events = index_manager.enqueue_index_from_file(
            "demo.docx",
            collection_name="document_indexing",
            persist_directory="E:/tmp/chroma",
        )

    assert events == ["evt-1"]
    assert captured[0]["trace_id"] == "trace-index-001"
    assert captured[0]["chunk_metadata"]["trace_id"] == "trace-index-001"


def test_vector_worker_success_persists_trace_id(monkeypatch) -> None:
    acked: list[str] = []
    document_store = DummyMySQLStore()
    vector_store = DummyVectorStore()

    monkeypatch.setattr(
        vector_worker,
        "read_index_chunk_events",
        lambda **kwargs: [
            (
                "rag:index-events",
                [
                    (
                        "evt-1",
                        {
                            "event_type": "index_chunk",
                            "collection_name": "document_indexing",
                            "backend": "chroma",
                            "persist_directory": "E:/tmp/chroma",
                            "embedding_model": "text-embedding-v1",
                            "trace_id": "trace-worker-001",
                            "chunk_text": "三层CNN用于验证码识别。",
                            "chunk_metadata": '{"source": "demo.docx", "title_path": "方法 > 模型结构"}',
                        },
                    ),
                ],
            ),
        ],
    )
    monkeypatch.setattr(
        vector_worker,
        "ack_index_chunk_event",
        lambda event_id, **kwargs: acked.append(str(event_id)) or 1,
    )
    monkeypatch.setattr(vector_worker, "get_mysql_store", lambda: document_store)
    monkeypatch.setattr(vector_worker, "load_index", lambda **kwargs: vector_store)
    monkeypatch.setattr(vector_worker, "is_already_processed", lambda key: False)
    monkeypatch.setattr(vector_worker, "mark_processed", lambda *args, **kwargs: None)
    monkeypatch.setattr(vector_worker, "clear_retry", lambda *args, **kwargs: None)

    worker = vector_worker.VectorWorker(
        collection_name="document_indexing", persist_directory="E:/tmp/chroma", max_retries=3
    )
    count = worker.process_once()

    assert count == 1
    assert acked == ["evt-1"]
    assert document_store.documents[0]["metadata"]["trace_id"] == "trace-worker-001"
    assert document_store.embeddings[0]["metadata"]["trace_id"] == "trace-worker-001"


def test_vector_worker_duplicate_event_is_skipped(monkeypatch) -> None:
    acked: list[str] = []
    document_store = DummyMySQLStore()

    monkeypatch.setattr(
        vector_worker,
        "read_index_chunk_events",
        lambda **kwargs: [
            (
                "rag:index-events",
                [
                    (
                        "evt-dup",
                        {
                            "event_type": "index_chunk",
                            "collection_name": "document_indexing",
                            "trace_id": "trace-worker-dup",
                            "chunk_text": "三层CNN用于验证码识别。",
                            "chunk_metadata": "{}",
                        },
                    ),
                ],
            ),
        ],
    )
    monkeypatch.setattr(
        vector_worker,
        "ack_index_chunk_event",
        lambda event_id, **kwargs: acked.append(str(event_id)) or 1,
    )
    monkeypatch.setattr(vector_worker, "get_mysql_store", lambda: document_store)
    monkeypatch.setattr(vector_worker, "load_index", lambda **kwargs: DummyVectorStore())
    monkeypatch.setattr(vector_worker, "is_already_processed", lambda key: True)
    monkeypatch.setattr(vector_worker, "clear_retry", lambda *args, **kwargs: None)

    worker = vector_worker.VectorWorker(
        collection_name="document_indexing", persist_directory="E:/tmp/chroma"
    )
    count = worker.process_once()

    assert count == 0
    assert acked == ["evt-dup"]
    assert document_store.documents == []
    assert document_store.embeddings == []


def test_vector_worker_deadletters_after_max_retries(monkeypatch) -> None:
    acked: list[str] = []
    dlq_calls: list[dict] = []

    monkeypatch.setattr(
        vector_worker,
        "read_index_chunk_events",
        lambda **kwargs: [
            (
                "rag:index-events",
                [
                    (
                        "evt-fail",
                        {
                            "event_type": "index_chunk",
                            "collection_name": "document_indexing",
                            "trace_id": "trace-worker-fail",
                            "chunk_text": "三层CNN用于验证码识别。",
                            "chunk_metadata": "{}",
                        },
                    ),
                ],
            ),
        ],
    )
    monkeypatch.setattr(
        vector_worker,
        "ack_index_chunk_event",
        lambda event_id, **kwargs: acked.append(str(event_id)) or 1,
    )
    monkeypatch.setattr(vector_worker, "get_mysql_store", lambda: DummyMySQLStore())
    monkeypatch.setattr(vector_worker, "load_index", lambda **kwargs: FailingVectorStore())
    monkeypatch.setattr(vector_worker, "is_already_processed", lambda key: False)
    monkeypatch.setattr(vector_worker, "increment_retry", lambda *args, **kwargs: 1)
    monkeypatch.setattr(
        vector_worker, "send_to_dead_letter", lambda **kwargs: dlq_calls.append(kwargs) or "dlq-1"
    )
    monkeypatch.setattr(vector_worker, "clear_retry", lambda *args, **kwargs: None)
    monkeypatch.setattr(vector_worker.time, "sleep", lambda *args, **kwargs: None)

    worker = vector_worker.VectorWorker(
        collection_name="document_indexing", persist_directory="E:/tmp/chroma", max_retries=1
    )
    count = worker.process_once()

    assert count == 0
    assert acked == ["evt-fail"]
    assert dlq_calls[0]["trace_id"] == "trace-worker-fail"
    assert dlq_calls[0]["event_id"] == "evt-fail"


def test_persist_worker_deadletters_after_max_retries(monkeypatch) -> None:
    acked: list[str] = []
    dlq_calls: list[dict] = []

    monkeypatch.setattr(persist_worker.PersistWorker, "_claim_and_process_pending", lambda self: 0)
    monkeypatch.setattr(
        persist_worker,
        "read_qa_turn_events",
        lambda **kwargs: [
            (
                "rag:events",
                [
                    (
                        "evt-qa-fail",
                        {
                            "event_type": "qa_turn",
                            "session_id": "sess-1",
                            "trace_id": "trace-qa-fail",
                            "question": "Q",
                            "answer": "A",
                            "conversation_title": "t",
                            "user_message_id": "u1",
                            "assistant_message_id": "a1",
                            "user_metadata": "{}",
                            "assistant_metadata": "{}",
                            "snapshot": "[]",
                        },
                    ),
                ],
            ),
        ],
    )
    monkeypatch.setattr(persist_worker, "record_chat_turn", lambda **kwargs: False)
    monkeypatch.setattr(
        persist_worker,
        "ack_qa_turn_event",
        lambda event_id, **kwargs: acked.append(str(event_id)) or 1,
    )
    monkeypatch.setattr(persist_worker, "is_already_processed", lambda key: False)
    monkeypatch.setattr(persist_worker, "increment_retry", lambda *args, **kwargs: 1)
    monkeypatch.setattr(
        persist_worker, "send_to_dead_letter", lambda **kwargs: dlq_calls.append(kwargs) or "dlq-1"
    )
    monkeypatch.setattr(persist_worker, "clear_retry", lambda *args, **kwargs: None)
    monkeypatch.setattr(persist_worker.time, "sleep", lambda *args, **kwargs: None)

    worker = persist_worker.PersistWorker(batch_size=10, max_retries=1)
    count = worker.process_once()

    assert count == 0
    assert acked == ["evt-qa-fail"]
    assert dlq_calls[0]["trace_id"] == "trace-qa-fail"
    assert dlq_calls[0]["event_id"] == "evt-qa-fail"
