"""索引管理统一入口。"""

import argparse
import logging
import sys

from pathlib import Path
from typing import Iterable, List, Tuple

from langchain_chroma import Chroma
from langchain_core.documents import Document

from ..chunking import ChunkingConfig
from ..embeddings import embeddings
from ..memory.redis_memory import append_index_chunk_event
from ..observability import get_trace_id
from ..pipeline import ingest_file, ingest_files
from ..storage import persist_index_chunks


DEFAULT_INDEX_BACKEND = "chroma"
DEFAULT_COLLECTION_NAME = "document_indexing"
DEFAULT_PERSIST_DIRECTORY = Path(__file__).resolve().parent / "chroma_db"


LOGGER = logging.getLogger(__name__)


def _normalize_backend(backend: str | None) -> str:
	backend_name = (backend or DEFAULT_INDEX_BACKEND).strip().lower()
	if backend_name != DEFAULT_INDEX_BACKEND:
		raise ValueError(f"不支持的索引后端: {backend}")
	return backend_name


def _resolve_persist_directory(persist_directory: str | Path | None) -> str:
	directory = Path(persist_directory) if persist_directory is not None else DEFAULT_PERSIST_DIRECTORY
	directory.mkdir(parents=True, exist_ok=True)
	return str(directory.resolve())


def build_index_from_chunks(
	chunks: Iterable[Document],
	collection_name: str = DEFAULT_COLLECTION_NAME,
	persist_directory: str | Path | None = None,
	backend: str | None = None,
) -> Chroma:
	"""基于分块构建索引。"""
	_normalize_backend(backend)
	chunk_list = list(chunks)
	if not chunk_list:
		raise ValueError("chunks 为空，无法构建索引")

	embedding_model = embeddings()
	resolved_persist_directory = _resolve_persist_directory(persist_directory)
	chunk_records = []
	try:
		chunk_records = persist_index_chunks(
			chunk_list,
			collection_name=collection_name,
			backend=DEFAULT_INDEX_BACKEND,
			persist_directory=resolved_persist_directory,
			embedding_model=getattr(embedding_model, "model", None),
		)
	except Exception as exc:
		LOGGER.warning("MySQL persistence skipped for index build: %s", exc)
	chunk_ids = [record["vector_id"] for record in chunk_records] if chunk_records else None
	vector_store = Chroma.from_documents(
		documents=chunk_list,
		embedding=embedding_model,
		ids=chunk_ids,
		collection_name=collection_name,
		persist_directory=resolved_persist_directory,
	)
	return vector_store



def enqueue_index_chunks(
	chunks: Iterable[Document],
	collection_name: str = DEFAULT_COLLECTION_NAME,
	persist_directory: str | Path | None = None,
	backend: str | None = None,
	embedding_model: str | None = None,
	trace_id: str | None = None,
) -> list[str]:
	"""把待建索引的 chunk 逐条投递到 Redis Stream，由 vector worker 异步 upsert。"""
	_normalize_backend(backend)
	resolved_persist_directory = _resolve_persist_directory(persist_directory)
	active_trace_id = (trace_id or get_trace_id() or "").strip() or None
	events: list[str] = []
	for chunk in chunks:
		chunk_metadata = dict(chunk.metadata or {})
		if active_trace_id and not chunk_metadata.get("trace_id"):
			chunk_metadata["trace_id"] = active_trace_id
		event_id = append_index_chunk_event(
			chunk_text=chunk.page_content,
			chunk_metadata=chunk_metadata,
			trace_id=active_trace_id,
			collection_name=collection_name,
			persist_directory=resolved_persist_directory,
			backend=DEFAULT_INDEX_BACKEND,
			embedding_model=embedding_model,
		)
		events.append(event_id)
	return events


def enqueue_index_from_file(
	path: str,
	chunking_config: ChunkingConfig | None = None,
	collection_name: str = DEFAULT_COLLECTION_NAME,
	persist_directory: str | Path | None = None,
	backend: str | None = None,
	embedding_model: str | None = None,
	trace_id: str | None = None,
) -> list[str]:
	"""从单文件摄入、切分并投递到 Redis Stream。"""
	_normalize_backend(backend)
	chunks = ingest_file(path, chunking_config=chunking_config)
	return enqueue_index_chunks(
		chunks=chunks,
		collection_name=collection_name,
		persist_directory=persist_directory,
		backend=backend,
		embedding_model=embedding_model,
		trace_id=trace_id,
	)


