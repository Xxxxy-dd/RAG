from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from .service import ContextChunk, QAServiceResult, answer_question
from ..memory.redis_memory import clear_session
from ..observability import get_trace_id
from ..storage import list_session_messages
from .schemas import QARequest, QAResponse, ContextChunkResponse


router = APIRouter(prefix="/api", tags=["rag"])
LOGGER = logging.getLogger(__name__)


def _to_response(result: QAServiceResult) -> QAResponse:
	contexts = [
		ContextChunkResponse(
			index=item.index,
			text=item.text,
			source=item.source,
			title_path=item.title_path,
			retrieval_score=item.retrieval_score,
			rerank_score=item.rerank_score,
		)
		for item in result.contexts
	]
	return QAResponse(
		question=result.question,
		rewritten_question=result.rewritten_question,
		answer=result.answer,
		contexts=contexts,
	)


@router.get("/health")
def health() -> dict[str, str]:
	return {"status": "ok"}


@router.post("/qa", response_model=QAResponse)
def qa(request: QARequest, http_request: Request) -> QAResponse:
	trace_id = getattr(http_request.state, "trace_id", "") or get_trace_id()
	try:
		LOGGER.info("qa_request_received", extra={"event": "qa_request_received", "trace_id": trace_id, "session_id": request.session_id})
		result = answer_question(
			question=request.question,
			history=request.history,
			session_id=request.session_id,
			top_k=request.top_k,
			top_n=request.top_n,
			use_query_rewrite=request.use_query_rewrite,
			collection_name=request.collection_name,
			persist_directory=Path(request.persist_directory) if request.persist_directory else None,
			trace_id=trace_id,
		)
		return _to_response(result)
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc)) from exc
	except Exception as exc:
		LOGGER.exception("QA request failed", extra={"event": "qa_request_failed", "trace_id": trace_id, "session_id": request.session_id})
		raise HTTPException(status_code=500, detail="RAG 服务暂时不可用") from exc


__all__ = [
	"router",
	"QARequest",
	"QAResponse",
]


@router.delete("/session/{session_id}")
def delete_session(session_id: str) -> dict:
	"""清空指定 session 的短期记忆（history 和 last_retrieved）。"""
	try:
		clear_session(session_id)
		return {"status": "ok"}
	except Exception as exc:
		LOGGER.exception("Failed to delete session memory: %s", session_id)
		raise HTTPException(status_code=500, detail="RAG 服务暂时不可用") from exc


@router.get("/session/{session_id}/messages")
def session_messages(session_id: str, limit: int = 50) -> dict:
	"""返回 MySQL 中持久化的会话消息。"""
	try:
		messages = list_session_messages(session_id=session_id, limit=limit)
		return {"session_id": session_id, "count": len(messages), "messages": messages}
	except Exception as exc:
		LOGGER.exception("Failed to load session messages: %s", session_id)
		raise HTTPException(status_code=500, detail="RAG 服务暂时不可用") from exc
