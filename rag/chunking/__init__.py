
"""Chunking package.

统一提供 Markdown 文档切分能力。
"""

from .markdown_chunker import ChunkingConfig, split_loaded_documents, split_markdown_documents

__all__ = [
	"ChunkingConfig",
	"split_markdown_documents",
	"split_loaded_documents",
]
