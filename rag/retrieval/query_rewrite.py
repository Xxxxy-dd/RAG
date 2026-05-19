from typing import Iterable

from ..models import ChatClient


def _format_history(history: Iterable[str] | None) -> str:
    if not history:
        return "无"
    return "\n".join(f"- {item}" for item in history)


def rewrite_query(
    query: str, history: Iterable[str] | None = None, client: ChatClient | None = None
) -> str:
    """将用户问题改写为更适合检索的查询语句。"""
    if not query or not query.strip():
        raise ValueError("query 不能为空")

    chat = client or ChatClient()

    prompt = (
        "请将用户问题改写为适合向量检索的简洁查询。\n"
        "要求:\n"
        "1. 保留核心实体、时间、数字与限定词；\n"
        "2. 删除寒暄与无关措辞；\n"
        "3. 如有上下文，消解代词指代；\n"
        "4. 仅输出改写后的单句查询，不要解释。\n\n"
        f"对话历史:\n{_format_history(history)}\n\n"
        f"用户问题:\n{query.strip()}"
    )

    rewritten = chat.complete(prompt=prompt, system_prompt="你是检索改写助手，只输出查询语句。")
    return rewritten.strip()
