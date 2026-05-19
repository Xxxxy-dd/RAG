from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class QARequest(BaseModel):
    question: str = Field(..., description="用户问题")
    history: List[str] | None = Field(default=None, description="对话历史")
    session_id: str | None = Field(default=None, description="会话 ID，用于短期记忆检索")
    top_k: int = Field(default=6, ge=1, le=50, description="检索候选数")
    top_n: int = Field(default=4, ge=1, le=20, description="重排后保留数")
    use_query_rewrite: bool = Field(default=True, description="是否启用查询改写")
    collection_name: str = Field(default="document_indexing", description="Chroma 集合名称")
    persist_directory: str | None = Field(default=None, description="Chroma 持久化目录")


class ContextChunkResponse(BaseModel):
    index: int
    text: str
    source: str | None
    title_path: str | None
    retrieval_score: float | None
    rerank_score: float | None


class QAResponse(BaseModel):
    question: str
    rewritten_question: str
    answer: str
    contexts: List[ContextChunkResponse]


__all__ = ["QARequest", "ContextChunkResponse", "QAResponse"]
