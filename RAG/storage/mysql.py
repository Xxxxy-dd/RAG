from __future__ import annotations

import json
import logging
import os
import hashlib
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse
from pathlib import Path

from langchain_core.documents import Document

from dotenv import load_dotenv

from ..config import get_settings
from ..embeddings import embeddings as build_embeddings

try:
    import pymysql
    from pymysql.cursors import DictCursor
except Exception:  # pragma: no cover - optional dependency until installed
    pymysql = None
    DictCursor = None


LOGGER = logging.getLogger(__name__)


def _load_project_env() -> None:
    project_root = Path(__file__).resolve().parents[2]
    dotenv_path = project_root / ".env"
    load_dotenv(dotenv_path=dotenv_path)


_load_project_env()


@dataclass(frozen=True, slots=True)
class MySQLSettings:
    host: str
    port: int
    user: str
    password: str
    database: str
    charset: str = "utf8mb4"
    connect_timeout: int = 5
    use_unicode: bool = True


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


def _build_settings_from_url(database_url: str) -> MySQLSettings | None:
    parsed = urlparse(database_url)
    if parsed.scheme not in {"mysql", "mysql+pymysql"}:
        return None

    query = parse_qs(parsed.query)
    charset = query.get("charset", ["utf8mb4"])[0]
    port = parsed.port or 3306
    database = parsed.path.lstrip("/")
    if not parsed.hostname or not parsed.username or not database:
        return None

    return MySQLSettings(
        host=parsed.hostname,
        port=port,
        user=unquote(parsed.username),
        password=unquote(parsed.password or ""),
        database=database,
        charset=charset,
    )


def load_mysql_settings() -> MySQLSettings | None:
    database_url = _first_env("DATABASE_URL", "MYSQL_DATABASE_URL")
    if database_url:
        settings = _build_settings_from_url(database_url)
        if settings is not None:
            return settings

    host = _first_env("MYSQL_HOST")
    user = _first_env("MYSQL_USER")
    database = _first_env("MYSQL_DATABASE")
    if not host or not user or not database:
        return None

    port_raw = _first_env("MYSQL_PORT") or "3306"
    try:
        port = int(port_raw)
    except ValueError:
        port = 3306

    charset = _first_env("MYSQL_CHARSET") or "utf8mb4"
    password = os.getenv("MYSQL_PASSWORD", "")
    connect_timeout_raw = _first_env("MYSQL_CONNECT_TIMEOUT") or "5"
    try:
        connect_timeout = int(connect_timeout_raw)
    except ValueError:
        connect_timeout = 5

    return MySQLSettings(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        charset=charset,
        connect_timeout=connect_timeout,
    )


def resolve_embedding_model_name(embedding_model: str | None = None) -> str:
    if embedding_model and embedding_model.strip():
        return embedding_model.strip()
    env_model = _first_env("EMBEDDINGS_MODEL")
    if env_model:
        return env_model
    try:
        return get_settings().embeddings_model
    except Exception:
        return "unknown"


@lru_cache(maxsize=8)
def resolve_embedding_dimension(embedding_model: str | None = None) -> int:
    """Return the embedding vector size for the active model.

    The value is cached because dimension is fixed for a given model.
    """
    try:
        embedding_client = build_embeddings()
        vector = embedding_client.embed_query("embedding-dimension-probe")
        return len(vector)
    except Exception:
        LOGGER.warning(
            "Failed to resolve embedding dimension for model=%s",
            resolve_embedding_model_name(embedding_model),
            exc_info=True,
        )
        return 0


