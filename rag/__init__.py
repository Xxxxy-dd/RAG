"""RAG package placeholder

This package contains placeholders for the RAG project structure.
Implementations intentionally left for the user to complete.
"""

try:
    from .pipeline import ingest_file, ingest_files
except Exception:
    # 支持直接运行单文件（例如: python rag/__init__.py）场景的回退导入：
    # 当作为脚本直接执行时，__package__ 可能为 None，导致相对导入失败。
    # 这里通过把项目根加入 sys.path，然后按包名导入来回退。
    import importlib
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    pkg = importlib.import_module("rag.pipeline")
    ingest_file = getattr(pkg, "ingest_file")
    ingest_files = getattr(pkg, "ingest_files")

__all__ = ["ingest_file", "ingest_files"]
