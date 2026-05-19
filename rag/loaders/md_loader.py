"""Markdown loader.

该 loader 负责读取原生 Markdown 文件，按标题层级组织内容，
并输出为统一的 `Document` 列表，供后续 chunking 模块统一切分。
"""

from pathlib import Path
import re
from typing import List, Tuple

from langchain_core.documents import Document


_ATX_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")


def _normalize_text(text: str) -> str:
    """整理空白字符，保持 Markdown 结构的同时减少噪声空行。"""
    if not text:
        return ""

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_title(markdown_text: str, fallback_name: str) -> str:
    """优先取首个一级标题作为文档标题，否则回退到文件名。"""
    for line in markdown_text.splitlines():
        matched = _ATX_HEADING_RE.match(line.strip())
        if matched and len(matched.group(1)) == 1:
            title = _normalize_text(matched.group(2))
            if title:
                return title

    return fallback_name


def _build_section_docs(path: str, markdown_text: str, doc_title: str) -> List[Document]:
    """按 Markdown 标题拆分为 section 文档（不做 chunking）。"""
    lines = markdown_text.splitlines()
    title_stack: List[Tuple[int, str]] = []
    buffer: List[str] = []
    section_docs: List[Document] = []
    section_id = 0

    def flush_buffer() -> None:
        nonlocal section_id
        content = _normalize_text("\n".join(buffer))
        if not content:
            return

        section_id += 1
        title_path = " > ".join(title for _, title in title_stack) if title_stack else doc_title
        metadata = {
            "source": path,
            "format": "markdown",
            "document_title": doc_title,
            "content_type": "markdown",
            "section_id": section_id,
            "title_path": title_path,
        }
        for level, heading in title_stack:
            metadata[f"h{level}"] = heading

        section_docs.append(Document(page_content=content, metadata=metadata))

    for raw_line in lines:
        line = raw_line.rstrip()
        matched = _ATX_HEADING_RE.match(line.strip())
        if matched:
            flush_buffer()
            buffer.clear()

            level = len(matched.group(1))
            heading_text = _normalize_text(matched.group(2))
            title_stack[:] = [(lv, t) for lv, t in title_stack if lv < level]
            title_stack.append((level, heading_text))

            buffer.append(line)
            continue

        buffer.append(line)

    flush_buffer()

    if section_docs:
        return section_docs

    # 无标题文档兜底：整份作为一个 markdown document
    content = _normalize_text(markdown_text)
    if not content:
        return []

    return [
        Document(
            page_content=content,
            metadata={
                "source": path,
                "format": "markdown",
                "document_title": doc_title,
                "content_type": "markdown",
                "section_id": 1,
                "title_path": doc_title,
            },
        )
    ]


def load_md(path: str) -> List[Document]:
    """读取 Markdown 文件并输出统一 Document 列表（不做 chunking）。"""
    file_path = Path(path)
    if not file_path.exists():
        return []

    markdown_text = file_path.read_text(encoding="utf-8", errors="ignore")
    markdown_text = _normalize_text(markdown_text)
    if not markdown_text:
        return []

    doc_title = _extract_title(markdown_text, file_path.stem)
    return _build_section_docs(path, markdown_text, doc_title)


def load_markdown(path: str) -> List[Document]:
    """`load_md` 的别名，便于统一调用命名。"""
    return load_md(path)