SCHEMA_STATEMENTS = (
    """
CREATE TABLE IF NOT EXISTS conversations (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
	session_id VARCHAR(128) NOT NULL,
	user_id VARCHAR(128) NULL,
	title VARCHAR(255) NULL,
	created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
	updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
	UNIQUE KEY uq_conversations_session_id (session_id),
	KEY idx_conversations_updated_at (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
""",
    """
CREATE TABLE IF NOT EXISTS messages (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
	conversation_id BIGINT UNSIGNED NOT NULL,
	message_id VARCHAR(64) NOT NULL,
	trace_id VARCHAR(64) NULL,
	idempotency_key VARCHAR(191) NULL,
	role VARCHAR(32) NOT NULL,
	text LONGTEXT NOT NULL,
	seq INT NOT NULL,
	metadata LONGTEXT NULL,
	created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
	updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
	UNIQUE KEY uq_messages_message_id (message_id),
	UNIQUE KEY uq_messages_conversation_seq (conversation_id, seq),
	KEY idx_messages_trace_id (trace_id),
	KEY idx_messages_idempotency_key (idempotency_key),
	KEY idx_messages_conversation_created (conversation_id, created_at),
	KEY idx_messages_role_created (role, created_at),
	CONSTRAINT fk_messages_conversation FOREIGN KEY (conversation_id)
		REFERENCES conversations(id)
		ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
""",
    """
CREATE TABLE IF NOT EXISTS documents (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
	document_key VARCHAR(191) NOT NULL,
	trace_id VARCHAR(64) NULL,
	idempotency_key VARCHAR(191) NULL,
	source VARCHAR(512) NULL,
	title_path VARCHAR(1024) NULL,
	content LONGTEXT NOT NULL,
	content_hash CHAR(64) NOT NULL,
	metadata LONGTEXT NULL,
	created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
	updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
	UNIQUE KEY uq_documents_document_key (document_key),
	UNIQUE KEY uq_documents_content_hash (content_hash),
	UNIQUE KEY uq_documents_idempotency_key (idempotency_key),
	KEY idx_documents_trace_id (trace_id),
	KEY idx_documents_idempotency_key (idempotency_key),
	KEY idx_documents_source (source),
	KEY idx_documents_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
""",
    """
CREATE TABLE IF NOT EXISTS embeddings (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
	document_id BIGINT UNSIGNED NOT NULL,
	vector_id VARCHAR(191) NOT NULL,
	trace_id VARCHAR(64) NULL,
	idempotency_key VARCHAR(191) NULL,
	model VARCHAR(191) NOT NULL,
	dimension INT NOT NULL,
	metadata LONGTEXT NULL,
	created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
	updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
	UNIQUE KEY uq_embeddings_vector_id (vector_id),
	UNIQUE KEY uq_embeddings_idempotency_key (idempotency_key),
	KEY idx_embeddings_trace_id (trace_id),
	KEY idx_embeddings_idempotency_key (idempotency_key),
	KEY idx_embeddings_document_id (document_id),
	KEY idx_embeddings_model (model),
	CONSTRAINT fk_embeddings_document FOREIGN KEY (document_id)
		REFERENCES documents(id)
		ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
""",
)


def _require_driver() -> None:
    if pymysql is None or DictCursor is None:
        raise RuntimeError(
            "pymysql package is not installed; install requirements before using MySQL persistence"
        )


