from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path

from dotenv import load_dotenv


def _load_dotenv() -> None:
    """按项目根路径加载 .env，避免依赖当前工作目录。"""
    project_root = Path(__file__).resolve().parents[1]
    dotenv_path = project_root / ".env"
    load_dotenv(dotenv_path=dotenv_path)


@dataclass(frozen=True)
class Settings:
    llm_api_key: str | None
    llm_base_url: str
    llm_model: str
    llm_timeout: int
    embeddings_api_key: str | None
    embeddings_model: str
    rerank_mode: str
    rerank_model: str
    rerank_api_key: str | None
    rerank_base_url: str
    rerank_timeout: int
    rerank_model_path: str | None
    chunk_title_only_max_chars: int
    chunk_title_only_allow_punctuation: bool


def _int_from_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"环境变量 {name} 必须是整数，当前值: {raw}") from exc


def _bool_from_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default

    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"环境变量 {name} 必须是布尔值，当前值: {raw}")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    _load_dotenv()
    return Settings(
        llm_api_key=os.getenv("LLM_API_KEY"),
        llm_base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1"),
        llm_model=os.getenv("LLM_MODEL", "deepseek-chat"),
        llm_timeout=_int_from_env("LLM_TIMEOUT", 60),
        embeddings_api_key=os.getenv("EMBEDDINGS_API_KEY"),
        embeddings_model=os.getenv("EMBEDDINGS_MODEL", "text-embedding-v1"),
        rerank_mode=os.getenv("RERANK_MODE", "local").strip().lower(),
        rerank_model=os.getenv("RERANK_MODEL", "BAAI/bge-reranker-base"),
        rerank_api_key=os.getenv("RERANK_API_KEY"),
        rerank_base_url=os.getenv("RERANK_BASE_URL", "https://api.openai.com/v1"),
        rerank_timeout=_int_from_env("RERANK_TIMEOUT", 60),
        rerank_model_path=os.getenv("RERANK_MODEL_PATH"),
        chunk_title_only_max_chars=_int_from_env("CHUNK_TITLE_ONLY_MAX_CHARS", 6),
        chunk_title_only_allow_punctuation=_bool_from_env("CHUNK_TITLE_ONLY_ALLOW_PUNCTUATION", False),
    )
