"""Developer helper: create DB schema by invoking MySQLStore.ensure_schema()

This script is intended for local development only. Do NOT run in production.
"""
from rag.storage.mysql import get_mysql_store

store = get_mysql_store()
if store is None:
    print("MySQL store not available (check DATABASE_URL or MYSQL_* env vars and install pymysql).")
else:
    print("Ensuring schema...")
    try:
        store.ensure_schema()
        print("Schema ensured successfully.")
    except Exception as exc:
        print("Failed to ensure schema:", exc)
        raise