@dataclass(slots=True)
class MySQLStore:
    settings: MySQLSettings

    @contextmanager
    def connection(self):
        _require_driver()
        conn = pymysql.connect(
            host=self.settings.host,
            port=self.settings.port,
            user=self.settings.user,
            password=self.settings.password,
            db=self.settings.database,
            charset=self.settings.charset,
            connect_timeout=self.settings.connect_timeout,
            autocommit=False,
            cursorclass=DictCursor,
        )
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def ensure_schema(self) -> None:
        # Prefer using SQLAlchemy metadata when available so migrations and
        # programmatic schema creation stay consistent. Fall back to the raw
        # SCHEMA_STATEMENTS for minimal development environments.
        try:
            from rag.storage.models import metadata as sa_metadata
        except Exception:
            sa_metadata = None

        if sa_metadata is not None:
            with self.connection() as conn:
                # SQLAlchemy expects an Engine/Connection; we can pass the raw DBAPI connection
                # by creating an engine bound to the same DSN. Simpler: use metadata.create_all
                # on a SQLAlchemy engine created from current settings.
                from sqlalchemy import create_engine

                engine = create_engine(
                    f"mysql+pymysql://{self.settings.user}:{self.settings.password}@{self.settings.host}:{self.settings.port}/{self.settings.database}?charset={self.settings.charset}"
                )
                sa_metadata.create_all(bind=engine)
                return

        # Fallback: execute raw SQL statements
        with self.connection() as conn:
            with conn.cursor() as cursor:
                for statement in SCHEMA_STATEMENTS:
                    cursor.execute(statement)

    def ensure_conversation(
        self, session_id: str, user_id: str | None = None, title: str | None = None
    ) -> int:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
					INSERT INTO conversations (session_id, user_id, title)
					VALUES (%s, %s, %s)
					ON DUPLICATE KEY UPDATE
						user_id = COALESCE(VALUES(user_id), user_id),
						title = COALESCE(VALUES(title), title),
						updated_at = CURRENT_TIMESTAMP
					""",
                    (session_id, user_id, title),
                )
                cursor.execute("SELECT id FROM conversations WHERE session_id = %s", (session_id,))
                row = cursor.fetchone()
                if not row:
                    raise RuntimeError(f"Failed to load conversation for session_id={session_id}")
                return int(row["id"])

    def _next_sequence(self, cursor, conversation_id: int) -> int:
        cursor.execute(
            "SELECT COALESCE(MAX(seq), 0) AS max_seq FROM messages WHERE conversation_id = %s",
            (conversation_id,),
        )
        row = cursor.fetchone() or {"max_seq": 0}
        return int(row["max_seq"] or 0) + 1

    def append_message(
        self,
        session_id: str,
        role: str,
        text: str,
        *,
        user_id: str | None = None,
        title: str | None = None,
        message_id: str | None = None,
        trace_id: str | None = None,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            conversation_id = self.ensure_conversation(
                session_id=session_id, user_id=user_id, title=title
            )
            message_id = message_id or uuid.uuid4().hex
            metadata_text = (
                json.dumps(metadata, ensure_ascii=False) if metadata is not None else None
            )

            with self.connection() as conn:
                with conn.cursor() as cursor:
                    seq = self._next_sequence(cursor, conversation_id)
                    cursor.execute(
                        """
						INSERT INTO messages (conversation_id, message_id, trace_id, idempotency_key, role, text, seq, metadata)
						VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
						ON DUPLICATE KEY UPDATE
							text = VALUES(text),
							trace_id = VALUES(trace_id),
							idempotency_key = VALUES(idempotency_key),
							role = VALUES(role),
							metadata = VALUES(metadata),
							updated_at = CURRENT_TIMESTAMP
						""",
                        (
                            conversation_id,
                            message_id,
                            trace_id,
                            idempotency_key,
                            role,
                            text,
                            seq,
                            metadata_text,
                        ),
                    )
                    cursor.execute(
                        "SELECT id, conversation_id, message_id, trace_id, idempotency_key, role, text, seq, metadata, created_at, updated_at FROM messages WHERE message_id = %s",
                        (message_id,),
                    )
                    row = cursor.fetchone()
                    if not row:
                        raise RuntimeError(f"Failed to persist message {message_id}")
                    return row
        except Exception:
            LOGGER.exception(
                "MySQL append_message failed: session_id=%s role=%s message_id=%s",
                session_id,
                role,
                message_id,
            )
            raise

    def record_chat_turn(
        self,
        session_id: str,
        user_text: str,
        assistant_text: str,
        *,
        user_id: str | None = None,
        conversation_title: str | None = None,
        user_message_id: str | None = None,
        assistant_message_id: str | None = None,
        trace_id: str | None = None,
        idempotency_key: str | None = None,
        user_metadata: dict[str, Any] | None = None,
        assistant_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            conversation_id = self.ensure_conversation(
                session_id=session_id, user_id=user_id, title=conversation_title
            )
            user_message = self.append_message(
                session_id=session_id,
                role="user",
                text=user_text,
                user_id=user_id,
                title=conversation_title,
                message_id=user_message_id,
                trace_id=trace_id,
                idempotency_key=idempotency_key,
                metadata=user_metadata,
            )
            assistant_message = self.append_message(
                session_id=session_id,
                role="assistant",
                text=assistant_text,
                user_id=user_id,
                title=conversation_title,
                message_id=assistant_message_id,
                trace_id=trace_id,
                idempotency_key=idempotency_key,
                metadata=assistant_metadata,
            )
            return {
                "conversation_id": conversation_id,
                "user_message": user_message,
                "assistant_message": assistant_message,
            }
        except Exception:
            LOGGER.exception("MySQL record_chat_turn failed: session_id=%s", session_id)
            raise

    def list_messages(self, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT id FROM conversations WHERE session_id = %s", (session_id,))
                conversation = cursor.fetchone()
                if not conversation:
                    return []
                cursor.execute(
                    """
					SELECT message_id, role, text, seq, metadata, created_at
					FROM messages
					WHERE conversation_id = %s
					ORDER BY seq ASC
					LIMIT %s
					""",
                    (int(conversation["id"]), int(limit)),
                )
                return list(cursor.fetchall() or [])

    def save_document(
        self,
        document_key: str,
        content: str,
        *,
        source: str | None = None,
        title_path: str | None = None,
        trace_id: str | None = None,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            metadata_text = (
                json.dumps(metadata, ensure_ascii=False) if metadata is not None else None
            )
            content_hash = __import__("hashlib").sha256(content.encode("utf-8")).hexdigest()
            with self.connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
						INSERT INTO documents (document_key, trace_id, idempotency_key, source, title_path, content, content_hash, metadata)
						VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
						ON DUPLICATE KEY UPDATE
							source = VALUES(source),
							title_path = VALUES(title_path),
							trace_id = VALUES(trace_id),
							idempotency_key = VALUES(idempotency_key),
							content = VALUES(content),
							content_hash = VALUES(content_hash),
							metadata = VALUES(metadata),
							updated_at = CURRENT_TIMESTAMP
						""",
                        (
                            document_key,
                            trace_id,
                            idempotency_key,
                            source,
                            title_path,
                            content,
                            content_hash,
                            metadata_text,
                        ),
                    )
                    cursor.execute(
                        "SELECT id, document_key, trace_id, idempotency_key, source, title_path, content, content_hash, metadata, created_at, updated_at FROM documents WHERE document_key = %s",
                        (document_key,),
                    )
                    row = cursor.fetchone()
                    if not row:
                        raise RuntimeError(f"Failed to persist document {document_key}")
                    return row
        except Exception:
            LOGGER.exception("MySQL save_document failed: document_key=%s", document_key)
            raise

    def save_embedding(
        self,
        document_id: int,
        vector_id: str,
        model: str | None = None,
        dimension: int | None = None,
        *,
        trace_id: str | None = None,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            metadata_text = (
                json.dumps(metadata, ensure_ascii=False) if metadata is not None else None
            )
            resolved_model = resolve_embedding_model_name(model)
            resolved_dimension = (
                dimension if dimension is not None else resolve_embedding_dimension(model)
            )
            with self.connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
						INSERT INTO embeddings (document_id, vector_id, trace_id, idempotency_key, model, dimension, metadata)
						VALUES (%s, %s, %s, %s, %s, %s, %s)
						ON DUPLICATE KEY UPDATE
							model = VALUES(model),
							dimension = VALUES(dimension),
							trace_id = VALUES(trace_id),
							idempotency_key = VALUES(idempotency_key),
							metadata = VALUES(metadata),
							updated_at = CURRENT_TIMESTAMP
						""",
                        (
                            document_id,
                            vector_id,
                            trace_id,
                            idempotency_key,
                            resolved_model,
                            resolved_dimension,
                            metadata_text,
                        ),
                    )
                    cursor.execute(
                        "SELECT id, document_id, vector_id, trace_id, idempotency_key, model, dimension, metadata, created_at, updated_at FROM embeddings WHERE vector_id = %s",
                        (vector_id,),
                    )
                    row = cursor.fetchone()
                    if not row:
                        raise RuntimeError(f"Failed to persist embedding {vector_id}")
                    return row
        except Exception:
            LOGGER.exception(
                "MySQL save_embedding failed: vector_id=%s document_id=%s", vector_id, document_id
            )
            raise


@lru_cache(maxsize=1)
def get_mysql_store() -> MySQLStore | None:
    settings = load_mysql_settings()
    if settings is None:
        return None
    if pymysql is None or DictCursor is None:
        LOGGER.warning(
            "MySQL settings are configured, but pymysql is not installed; skipping persistence"
        )
        return None

    store = MySQLStore(settings)
    # Schema management is handled by Alembic migrations. The application
    # MUST NOT auto-create or modify database schema at startup in production.
    # If you need to create schema locally for development, use the
    # scripts/ensure_schema.py helper which calls store.ensure_schema().
    return store


def record_chat_turn(
    session_id: str,
    user_text: str,
    assistant_text: str,
    *,
    user_id: str | None = None,
    conversation_title: str | None = None,
    user_message_id: str | None = None,
    assistant_message_id: str | None = None,
    trace_id: str | None = None,
    idempotency_key: str | None = None,
    user_metadata: dict[str, Any] | None = None,
    assistant_metadata: dict[str, Any] | None = None,
) -> bool:
    store = get_mysql_store()
    if store is None:
        LOGGER.warning("MySQL store unavailable, skip record_chat_turn: session_id=%s", session_id)
        return False
    store.record_chat_turn(
        session_id=session_id,
        user_text=user_text,
        assistant_text=assistant_text,
        user_id=user_id,
        conversation_title=conversation_title,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
        trace_id=trace_id,
        idempotency_key=idempotency_key,
        user_metadata=user_metadata,
        assistant_metadata=assistant_metadata,
    )
    return True


def list_session_messages(session_id: str, limit: int = 50) -> list[dict[str, Any]]:
    store = get_mysql_store()
    if store is None:
        return []
    return store.list_messages(session_id=session_id, limit=limit)


def _normalize_key_part(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return "unknown"
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in text)


def make_document_key(chunk: Document, collection_name: str) -> str:
    metadata = dict(chunk.metadata or {})
    source = _normalize_key_part(metadata.get("source"))
    title_path = _normalize_key_part(metadata.get("title_path"))
    section_id = _normalize_key_part(metadata.get("section_id"))
    chunk_id = _normalize_key_part(metadata.get("chunk_id"))
    content_hash = hashlib.sha256(chunk.page_content.encode("utf-8")).hexdigest()[:16]
    raw_key = f"{collection_name}|{source}|{title_path}|{section_id}|{chunk_id}|{content_hash}"
    return f"doc_{hashlib.sha256(raw_key.encode('utf-8')).hexdigest()}"


def make_vector_id(document_key: str) -> str:
    return f"vec_{hashlib.sha256(document_key.encode('utf-8')).hexdigest()}"


def persist_index_chunks(
    chunks: list[Document],
    *,
    collection_name: str,
    backend: str = "chroma",
    persist_directory: str | None = None,
    embedding_model: str | None = None,
) -> list[dict[str, Any]]:
    """把索引 chunk 镜像写入 MySQL，便于长期审计和向量元数据追踪。"""
    store = get_mysql_store()
    if store is None or not chunks:
        return []

    results: list[dict[str, Any]] = []
    for chunk in chunks:
        metadata = dict(chunk.metadata or {})
        document_key = make_document_key(chunk, collection_name)
        vector_id = make_vector_id(document_key)
        payload_metadata = {
            **metadata,
            "collection_name": collection_name,
            "backend": backend,
            "document_key": document_key,
            "vector_id": vector_id,
        }
        if persist_directory:
            payload_metadata["persist_directory"] = persist_directory

        document_row = store.save_document(
            document_key=document_key,
            content=chunk.page_content,
            source=str(metadata.get("source")) if metadata.get("source") is not None else None,
            title_path=str(metadata.get("title_path"))
            if metadata.get("title_path") is not None
            else None,
            trace_id=str(metadata.get("trace_id"))
            if metadata.get("trace_id") is not None
            else None,
            idempotency_key=str(metadata.get("idempotency_key"))
            if metadata.get("idempotency_key") is not None
            else None,
            metadata=payload_metadata,
        )
        embedding_row = store.save_embedding(
            document_id=int(document_row["id"]),
            vector_id=vector_id,
            model=resolve_embedding_model_name(embedding_model),
            dimension=resolve_embedding_dimension(embedding_model),
            trace_id=str(metadata.get("trace_id"))
            if metadata.get("trace_id") is not None
            else None,
            idempotency_key=str(metadata.get("idempotency_key"))
            if metadata.get("idempotency_key") is not None
            else None,
            metadata={
                "collection_name": collection_name,
                "backend": backend,
                "document_key": document_key,
                "persist_directory": persist_directory,
            },
        )
        results.append(
            {
                "document_key": document_key,
                "vector_id": vector_id,
                "document_id": int(document_row["id"]),
                "embedding_id": int(embedding_row["id"]),
            }
        )

    return results
