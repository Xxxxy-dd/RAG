from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence
import logging
import uuid

from ..indexes import DEFAULT_COLLECTION_NAME, DEFAULT_PERSIST_DIRECTORY
from ..models import ChatClient
from ..retrieval import (
    RetrievedDocument,
    RerankedDocument,
    rerank_with_details,
    retrieve_documents_with_scores,
    rewrite_query,
)
from ..memory.redis_memory import (
    append_qa_turn_event,
    get_recent_messages,
    save_message,
    save_retrieval_snapshot,
)
from ..observability import get_trace_id


DEFAULT_TOP_K = 6
DEFAULT_TOP_N = 4


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ContextChunk:
    index: int
    text: str
    source: str | None
    title_path: str | None
    retrieval_score: float | None
    rerank_score: float | None


@dataclass(slots=True)
class QAServiceResult:
    question: str
    rewritten_question: str
    answer: str
    contexts: list[ContextChunk]


def _to_context_chunk_from_reranked(index: int, item: RerankedDocument) -> ContextChunk:
    metadata = dict(item.document.metadata or {})
    return ContextChunk(
        index=index,
        text=item.document.page_content,
        source=metadata.get("source"),
        title_path=metadata.get("title_path"),
        retrieval_score=metadata.get("original_score"),
        rerank_score=item.rerank_score,
    )


def _to_context_chunk_from_retrieved(index: int, item: RetrievedDocument) -> ContextChunk:
    metadata = dict(item.document.metadata or {})
    return ContextChunk(
        index=index,
        text=item.document.page_content,
        source=metadata.get("source"),
        title_path=metadata.get("title_path"),
        retrieval_score=item.score,
        rerank_score=None,
    )


def _format_context_for_prompt(chunks: Sequence[ContextChunk]) -> str:
    if not chunks:
        return "无可用上下文"

    sections: list[str] = []
    for chunk in chunks:
        header = (
            f"[片段 {chunk.index}]"
            f" source={chunk.source or 'unknown'}"
            f" title_path={chunk.title_path or 'ROOT'}"
            f" retrieval_score={chunk.retrieval_score}"
            f" rerank_score={chunk.rerank_score}"
        )
        sections.append(f"{header}\n{chunk.text.strip()}")
    return "\n\n".join(sections)


def _build_answer_prompt(
    question: str, rewritten_question: str, chunks: Sequence[ContextChunk]
) -> str:
    context_text = _format_context_for_prompt(chunks)
    return (
        "你将基于给定上下文回答用户问题。\n"
        "要求:\n"
        "1. 优先使用上下文中的事实，不要编造；\n"
        "2. 若上下文信息不足，明确说明不足点；\n"
        "3. 回答简洁、有条理，可用编号。\n\n"
        f"原始问题:\n{question.strip()}\n\n"
        f"检索查询:\n{rewritten_question.strip()}\n\n"
        f"上下文:\n{context_text}\n"
    )


