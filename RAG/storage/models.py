from __future__ import annotations

import sqlalchemy as sa

metadata = sa.MetaData()

conversations = sa.Table(
    "conversations",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("session_id", sa.String(128), nullable=False),
    sa.Column("user_id", sa.String(128), nullable=True),
    sa.Column("title", sa.String(255), nullable=True),
    sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), nullable=False),
    sa.UniqueConstraint("session_id", name="uq_conversations_session_id"),
    sa.Index("idx_conversations_updated_at", "updated_at"),
)

messages = sa.Table(
    "messages",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("conversation_id", sa.BigInteger, sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
    sa.Column("message_id", sa.String(64), nullable=False),
    sa.Column("trace_id", sa.String(64), nullable=True),
    sa.Column("idempotency_key", sa.String(191), nullable=True),
    sa.Column("role", sa.String(32), nullable=False),
    sa.Column("text", sa.Text, nullable=False),
    sa.Column("seq", sa.Integer, nullable=False),
    sa.Column("metadata", sa.Text, nullable=True),
    sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), nullable=False),
    sa.UniqueConstraint("message_id", name="uq_messages_message_id"),
    sa.UniqueConstraint("conversation_id", "seq", name="uq_messages_conversation_seq"),
    sa.Index("idx_messages_trace_id", "trace_id"),
    sa.Index("idx_messages_idempotency_key", "idempotency_key"),
    sa.Index("idx_messages_conversation_created", "conversation_id", "created_at"),
    sa.Index("idx_messages_role_created", "role", "created_at"),
)

documents = sa.Table(
    "documents",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("document_key", sa.String(191), nullable=False),
    sa.Column("trace_id", sa.String(64), nullable=True),
    sa.Column("idempotency_key", sa.String(191), nullable=True),
    sa.Column("source", sa.String(512), nullable=True),
    sa.Column("title_path", sa.String(1024), nullable=True),
    sa.Column("content", sa.Text, nullable=False),
    sa.Column("content_hash", sa.String(64), nullable=False),
    sa.Column("metadata", sa.Text, nullable=True),
    sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), nullable=False),
    sa.UniqueConstraint("document_key", name="uq_documents_document_key"),
    sa.UniqueConstraint("content_hash", name="uq_documents_content_hash"),
    sa.UniqueConstraint("idempotency_key", name="uq_documents_idempotency_key"),
    sa.Index("idx_documents_trace_id", "trace_id"),
    sa.Index("idx_documents_idempotency_key", "idempotency_key"),
    sa.Index("idx_documents_source", "source"),
    sa.Index("idx_documents_created_at", "created_at"),
)

embeddings = sa.Table(
    "embeddings",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("document_id", sa.BigInteger, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
    sa.Column("vector_id", sa.String(191), nullable=False),
    sa.Column("trace_id", sa.String(64), nullable=True),
    sa.Column("idempotency_key", sa.String(191), nullable=True),
    sa.Column("model", sa.String(191), nullable=False),
    sa.Column("dimension", sa.Integer, nullable=False),
    sa.Column("metadata", sa.Text, nullable=True),
    sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), nullable=False),
    sa.UniqueConstraint("vector_id", name="uq_embeddings_vector_id"),
    sa.UniqueConstraint("idempotency_key", name="uq_embeddings_idempotency_key"),
    sa.Index("idx_embeddings_trace_id", "trace_id"),
    sa.Index("idx_embeddings_idempotency_key", "idempotency_key"),
    sa.Index("idx_embeddings_document_id", "document_id"),
    sa.Index("idx_embeddings_model", "model"),
)

__all__ = ["metadata", "conversations", "messages", "documents", "embeddings"]
