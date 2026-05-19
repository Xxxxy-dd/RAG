from langchain_core.documents import Document

from rag.indexes import index_manager
from rag.workers import vector_worker


class DummyEmbeddings:
    model = "text-embedding-v1"


class DummyVectorStore:
    def __init__(self):
        self.calls = []

    def update_documents(self, ids, documents):
        self.calls.append(("update_documents", ids, [doc.page_content for doc in documents]))

    def add_documents(self, documents, ids):
        self.calls.append(("add_documents", ids, [doc.page_content for doc in documents]))


class DummyStore:
    def __init__(self):
        self.documents = []
        self.embeddings = []

    def save_document(self, **kwargs):
        self.documents.append(kwargs)
        return {"id": 11}

    def save_embedding(self, **kwargs):
        self.embeddings.append(kwargs)
        return {"id": 22}


def test_enqueue_index_from_file(monkeypatch) -> None:
    chunks = [
        Document(
            page_content="三层CNN用于验证码识别。",
            metadata={
                "source": "demo.docx",
                "title_path": "方法 > 模型结构",
                "section_id": 2,
                "chunk_id": 1,
            },
        ),
        Document(
            page_content="池化层用于下采样。",
            metadata={
                "source": "demo.docx",
                "title_path": "方法 > 模型结构",
                "section_id": 2,
                "chunk_id": 2,
            },
        ),
    ]
    calls = []

    monkeypatch.setattr(index_manager, "ingest_file", lambda path, chunking_config=None: chunks)
    monkeypatch.setattr(
        index_manager,
        "append_index_chunk_event",
        lambda **kwargs: calls.append(kwargs) or f"evt-{len(calls)}",
    )

    events = index_manager.enqueue_index_from_file(
        "demo.docx",
        collection_name="document_indexing",
        persist_directory="E:/tmp/chroma",
    )

    assert events == ["evt-1", "evt-2"]
    assert calls[0]["chunk_text"] == "三层CNN用于验证码识别。"
    assert calls[0]["collection_name"] == "document_indexing"
    assert calls[1]["chunk_metadata"]["chunk_id"] == 2


def test_vector_worker_process_once(monkeypatch) -> None:
    calls = []

    def fake_read_index_chunk_events(**kwargs):
        return [
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
                            "chunk_text": "三层CNN用于验证码识别。",
                            "chunk_metadata": '{"source": "demo.docx", "title_path": "方法 > 模型结构", "section_id": 2, "chunk_id": 1}',
                        },
                    ),
                ],
            ),
        ]

    monkeypatch.setattr(vector_worker, "read_index_chunk_events", fake_read_index_chunk_events)
    monkeypatch.setattr(
        vector_worker,
        "ack_index_chunk_event",
        lambda event_id, **kwargs: calls.append(("ack", event_id)) or 1,
    )
    monkeypatch.setattr(vector_worker, "get_mysql_store", lambda: DummyStore())
    monkeypatch.setattr(vector_worker, "load_index", lambda **kwargs: DummyVectorStore())
    monkeypatch.setattr(vector_worker, "is_already_processed", lambda key: False)
    monkeypatch.setattr(vector_worker, "mark_processed", lambda *args, **kwargs: None)
    monkeypatch.setattr(vector_worker, "clear_retry", lambda *args, **kwargs: None)

    worker = vector_worker.VectorWorker(
        collection_name="document_indexing", persist_directory="E:/tmp/chroma"
    )
    count = worker.process_once()

    assert count == 1
    assert calls[0] == ("ack", "evt-1")
