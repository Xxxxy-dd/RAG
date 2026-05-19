from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

try:
    # Load .env from project root so alembic can read DATABASE_URL / MYSQL_* vars
    from dotenv import load_dotenv

    project_root = Path(__file__).resolve().parents[1]
    dotenv_path = project_root / ".env"
    if dotenv_path.exists():
        load_dotenv(dotenv_path=str(dotenv_path))
except Exception:
    # dotenv is optional; if not available, environment variables must be set externally
    pass

from alembic import context

# ensure project root is on path so we can import rag.storage
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    try:
        fileConfig(config.config_file_name)
    except Exception:
        # If alembic.ini does not define logging sections expected by fileConfig,
        # skip logging configuration to allow migrations to run in minimal envs.
        pass

# Try to import SQLAlchemy metadata from rag.storage.models to enable autogenerate
try:
    # Try the normal import first (may require project deps).
    from rag.storage.models import metadata as target_metadata  # type: ignore
except Exception:
    # Fallback: load the models.py file directly to avoid importing the whole package
    try:
        import importlib.util

        models_path = os.path.join(project_root, "rag", "storage", "models.py")
        spec = importlib.util.spec_from_file_location("rag_storage_models", models_path)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            target_metadata = getattr(mod, "metadata", None)
        else:
            target_metadata = None
    except Exception:
        target_metadata = None


def get_database_url() -> str:
    # Prefer explicit env var DATABASE_URL, fall back to MYSQL_* env vars
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    # try to build a mysql+pymysql URL if components are present
    host = os.getenv("MYSQL_HOST")
    user = os.getenv("MYSQL_USER")
    password = os.getenv("MYSQL_PASSWORD", "")
    database = os.getenv("MYSQL_DATABASE")
    port = os.getenv("MYSQL_PORT")
    if host and user and database:
        host_part = f":{port}" if port else ""
        return f"mysql+pymysql://{user}:{password}@{host}{host_part}/{database}"
    raise RuntimeError(
        "No database URL configured for alembic; set DATABASE_URL or MYSQL_* env vars"
    )


def run_migrations_offline() -> None:
    url = get_database_url()
    context.configure(url=url, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    from sqlalchemy import create_engine

    url = get_database_url()
    connectable = create_engine(url)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
