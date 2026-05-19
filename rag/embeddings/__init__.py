from .remote_embedder import remote_embedder_model

__all__ = ["remote_embedder_model"]

#暴露接口，供外部调用
def embeddings():
    return remote_embedder_model()





