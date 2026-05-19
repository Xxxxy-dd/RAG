"""数据摄入编排包。"""

from pathlib import Path
import sys


if __package__ in (None, ""):
	# 当该文件被直接执行时，Python 无法识别父包。
	# 将项目根目录加入 sys.path，确保绝对包导入可用。
	project_root = Path(__file__).resolve().parents[2]
	if str(project_root) not in sys.path:
		sys.path.insert(0, str(project_root))
	from rag.pipeline.ingest import ingest_file, ingest_files
else:
	from .ingest import ingest_file, ingest_files


__all__ = ["ingest_file", "ingest_files"]


def _ensure_project_root_on_path():
	if __package__ in (None, ""):
		project_root = Path(__file__).resolve().parents[2]
		if str(project_root) not in sys.path:
			sys.path.insert(0, str(project_root))


def _print_summary(chunks):
	print(f"Total chunks: {len(chunks)}")
	for i, c in enumerate(chunks, start=1):
		content = getattr(c, "page_content", "")
		meta = getattr(c, "metadata", {}) or {}
		preview = content.replace("\n", " ")[:200]
		print(
			f"[{i}/{len(chunks)}] len={len(content):>5} chars, "
			f"type={meta.get('content_type')}, page={meta.get('page_number')}, title={meta.get('page_title')}"
		)
		print(f"  preview: {preview}\n")


def main(argv=None):
	"""针对示例文件或传入路径运行一个简要的分块摘要演示。"""
	if argv is None:
		argv = sys.argv[1:]

	_ensure_project_root_on_path()

	from rag.pipeline import ingest_file

	if argv:
		path = argv[0]
	else:
		path = str(Path(__file__).resolve().parents[2] / "data" / "samples" / "基于CNN的论坛验证码识别实验.pptx")

	chunks_all = ingest_file(path)
	chunks = _print_summary(chunks_all)
	return chunks



if __name__ == "__main__":
	main()


