"""重排层统一入口。"""

from dataclasses import dataclass, field
from typing import Sequence

from langchain_core.documents import Document

from ..models import RerankClient
from .retriever import RetrievedDocument


DEFAULT_RERANKER_MODEL = "BAAI/bge-reranker-base"
DEFAULT_RERANK_TOP_N = 4


@dataclass(slots=True)
class RerankedDocument:
    """重排结果包装。"""

    document: Document
    rank: int
    rerank_score: float
    original_rank: int | None = None
    original_score: float | None = None


@dataclass(slots=True)
class RerankerService:
    """面向业务的重排服务。"""

    model_name: str = DEFAULT_RERANKER_MODEL
    default_top_n: int = DEFAULT_RERANK_TOP_N
    device: str | None = None
    batch_size: int = 16
    client: RerankClient | None = field(default=None, repr=False)

    def _resolve_top_n(self, top_n: int | None, total: int) -> int:
        resolved = self.default_top_n if top_n is None else top_n
        if resolved <= 0:
            raise ValueError("top_n 必须大于 0")
        return min(resolved, total)

    def _resolve_client(self) -> RerankClient:
        if self.client is not None:
            return self.client
        self.client = RerankClient(
            model=self.model_name,
            device=self.device,
            batch_size=self.batch_size,
        )
        return self.client

    def _normalize_inputs(
        self,
        documents: Sequence[Document | RetrievedDocument],
    ) -> list[tuple[Document, int | None, float | None]]:
        normalized: list[tuple[Document, int | None, float | None]] = []
        for item in documents:
            if isinstance(item, RetrievedDocument):
                normalized.append((item.document, item.rank, item.score))
            else:
                normalized.append((item, None, None))
        return normalized

    def _compose_rerank_text(self, document: Document) -> str:
        """把标题路径与正文合并后再送入重排模型。"""
        page_content = (document.page_content or "").strip()
        title_path = ""
        if isinstance(document.metadata, dict):
            raw_title_path = document.metadata.get("title_path")
            if isinstance(raw_title_path, str):
                title_path = raw_title_path.strip()

        if title_path and page_content and not page_content.startswith(title_path):
            return f"{title_path}\n\n{page_content}"
        return page_content or title_path

    def rerank(
        self,
        query: str,
        documents: Sequence[Document | RetrievedDocument],
        top_n: int | None = None,
    ) -> list[RerankedDocument]:
        """对候选文档进行重排并返回包装结果。"""
        if not query or not query.strip():
            raise ValueError("query 不能为空")
        if not documents:
            return []

        normalized = self._normalize_inputs(documents)
        client = self._resolve_client()
        doc_texts = [self._compose_rerank_text(doc) for doc, _, _ in normalized]
        scores = client.score(query=query.strip(), documents=doc_texts)

        scored_items = []
        for idx, score in enumerate(scores):
            document, original_rank, original_score = normalized[idx]
            scored_items.append((float(score), document, original_rank, original_score))

        scored_items.sort(key=lambda item: item[0], reverse=True)
        limit = self._resolve_top_n(top_n=top_n, total=len(scored_items))

        results: list[RerankedDocument] = []
        for rank, (score, document, original_rank, original_score) in enumerate(
            scored_items[:limit], start=1
        ):
            metadata = dict(document.metadata or {})
            metadata["rerank_score"] = score
            metadata["rerank_rank"] = rank
            if original_rank is not None:
                metadata["original_rank"] = original_rank
            if original_score is not None:
                metadata["original_score"] = original_score

            enriched_doc = Document(page_content=document.page_content, metadata=metadata)
            results.append(
                RerankedDocument(
                    document=enriched_doc,
                    rank=rank,
                    rerank_score=score,
                    original_rank=original_rank,
                    original_score=original_score,
                )
            )
        return results

    def rerank_documents(
        self,
        query: str,
        documents: Sequence[Document | RetrievedDocument],
        top_n: int | None = None,
    ) -> list[Document]:
        """对候选文档重排并仅返回文档列表。"""
        return [
            item.document for item in self.rerank(query=query, documents=documents, top_n=top_n)
        ]


def build_reranker_service(
    model_name: str = DEFAULT_RERANKER_MODEL,
    default_top_n: int = DEFAULT_RERANK_TOP_N,
    device: str | None = None,
    batch_size: int = 16,
    client: RerankClient | None = None,
) -> RerankerService:
    """创建重排服务。"""
    return RerankerService(
        model_name=model_name,
        default_top_n=default_top_n,
        device=device,
        batch_size=batch_size,
        client=client,
    )


def rerank_documents(
    query: str,
    documents: Sequence[Document | RetrievedDocument],
    top_n: int = DEFAULT_RERANK_TOP_N,
    model_name: str = DEFAULT_RERANKER_MODEL,
    device: str | None = None,
    batch_size: int = 16,
) -> list[Document]:
    """便捷函数：重排并返回文档列表。"""
    service = build_reranker_service(
        model_name=model_name,
        default_top_n=top_n,
        device=device,
        batch_size=batch_size,
    )
    return service.rerank_documents(query=query, documents=documents, top_n=top_n)


def rerank_with_details(
    query: str,
    documents: Sequence[Document | RetrievedDocument],
    top_n: int = DEFAULT_RERANK_TOP_N,
    model_name: str = DEFAULT_RERANKER_MODEL,
    device: str | None = None,
    batch_size: int = 16,
) -> list[RerankedDocument]:
    """便捷函数：重排并返回带分数细节的结果。"""
    service = build_reranker_service(
        model_name=model_name,
        default_top_n=top_n,
        device=device,
        batch_size=batch_size,
    )
    return service.rerank(query=query, documents=documents, top_n=top_n)
