"""检索层统一入口。"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from langchain_chroma import Chroma
from langchain_core.documents import Document

from ..indexes import DEFAULT_COLLECTION_NAME, DEFAULT_INDEX_BACKEND, DEFAULT_PERSIST_DIRECTORY, load_index
from .query_rewrite import rewrite_query


DEFAULT_TOP_K = 6
DEFAULT_SEARCH_TYPE = "similarity"


@dataclass(slots=True)
class RetrievedDocument:
	"""检索结果包装。"""

	document: Document
	rank: int
	score: float | None = None
	query: str | None = None
	rewritten_query: str | None = None


@dataclass(slots=True)
class RetrieverService:
	"""面向业务的检索服务。"""

	collection_name: str = DEFAULT_COLLECTION_NAME
	persist_directory: str | Path | None = None
	backend: str = DEFAULT_INDEX_BACKEND
	default_top_k: int = DEFAULT_TOP_K
	default_search_type: str = DEFAULT_SEARCH_TYPE
	default_use_query_rewrite: bool = False
	vector_store: Chroma | None = field(default=None, repr=False)

	def _normalize_search_type(self, search_type: str | None) -> str:
		mode = (search_type or self.default_search_type).strip().lower()
		if mode not in {"similarity", "mmr"}:
			raise ValueError(f"不支持的检索方式: {search_type}")
		return mode

	def _resolve_top_k(self, top_k: int | None) -> int:
		resolved = top_k if top_k is not None else self.default_top_k
		if resolved <= 0:
			raise ValueError("top_k 必须大于 0")
		return resolved

	def _normalize_backend(self) -> str:
		backend_name = self.backend.strip().lower()
		if backend_name != DEFAULT_INDEX_BACKEND:
			raise ValueError(f"不支持的索引后端: {self.backend}")
		return backend_name

	def _resolve_vector_store(self) -> Chroma:
		if self.vector_store is not None:
			return self.vector_store
		self._normalize_backend()
		self.vector_store = load_index(
			collection_name=self.collection_name,
			persist_directory=self.persist_directory or DEFAULT_PERSIST_DIRECTORY,
			backend=self.backend,
		)
		return self.vector_store

	def build_retriever(
		self,
		search_type: str | None = None,
		top_k: int | None = None,
	) -> Any:
		"""返回 LangChain 的 retriever 对象。"""
		vector_store = self._resolve_vector_store()
		mode = self._normalize_search_type(search_type)
		k = self._resolve_top_k(top_k)
		return vector_store.as_retriever(search_type=mode, search_kwargs={"k": k})

	def prepare_query(
		self,
		query: str,
		history: Iterable[str] | None = None,
		use_query_rewrite: bool | None = None,
	) -> str:
		"""根据配置决定是否先进行查询改写。"""
		if not query or not query.strip():
			raise ValueError("query 不能为空")

		should_rewrite = self.default_use_query_rewrite if use_query_rewrite is None else use_query_rewrite
		if should_rewrite:
			return rewrite_query(query=query, history=history)
		return query.strip()

	def search(
		self,
		query: str,
		history: Iterable[str] | None = None,
		top_k: int | None = None,
		search_type: str | None = None,
		use_query_rewrite: bool | None = None,
	) -> list[Document]:
		"""检索文档列表。"""
		prepared_query = self.prepare_query(query=query, history=history, use_query_rewrite=use_query_rewrite)
		vector_store = self._resolve_vector_store()
		mode = self._normalize_search_type(search_type)
		k = self._resolve_top_k(top_k)

		if mode == "mmr":
			return vector_store.max_marginal_relevance_search(prepared_query, k=k)
		return vector_store.similarity_search(prepared_query, k=k)

	def search_with_scores(
		self,
		query: str,
		history: Iterable[str] | None = None,
		top_k: int | None = None,
		use_query_rewrite: bool | None = None,
	) -> list[RetrievedDocument]:
		"""检索文档并返回分数包装结果。"""
		prepared_query = self.prepare_query(query=query, history=history, use_query_rewrite=use_query_rewrite)
		vector_store = self._resolve_vector_store()
		k = self._resolve_top_k(top_k)
		raw_results = vector_store.similarity_search_with_score(prepared_query, k=k)

		results: list[RetrievedDocument] = []
		for rank, (document, score) in enumerate(raw_results, start=1):
			metadata = dict(document.metadata or {})
			metadata["retrieval_rank"] = rank
			metadata["retrieval_score"] = score
			metadata["retrieval_query"] = query
			if prepared_query != query.strip():
				metadata["rewritten_query"] = prepared_query

			enriched_document = Document(page_content=document.page_content, metadata=metadata)
			results.append(
				RetrievedDocument(
					document=enriched_document,
					rank=rank,
					score=score,
					query=query,
					rewritten_query=prepared_query if prepared_query != query.strip() else None,
				)
			)
		return results


def build_retriever_service(
	collection_name: str = DEFAULT_COLLECTION_NAME,
	persist_directory: str | Path | None = None,
	backend: str = DEFAULT_INDEX_BACKEND,
	default_top_k: int = DEFAULT_TOP_K,
	default_search_type: str = DEFAULT_SEARCH_TYPE,
	default_use_query_rewrite: bool = False,
	vector_store: Chroma | None = None,
) -> RetrieverService:
	"""创建检索服务。"""
	return RetrieverService(
		collection_name=collection_name,
		persist_directory=persist_directory,
		backend=backend,
		default_top_k=default_top_k,
		default_search_type=default_search_type,
		default_use_query_rewrite=default_use_query_rewrite,
		vector_store=vector_store,
	)


def retrieve_documents(
	query: str,
	history: Iterable[str] | None = None,
	top_k: int = DEFAULT_TOP_K,
	search_type: str = DEFAULT_SEARCH_TYPE,
	use_query_rewrite: bool = False,
	collection_name: str = DEFAULT_COLLECTION_NAME,
	persist_directory: str | Path | None = None,
	backend: str = DEFAULT_INDEX_BACKEND,
) -> list[Document]:
	"""直接检索文档列表的便捷函数。"""
	service = build_retriever_service(
		collection_name=collection_name,
		persist_directory=persist_directory,
		backend=backend,
		default_top_k=top_k,
		default_search_type=search_type,
		default_use_query_rewrite=use_query_rewrite,
	)
	return service.search(
		query=query,
		history=history,
		top_k=top_k,
		search_type=search_type,
		use_query_rewrite=use_query_rewrite,
	)


def retrieve_documents_with_scores(
	query: str,
	history: Iterable[str] | None = None,
	top_k: int = DEFAULT_TOP_K,
	use_query_rewrite: bool = False,
	collection_name: str = DEFAULT_COLLECTION_NAME,
	persist_directory: str | Path | None = None,
	backend: str = DEFAULT_INDEX_BACKEND,
) -> list[RetrievedDocument]:
	"""直接检索并返回分数包装结果的便捷函数。"""
	service = build_retriever_service(
		collection_name=collection_name,
		persist_directory=persist_directory,
		backend=backend,
		default_top_k=top_k,
		default_use_query_rewrite=use_query_rewrite,
	)
	return service.search_with_scores(
		query=query,
		history=history,
		top_k=top_k,
		use_query_rewrite=use_query_rewrite,
	)
