"""pipeline 包的兼容入口，已转发到 index_manager。"""

from pathlib import Path
import sys


def _ensure_project_root_on_path():
    if __package__ in (None, ""):
        project_root = Path(__file__).resolve().parents[2]
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    _ensure_project_root_on_path()
    from rag.indexes.index_manager import main as index_main

    print("[Deprecated] python -m rag.pipeline 已转发到 python -m rag.indexes.index_manager")
    return index_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
