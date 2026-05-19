"""initial

Revision ID: 0001_initial
Revises: 
Create Date: 2026-05-18 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create all tables defined in rag.storage.models.metadata

    This initial migration uses the SQLAlchemy MetaData exported from
    `rag.storage.models` so future autogenerate diffs will be possible.
    """
    try:
        # Try normal import first; env.py also supports loading by path
        from rag.storage.models import metadata as target_metadata
    except Exception:
        # If import fails (missing optional deps), attempt to load the file directly
        import importlib.util, os

        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        models_path = os.path.join(project_root, 'rag', 'storage', 'models.py')
        spec = importlib.util.spec_from_file_location('rag_storage_models', models_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[arg-type]
        target_metadata = getattr(mod, 'metadata', None)

    if target_metadata is None:
        raise RuntimeError('Could not load target_metadata for initial migration')

    bind = op.get_bind()
    target_metadata.create_all(bind=bind)


def downgrade() -> None:
    try:
        from rag.storage.models import metadata as target_metadata
    except Exception:
        import importlib.util, os

        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        models_path = os.path.join(project_root, 'rag', 'storage', 'models.py')
        spec = importlib.util.spec_from_file_location('rag_storage_models', models_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[arg-type]
        target_metadata = getattr(mod, 'metadata', None)

    if target_metadata is None:
        raise RuntimeError('Could not load target_metadata for downgrade')

    bind = op.get_bind()
    target_metadata.drop_all(bind=bind)
