from __future__ import annotations

import argparse
import sys
from pathlib import Path
from textwrap import shorten

from langchain_core.documents import Document

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT_STR = str(PROJECT_ROOT)
if PROJECT_ROOT_STR not in sys.path:
    sys.path.insert(0, PROJECT_ROOT_STR)

from rag.indexes import DEFAULT_COLLECTION_NAME, DEFAULT_PERSIST_DIRECTORY
from rag.retrieval import (
    rerank_documents,
    retrieve_documents,
    retrieve_documents_with_scores,
    rewrite_query,
)


def _preview_text(text: str, width: int = 180) -> str:
    return shorten(text.replace("\n", " ").strip(), width=width, placeholder="...")


def _print_documents(title: str, documents) -> None:
    print(f"\n== {title} ==")
    if not documents:
        print("无结果")
        return

    for index, document in enumerate(documents, start=1):
        metadata = dict(getattr(document, "metadata", {}) or {})
        print(f"[{index}] {_preview_text(document.page_content)}")
        if metadata:
            print(f"    metadata: {metadata}")


def _mock_rerank(documents, top_n: int):
    mocked_documents = []
    for rank, document in enumerate(documents[:top_n], start=1):
        metadata = dict(document.document.metadata or {})
        metadata["rerank_rank"] = rank
        metadata["rerank_score"] = float(len(documents) - rank + 1)
        mocked_documents.append(
            Document(page_content=document.document.page_content, metadata=metadata)
        )
    return mocked_documents


def main() -> int:
    parser = argparse.ArgumentParser(description="输入一个问题，逐步查看 retrieval 的各个流程结果")
    parser.add_argument("question", help="要检索的问题")
    parser.add_argument("--top-k", type=int, default=3, help="检索返回条数")
    parser.add_argument("--rerank-top-n", type=int, default=3, help="重排返回条数")
    parser.add_argument("--collection-name", default=DEFAULT_COLLECTION_NAME, help="Chroma 集合名")
    parser.add_argument(
        "--persist-directory",
        default=str(DEFAULT_PERSIST_DIRECTORY),
        help="Chroma 持久化目录",
    )
    args = parser.parse_args()

    print(f"原始问题: {args.question}")
    print(f"collection_name: {args.collection_name}")
    print(f"persist_directory: {args.persist_directory}")

    try:
        rewritten_question = rewrite_query(args.question)
        print(f"\n== 改写结果 ==\n{rewritten_question}")
        search_query = rewritten_question
    except Exception as exc:
        print(f"\n== 改写结果 ==\n失败: {exc}")
        search_query = args.question.strip()

    try:
        documents = retrieve_documents(
            query=search_query,
            top_k=args.top_k,
            collection_name=args.collection_name,
            persist_directory=args.persist_directory,
        )
        _print_documents(f"检索结果（query={search_query}）", documents)
    except Exception as exc:
        print(f"\n== 检索结果 ==\n失败: {exc}")
        documents = []

    try:
        documents_with_scores = retrieve_documents_with_scores(
            query=search_query,
            top_k=args.top_k,
            collection_name=args.collection_name,
            persist_directory=args.persist_directory,
        )
        print(f"\n== 带分数检索结果（query={search_query}） ==")
        if not documents_with_scores:
            print("无结果")
        else:
            for index, item in enumerate(documents_with_scores, start=1):
                print(f"[{index}] score={item.score} rank={item.rank}")
                print(f"    {_preview_text(item.document.page_content)}")
                if item.document.metadata:
                    print(f"    metadata: {dict(item.document.metadata)}")
    except Exception as exc:
        print(f"\n== 带分数检索结果 ==\n失败: {exc}")
        documents_with_scores = []

    if documents_with_scores:
        try:
            reranked_documents = rerank_documents(
                query=search_query,
                documents=documents_with_scores,
                top_n=args.rerank_top_n,
            )
            _print_documents(f"重排结果（top_n={args.rerank_top_n}）", reranked_documents)
        except Exception as exc:
            print(f"\n== 重排结果 ==\n远端重排失败: {exc}")
            print("使用本地 mock 结果继续展示")
            mocked_documents = _mock_rerank(documents_with_scores, args.rerank_top_n)
            _print_documents(f"重排结果（mock top_n={args.rerank_top_n}）", mocked_documents)
    else:
        print("\n== 重排结果 ==\n无可重排文档")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
