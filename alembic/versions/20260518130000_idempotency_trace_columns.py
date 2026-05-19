"""add trace and idempotency columns

Revision ID: 20260518130000
Revises: 20260518064325
Create Date: 2026-05-18 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260518130000'
down_revision = '20260518064325'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('messages', sa.Column('trace_id', sa.String(length=64), nullable=True))
    op.add_column('messages', sa.Column('idempotency_key', sa.String(length=191), nullable=True))
    op.create_index('idx_messages_trace_id', 'messages', ['trace_id'], unique=False)
    op.create_index('idx_messages_idempotency_key', 'messages', ['idempotency_key'], unique=False)

    op.add_column('documents', sa.Column('trace_id', sa.String(length=64), nullable=True))
    op.add_column('documents', sa.Column('idempotency_key', sa.String(length=191), nullable=True))
    op.create_index('idx_documents_trace_id', 'documents', ['trace_id'], unique=False)
    op.create_index('idx_documents_idempotency_key', 'documents', ['idempotency_key'], unique=False)
    op.create_unique_constraint('uq_documents_idempotency_key', 'documents', ['idempotency_key'])

    op.add_column('embeddings', sa.Column('trace_id', sa.String(length=64), nullable=True))
    op.add_column('embeddings', sa.Column('idempotency_key', sa.String(length=191), nullable=True))
    op.create_index('idx_embeddings_trace_id', 'embeddings', ['trace_id'], unique=False)
    op.create_index('idx_embeddings_idempotency_key', 'embeddings', ['idempotency_key'], unique=False)
    op.create_unique_constraint('uq_embeddings_idempotency_key', 'embeddings', ['idempotency_key'])


def downgrade() -> None:
    op.drop_constraint('uq_embeddings_idempotency_key', 'embeddings', type_='unique')
    op.drop_index('idx_embeddings_idempotency_key', table_name='embeddings')
    op.drop_index('idx_embeddings_trace_id', table_name='embeddings')
    op.drop_column('embeddings', 'idempotency_key')
    op.drop_column('embeddings', 'trace_id')

    op.drop_constraint('uq_documents_idempotency_key', 'documents', type_='unique')
    op.drop_index('idx_documents_idempotency_key', table_name='documents')
    op.drop_index('idx_documents_trace_id', table_name='documents')
    op.drop_column('documents', 'idempotency_key')
    op.drop_column('documents', 'trace_id')

    op.drop_index('idx_messages_idempotency_key', table_name='messages')
    op.drop_index('idx_messages_trace_id', table_name='messages')
    op.drop_column('messages', 'idempotency_key')
    op.drop_column('messages', 'trace_id')
