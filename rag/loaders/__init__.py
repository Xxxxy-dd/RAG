"""Document loaders package.

当前 loader 统一职责：专属格式深度解析并输出 Markdown 化 Document 列表。
统一切分请使用 `rag.chunking.split_markdown_documents`。
"""

from .docx_loader import load_docx
from .html_loader import load_html
from .md_loader import load_markdown, load_md
from .pdf_loader import load_pdf
from .pptx_loader import load_pptx

__all__ = [
	"load_pdf",
	"load_pptx",
	"load_docx",
	"load_html",
	"load_md",
	"load_markdown",
]
