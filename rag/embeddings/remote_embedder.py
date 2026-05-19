from langchain_community.embeddings import DashScopeEmbeddings
from ..config import get_settings


def remote_embedder_model():
    settings = get_settings()
    if not settings.embeddings_api_key:
        raise RuntimeError("环境变量 EMBEDDINGS_API_KEY 未读到")
    embeddings = DashScopeEmbeddings(
        model=settings.embeddings_model,
        dashscope_api_key=settings.embeddings_api_key,
    )
    return embeddings