def enqueue_index_from_files(
	paths: Iterable[str],
	chunking_config: ChunkingConfig | None = None,
	collection_name: str = DEFAULT_COLLECTION_NAME,
	persist_directory: str | Path | None = None,
	continue_on_error: bool = True,
	backend: str | None = None,
	embedding_model: str | None = None,
	trace_id: str | None = None,
) -> tuple[list[str], list[Tuple[str, str]]]:
	"""从多文件摄入、切分并投递到 Redis Stream。"""
	_normalize_backend(backend)
	chunks, errors = ingest_files(
		paths=paths,
		chunking_config=chunking_config,
		continue_on_error=continue_on_error,
	)
	events = enqueue_index_chunks(
		chunks=chunks,
		collection_name=collection_name,
		persist_directory=persist_directory,
		backend=backend,
		embedding_model=embedding_model,
		trace_id=trace_id,
	)
	return events, errors


def build_index_from_file(
	path: str,
	chunking_config: ChunkingConfig | None = None,
	collection_name: str = DEFAULT_COLLECTION_NAME,
	persist_directory: str | Path | None = None,
	backend: str | None = None,
) -> Chroma:
	"""从单文件完成摄入、切分并构建索引。"""
	_normalize_backend(backend)
	chunks = ingest_file(path, chunking_config=chunking_config)
	return build_index_from_chunks(
		chunks=chunks,
		collection_name=collection_name,
		persist_directory=persist_directory,
	)


def build_index_from_files(
	paths: Iterable[str],
	chunking_config: ChunkingConfig | None = None,
	collection_name: str = DEFAULT_COLLECTION_NAME,
	persist_directory: str | Path | None = None,
	continue_on_error: bool = True,
	backend: str | None = None,
) -> Tuple[Chroma, List[Tuple[str, str]]]:
	"""从多文件完成摄入、切分并构建索引。"""
	_normalize_backend(backend)
	chunks, errors = ingest_files(
		paths=paths,
		chunking_config=chunking_config,
		continue_on_error=continue_on_error,
	)
	vector_store = build_index_from_chunks(
		chunks=chunks,
		collection_name=collection_name,
		persist_directory=persist_directory,
	)
	return vector_store, errors


def load_index(
	collection_name: str = DEFAULT_COLLECTION_NAME,
	persist_directory: str | Path | None = None,
	backend: str | None = None,
) -> Chroma:
	"""加载已存在的索引。"""
	_normalize_backend(backend)
	embedding_model = embeddings()
	return Chroma(
		collection_name=collection_name,
		persist_directory=_resolve_persist_directory(persist_directory),
		embedding_function=embedding_model,
	)


def available_backends() -> tuple[str, ...]:
	"""返回当前支持的索引后端列表。"""
	return (DEFAULT_INDEX_BACKEND,)


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description="统一索引入口：同步建索引或异步投递索引任务")
	parser.add_argument("paths", nargs="+", help="一个或多个待索引文件路径")
	parser.add_argument("--async-index", action="store_true", help="异步模式：仅投递到 Redis Stream")
	parser.add_argument("--collection-name", default=DEFAULT_COLLECTION_NAME, help="Chroma 集合名")
	parser.add_argument("--persist-directory", default=None, help="Chroma 持久化目录")
	parser.add_argument("--continue-on-error", action="store_true", help="多文件时遇错继续处理")
	parser.add_argument("--embedding-model", default=None, help="异步投递时写入事件元数据")
	args = parser.parse_args(argv)

	if args.async_index:
		if len(args.paths) == 1:
			events = enqueue_index_from_file(
				path=args.paths[0],
				collection_name=args.collection_name,
				persist_directory=args.persist_directory,
				embedding_model=args.embedding_model,
			)
			errors: list[Tuple[str, str]] = []
		else:
			events, errors = enqueue_index_from_files(
				paths=args.paths,
				collection_name=args.collection_name,
				persist_directory=args.persist_directory,
				continue_on_error=args.continue_on_error,
				embedding_model=args.embedding_model,
			)

		print(f"Enqueued chunks: {len(events)}")
		for index, event_id in enumerate(events, start=1):
			print(f"[{index}] event_id={event_id}")
		if errors:
			print(f"Ingest errors: {len(errors)}")
			for path, message in errors:
				print(f"- {path}: {message}")
			return 1
		return 0

	if len(args.paths) == 1:
		build_index_from_file(
			path=args.paths[0],
			collection_name=args.collection_name,
			persist_directory=args.persist_directory,
		)
		errors = []
	else:
		_, errors = build_index_from_files(
			paths=args.paths,
			collection_name=args.collection_name,
			persist_directory=args.persist_directory,
			continue_on_error=args.continue_on_error,
		)

	print("Index build completed.")
	if errors:
		print(f"Ingest errors: {len(errors)}")
		for path, message in errors:
			print(f"- {path}: {message}")
		return 1
	return 0


if __name__ == "__main__":
	raise SystemExit(main(sys.argv[1:]))


