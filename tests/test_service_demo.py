from langchain_core.documents import Document

from rag.api import service as service_module
from rag.api.service import answer_question
from rag.retrieval import RetrievedDocument, RerankedDocument


class DummyChatClient:
	def complete(self, prompt: str, system_prompt: str = "") -> str:
		# 验证 service 确实把上下文拼进了提示词
		assert "片段 1" in prompt
		assert "三层CNN" in prompt
		return "推荐使用三层CNN加池化层进行验证码识别。"


def test_service_demo(monkeypatch) -> None:
	"""service demo：演示改写-检索-重排-回答编排。"""

	def fake_retrieve_documents_with_scores(*args, **kwargs):
		doc = Document(
			page_content="模型结构采用三层CNN加池化层。",
			metadata={"source": "demo.docx", "title_path": "研究方法 > 模型结构"},
		)
		return [
			RetrievedDocument(
				document=doc,
				rank=1,
				score=0.91,
				query="验证码识别方法",
				rewritten_query="验证码识别方法",
			)
		]

	def fake_rerank_with_details(*args, **kwargs):
		doc = Document(
			page_content="模型结构采用三层CNN加池化层。",
			metadata={"source": "demo.docx", "title_path": "研究方法 > 模型结构", "original_score": 0.91},
		)
		return [
			RerankedDocument(
				document=doc,
				rank=1,
				rerank_score=0.99,
				original_rank=1,
				original_score=0.91,
			)
		]

	monkeypatch.setattr(service_module, "retrieve_documents_with_scores", fake_retrieve_documents_with_scores)
	monkeypatch.setattr(service_module, "rerank_with_details", fake_rerank_with_details)

	result = answer_question(
		question="验证码识别方法是什么？",
		top_k=3,
		top_n=1,
		use_query_rewrite=False,
		chat_client=DummyChatClient(),
	)

	assert result.question == "验证码识别方法是什么？"
	assert result.rewritten_question == "验证码识别方法是什么？"
	assert "三层CNN" in result.answer
	assert len(result.contexts) == 1
	assert result.contexts[0].source == "demo.docx"
	assert result.contexts[0].rerank_score == 0.99