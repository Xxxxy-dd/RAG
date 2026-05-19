from __future__ import annotations

import sys
import types
from pathlib import Path
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT_STR = str(PROJECT_ROOT)

if PROJECT_ROOT_STR not in sys.path:
    sys.path.insert(0, PROJECT_ROOT_STR)

# Provide a lightweight rag.pipeline stub so importing rag.* in tests does not
# pull optional heavy dependencies (e.g. bs4) through rag.__init__.
if "rag.pipeline" not in sys.modules:
    pipeline_stub = types.ModuleType("rag.pipeline")
    pipeline_stub.ingest_file = lambda *args, **kwargs: []
    pipeline_stub.ingest_files = lambda *args, **kwargs: ([], [])
    sys.modules["rag.pipeline"] = pipeline_stub

# Provide a lightweight rag.embeddings stub so index-related imports do not
# require optional community packages during test collection.
if "rag.embeddings" not in sys.modules:
    class _DummyEmbeddings:
        model = "test-embedding-model"

        def embed_query(self, text: str):
            return [0.0, 0.0, 0.0]

    embeddings_stub = types.ModuleType("rag.embeddings")
    embeddings_stub.embeddings = lambda: _DummyEmbeddings()
    sys.modules["rag.embeddings"] = embeddings_stub

    # Use in-memory idempotency store for tests to avoid relying on a real Redis
    try:
        from rag.workers import reliability
        reliability.use_inmemory_store_for_tests()
    except Exception:
        pass


    @pytest.fixture(autouse=True)
    def _clear_idempotency_store_between_tests():
        """Ensure each test starts with a fresh in-memory idempotency state."""
        try:
            from rag.workers import reliability as _rel

            _rel.clear_inmemory_store()
        except Exception:
            pass
        yield
