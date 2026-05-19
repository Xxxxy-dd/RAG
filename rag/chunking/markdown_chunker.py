"""Unified Markdown chunker for all loader outputs.

职责：
- 输入：各类 loader 输出的 Markdown `Document` 列表。
- 处理：先按 Markdown 标题语义切分，再按 token 长度补切。
- 输出：统一的 chunk `Document` 列表（保留来源元数据与标题路径）。
"""

from dataclasses import dataclass, field
import re
from typing import Callable, List, Sequence, Tuple

from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from ..config import get_settings

try:
    import tiktoken
except ImportError:  # pragma: no cover - optional dependency
    tiktoken = None


_TOKEN_ENCODER = None


def _normalize_text(text: str) -> str:
    """整理空白，避免切分时出现大量空块。"""
    if not text:
        return ""

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _token_length(text: str) -> int:
    """优先用 tiktoken 计数，没有则用字符近似。"""
    if not text:
        return 0

    if tiktoken is not None:
        try:
            global _TOKEN_ENCODER
            if _TOKEN_ENCODER is None:
                _TOKEN_ENCODER = tiktoken.get_encoding("cl100k_base")
            return len(_TOKEN_ENCODER.encode(text))
        except Exception:  # pragma: no cover - defensive fallback
            pass

    return max(1, len(text) // 2)


def _compose_title_path(metadata: dict) -> str:
    """从 h1-h6 和现有 title_path 组合稳定的标题路径。"""
    titles = []
    for i in range(1, 7):
        value = metadata.get(f"h{i}")
        if isinstance(value, str) and value.strip():
            titles.append(value.strip())

    if titles:
        return " > ".join(titles)

    existing = metadata.get("title_path")
    if isinstance(existing, str) and existing.strip():
        return existing.strip()

    fallback = metadata.get("document_title")
    if isinstance(fallback, str) and fallback.strip():
        return fallback.strip()

    return "ROOT"


def _prepend_title_context(text: str, metadata: dict) -> str:
    """把标题路径注入到 chunk 正文中，提升 embedding 和 rerank 的上下文可见性。"""
    clean_text = _normalize_text(text)
    if not clean_text:
        return ""

    title_path = _compose_title_path(metadata)
    if not title_path or title_path == "ROOT":
        return clean_text

    if clean_text.startswith(title_path):
        return clean_text

    return f"{title_path}\n\n{clean_text}"


def _is_title_only_chunk(text: str, metadata: dict, config: "ChunkingConfig") -> bool:
    """识别只有标题、没有实质正文的碎块。"""
    clean_text = _normalize_text(text)
    if not clean_text:
        return True

    plain_text = re.sub(r"^#+\s*", "", clean_text).strip()
    title_path = _compose_title_path(metadata)
    if title_path and plain_text == title_path:
        return True

    if len(plain_text) <= config.title_only_max_chars:
        if config.title_only_allow_punctuation:
            return True
        if not re.search(r"[。！？；：,.!?]", plain_text):
            return True

    return False


@dataclass
class ChunkingConfig:
    """统一切分参数。"""

    chunk_size: int = 700
    chunk_overlap: int = 150
    min_chunk_tokens: int = 80
    merge_max_tokens: int = 500
    title_only_max_chars: int | None = None
    title_only_allow_punctuation: bool | None = None
    length_function: Callable[[str], int] = _token_length
    headers_to_split_on: Sequence[Tuple[str, str]] = field(
        default_factory=lambda: [
            ("#", "h1"),
            ("##", "h2"),
            ("###", "h3"),
            ("####", "h4"),
            ("#####", "h5"),
            ("######", "h6"),
        ]
    )

    def __post_init__(self) -> None:
        settings = get_settings()
        if self.title_only_max_chars is None:
            self.title_only_max_chars = settings.chunk_title_only_max_chars
        if self.title_only_allow_punctuation is None:
            self.title_only_allow_punctuation = settings.chunk_title_only_allow_punctuation


def _should_merge_small_chunk(text: str, config: ChunkingConfig) -> bool:
    return config.length_function(text) < config.min_chunk_tokens


def _merge_adjacent_small_chunks(chunks: List[Document], config: ChunkingConfig) -> List[Document]:
    """把相邻短块做保守合并，减少碎片化召回。"""
    merged: List[Document] = []

    for chunk in chunks:
        chunk.page_content = _normalize_text(chunk.page_content)
        chunk.metadata = chunk.metadata or {}

        if not chunk.page_content:
            continue

        if not merged:
            merged.append(chunk)
            continue

        prev = merged[-1]
        same_source = prev.metadata.get("source") == chunk.metadata.get("source")
        same_path = prev.metadata.get("title_path") == chunk.metadata.get("title_path")

        if (
            same_source
            and same_path
            and _should_merge_small_chunk(chunk.page_content, config)
        ):
            prev.page_content = _normalize_text(prev.page_content + "\n" + chunk.page_content)
            prev.metadata["merged_chunk_count"] = prev.metadata.get("merged_chunk_count", 1) + 1
            continue

        merged.append(chunk)

    return merged


def split_markdown_documents(documents: List[Document], config: ChunkingConfig | None = None) -> List[Document]:
    """统一切分入口：Markdown 语义切分 + token 切分。"""
    if not documents:
        return []

    cfg = config or ChunkingConfig()
    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=list(cfg.headers_to_split_on),
        strip_headers=False,
    )
    token_splitter = RecursiveCharacterTextSplitter(
        chunk_size=cfg.chunk_size,
        chunk_overlap=cfg.chunk_overlap,
        separators=["\n\n", "\n", "。", "！", "？", "；", "，", " "],
        length_function=cfg.length_function,
    )

    chunks: List[Document] = []

    for doc in documents:
        source_metadata = dict(doc.metadata or {})
        source_metadata["content_type"] = source_metadata.get("content_type", "markdown")

        text = _normalize_text(doc.page_content)
        if not text:
            continue

        # 第一阶段：按 Markdown 标题语义切。
        semantic_docs = header_splitter.split_text(text)
        if not semantic_docs:
            semantic_docs = [Document(page_content=text, metadata={})]

        for semantic_doc in semantic_docs:
            semantic_text = _normalize_text(semantic_doc.page_content)
            if _is_title_only_chunk(
                semantic_text,
                {**source_metadata, **(semantic_doc.metadata or {})},
                cfg,
            ):
                continue

            semantic_metadata = {
                **source_metadata,
                **(semantic_doc.metadata or {}),
            }
            semantic_metadata["title_path"] = _compose_title_path(semantic_metadata)
            semantic_text = _prepend_title_context(semantic_text, semantic_metadata)

            if cfg.length_function(semantic_text) <= cfg.chunk_size:
                chunks.append(Document(page_content=semantic_text, metadata=semantic_metadata))
                continue

            # 第二阶段：按 token 长度补切。
            fine_chunks = token_splitter.create_documents(
                texts=[semantic_text],
                metadatas=[semantic_metadata],
            )
            for fine_doc in fine_chunks:
                fine_doc.page_content = _normalize_text(fine_doc.page_content)
                fine_doc.metadata = fine_doc.metadata or {}
                fine_doc.metadata["title_path"] = _compose_title_path(fine_doc.metadata)
                fine_doc.page_content = _prepend_title_context(fine_doc.page_content, fine_doc.metadata)
                chunks.append(fine_doc)

    chunks = _merge_adjacent_small_chunks(chunks, cfg)

    # 为每个 source + title_path 重新编号 chunk_id，便于后续追踪。
    local_counter = {}
    for chunk in chunks:
        key = (chunk.metadata.get("source"), chunk.metadata.get("title_path"))
        local_counter[key] = local_counter.get(key, 0) + 1
        chunk.metadata["chunk_id"] = local_counter[key]

    return chunks


def split_loaded_documents(documents: List[Document], config: ChunkingConfig | None = None) -> List[Document]:
    """别名：语义同 `split_markdown_documents`。"""
    return split_markdown_documents(documents, config=config)