def answer_question(
    question: str,
    history: Iterable[str] | None = None,
    *,
    session_id: str | None = None,
    trace_id: str | None = None,
    top_k: int = DEFAULT_TOP_K,
    top_n: int = DEFAULT_TOP_N,
    use_query_rewrite: bool = True,
    collection_name: str = DEFAULT_COLLECTION_NAME,
    persist_directory: str | Path | None = None,
    chat_client: ChatClient | None = None,
) -> QAServiceResult:
    """RAG 编排入口：改写 -> 检索 -> 重排 -> 拼接 -> 回答。"""
    active_trace_id = (trace_id or get_trace_id() or uuid.uuid4().hex).strip()
    if not question or not question.strip():
        raise ValueError("question 不能为空")

    raw_question = question.strip()
    # 若提供 session_id，则优先加载短期会话记忆并合并到 history
    merged_history: list[str] = []
    if session_id:
        try:
            recent = get_recent_messages(session_id, limit=10)
            for item in recent:
                role = item.get("role")
                text = item.get("text")
                if role and text:
                    merged_history.append(f"{role}: {text}")
        except Exception as exc:
            # 记忆服务不可用时降级为仅使用显式 history，但保留日志便于排障。
            LOGGER.warning(
                "Failed to load recent messages for session_id=%s: %s",
                session_id,
                exc,
                exc_info=True,
            )
            merged_history = []

    if history:
        merged_history.extend(list(history))

    rewritten_question = (
        rewrite_query(raw_question, history=merged_history) if use_query_rewrite else raw_question
    )
    LOGGER.info(
        "qa_orchestration_started",
        extra={
            "event": "qa_orchestration_started",
            "trace_id": active_trace_id,
            "session_id": session_id,
            "top_k": top_k,
            "top_n": top_n,
            "collection_name": collection_name,
        },
    )

    retrieved = retrieve_documents_with_scores(
        query=rewritten_question,
        top_k=top_k,
        use_query_rewrite=False,
        collection_name=collection_name,
        persist_directory=persist_directory or DEFAULT_PERSIST_DIRECTORY,
    )

    reranked = rerank_with_details(
        query=rewritten_question,
        documents=retrieved,
        top_n=top_n,
    )

    context_chunks: list[ContextChunk] = []
    if reranked:
        context_chunks = [
            _to_context_chunk_from_reranked(index=i, item=item)
            for i, item in enumerate(reranked, start=1)
        ]
    elif retrieved:
        context_chunks = [
            _to_context_chunk_from_retrieved(index=i, item=item)
            for i, item in enumerate(retrieved[:top_n], start=1)
        ]

    prompt = _build_answer_prompt(raw_question, rewritten_question, context_chunks)
    client = chat_client or ChatClient()
    answer = client.complete(
        prompt=prompt, system_prompt="你是严谨的知识库问答助手，请基于上下文回答。"
    )
    turn_id = uuid.uuid4().hex
    user_message_id = f"{turn_id}-u"
    assistant_message_id = f"{turn_id}-a"

    # 保存会话消息与检索快照到短期记忆
    if session_id:
        try:
            save_message(session_id, role="user", text=raw_question)
            save_message(session_id, role="assistant", text=answer)
            snapshot = []
            for c in context_chunks:
                snapshot.append(
                    {
                        "index": c.index,
                        "source": c.source,
                        "title_path": c.title_path,
                        "retrieval_score": c.retrieval_score,
                        "rerank_score": c.rerank_score,
                    }
                )
            save_retrieval_snapshot(session_id, snapshot)
            # NOTE: 持久化改为由后台 worker 专门负责（worker-only 模式），
            # 这里仅把会话写入短期 Redis，并把事件投递到 Redis Stream 供 worker 消费。
            append_qa_turn_event(
                session_id=session_id,
                trace_id=active_trace_id,
                question=raw_question,
                answer=answer,
                conversation_title=raw_question[:120],
                user_message_id=user_message_id,
                assistant_message_id=assistant_message_id,
                user_metadata={
                    "source": "api",
                    "kind": "question",
                    "turn_id": turn_id,
                    "trace_id": active_trace_id,
                },
                assistant_metadata={
                    "source": "api",
                    "kind": "answer",
                    "turn_id": turn_id,
                    "trace_id": active_trace_id,
                },
                snapshot=snapshot,
            )
        except Exception:
            # 持久化失败不阻断主回答返回，但日志必须可见。
            LOGGER.exception(
                "Failed to persist QA turn for session_id=%s",
                session_id,
                extra={"event": "qa_turn_enqueue_failed", "trace_id": active_trace_id},
            )

    LOGGER.info(
        "qa_orchestration_finished",
        extra={
            "event": "qa_orchestration_finished",
            "trace_id": active_trace_id,
            "session_id": session_id,
            "context_count": len(context_chunks),
        },
    )

    return QAServiceResult(
        question=raw_question,
        rewritten_question=rewritten_question,
        answer=answer,
        contexts=context_chunks,
    )


__all__ = [
    "ContextChunk",
    "QAServiceResult",
    "answer_question",
]
