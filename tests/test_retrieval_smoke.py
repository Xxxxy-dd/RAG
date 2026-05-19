from types import SimpleNamespace

from langchain_core.documents import Document

from rag.models import rerank_client as rerank_client_module
from rag.retrieval import RetrieverService, rerank_documents, rewrite_query


class DummyChatClient:
    def complete(self, prompt: str, system_prompt: str | None = None) -> str:
        return "captcha recognition"


class DummyVectorStore:
    def __init__(self) -> None:
        self.documents = [
            Document(
                page_content="Captcha recognition can use a CNN to extract image features.",
                metadata={"source": "demo.pdf", "title_path": "model"},
            ),
            Document(
                page_content="The pipeline preprocesses the image before classification.",
                metadata={"source": "demo.pdf", "title_path": "pipeline"},
            ),
        ]

    def similarity_search(self, query: str, k: int):
        return self.documents[:k]

    def similarity_search_with_score(self, query: str, k: int):
        return [(document, 0.1 + index) for index, document in enumerate(self.documents[:k])]


def test_retrieval_smoke(monkeypatch) -> None:
    """Verify query rewrite, retrieval, scored retrieval, and reranking without local Chroma state."""
    rewritten_query = rewrite_query("  How should this captcha be recognized?  ", client=DummyChatClient())
    assert rewritten_query == "captcha recognition"

    service = RetrieverService(vector_store=DummyVectorStore())
    documents = service.search(query="captcha", top_k=2)
    assert len(documents) == 2
    assert documents[0].metadata["source"] == "demo.pdf"

    documents_with_scores = service.search_with_scores(query="captcha", top_k=2)
    assert len(documents_with_scores) == 2
    assert documents_with_scores[0].document.page_content
    assert documents_with_scores[0].score is not None

    def fake_get_settings() -> SimpleNamespace:
        return SimpleNamespace(
            rerank_mode="remote",
            rerank_model="dummy-reranker",
            rerank_api_key="test-api-key",
            rerank_base_url="https://example.com/v1",
            rerank_timeout=1,
        )

    monkeypatch.setattr(rerank_client_module, "get_settings", fake_get_settings)
    monkeypatch.setattr(
        rerank_client_module.RerankClient,
        "score",
        lambda self, query, documents: list(range(len(documents), 0, -1)),
    )

    reranked_documents = rerank_documents(
        query="captcha",
        documents=documents_with_scores,
        top_n=1,
    )
    assert len(reranked_documents) == 1
    assert reranked_documents[0].page_content
    assert reranked_documents[0].metadata.get("rerank_score") is not None
