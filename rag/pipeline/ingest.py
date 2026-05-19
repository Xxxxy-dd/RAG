"""统一的数据摄入编排。

流程：
1. 根据文件后缀选择对应格式的加载器。
2. 将源文件转换为类似 Markdown 的 Document（加载阶段）。
3. 应用统一的 Markdown 分块（分块阶段）。
4. 返回可直接用于向量化/索引的块数据。
"""

from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from langchain_core.documents import Document

# 使用包内相对导入，确保该模块在包内运行时可正常工作。
from ..chunking import ChunkingConfig, split_markdown_documents
from ..loaders import load_docx, load_html, load_markdown, load_pdf, load_pptx


LoaderFunc = callable


def _resolve_loader(path: str):
    """根据文件后缀返回对应的加载器函数。"""
    suffix = Path(path).suffix.lower()

    loader_map: Dict[str, object] = {
        ".pdf": load_pdf,
        ".pptx": load_pptx,
        ".docx": load_docx,
        ".html": load_html,
        ".htm": load_html,
        ".md": load_markdown,
        ".markdown": load_markdown,
    }

    loader = loader_map.get(suffix)
    if loader is None:
        raise ValueError(f"Unsupported file type: {suffix or 'no suffix'}")

    return loader


def ingest_file(path: str, chunking_config: ChunkingConfig | None = None) -> List[Document]:
    """摄入单个文件并返回最终分块。

    参数：
    - path: 源文件路径。
    - chunking_config: 可选，用于覆盖默认的统一 Markdown 分块配置。
    """
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    loader = _resolve_loader(path)
    markdown_docs = loader(str(file_path))

    if not markdown_docs:
        return []

    chunks = split_markdown_documents(markdown_docs, config=chunking_config)
    return chunks


def ingest_files(
    paths: Iterable[str],
    chunking_config: ChunkingConfig | None = None,
    continue_on_error: bool = True,
) -> Tuple[List[Document], List[Tuple[str, str]]]:
    """批量摄入多个文件。

    返回：
    - all_chunks: 所有文件分块合并后的扁平列表。
    - errors: 形如 (path, error_message) 的错误列表。
    """
    all_chunks: List[Document] = []
    errors: List[Tuple[str, str]] = []

    for path in paths:
        try:
            all_chunks.extend(ingest_file(path, chunking_config=chunking_config))
        except Exception as exc:
            if not continue_on_error:
                raise
            errors.append((path, str(exc)))

    return all_chunks, errors
