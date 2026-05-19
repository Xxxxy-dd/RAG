from types import SimpleNamespace

from rag.indexes import DEFAULT_COLLECTION_NAME, DEFAULT_PERSIST_DIRECTORY
from rag.models import rerank_client as rerank_client_module
from rag.retrieval import (
	rerank_documents,
	retrieve_documents,
	retrieve_documents_with_scores,
	rewrite_query,
)


class DummyChatClient:
	def complete(self, prompt: str, system_prompt: str | None = None) -> str:
		return "验证码识别"


def test_retrieval_smoke(monkeypatch) -> None:
	"""最小 smoke test：验证 retrieval 的改写、检索和重排流程可用。"""
	# 1) 查询改写：用注入的假客户端，避免真实 LLM 调用
	rewritten_query = rewrite_query("  这个验证码怎么识别？  ", client=DummyChatClient())
	assert rewritten_query == "验证码识别"

	# 2) 基于现有 chroma_db 的检索与带分数检索
	documents = retrieve_documents(
		query="验证码",
		top_k=2,
		collection_name=DEFAULT_COLLECTION_NAME,
		persist_directory=DEFAULT_PERSIST_DIRECTORY,
	)
	assert documents, "chroma_db 中应至少能检索到 1 条结果"

	documents_with_scores = retrieve_documents_with_scores(
		query="验证码",
		top_k=2,
		collection_name=DEFAULT_COLLECTION_NAME,
		persist_directory=DEFAULT_PERSIST_DIRECTORY,
	)
	assert documents_with_scores
	assert documents_with_scores[0].document.page_content
	assert documents_with_scores[0].score is not None

	# 3) 重排：让 RerankClient 走假的远端配置和假的分数返回，避免真实网络调用
	def fake_get_settings() -> SimpleNamespace:
		return SimpleNamespace(
			rerank_mode="remote",
			rerank_model="dummy-reranker",
			rerank_api_key="test-api-key",
			rerank_base_url="https://example.com/v1",
			rerank_timeout=1,
		)

	monkeypatch.setattr(rerank_client_module, "get_settings", fake_get_settings)
	monkeypatch.setattr(rerank_client_module.RerankClient, "score", lambda self, query, documents: list(range(len(documents), 0, -1)))

	reranked_documents = rerank_documents(
		query="验证码",
		documents=documents_with_scores,
		top_n=1,
	)
	assert len(reranked_documents) == 1
	assert reranked_documents[0].page_content
	assert reranked_documents[0].metadata.get("rerank_score") is not None