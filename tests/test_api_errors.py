from fastapi.testclient import TestClient

from rag.main import app


client = TestClient(app)


def test_validation_error_shape() -> None:
    response = client.post("/api/qa", json={})

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["message"] == "请求参数校验失败"
    assert isinstance(body["error"]["details"], list)


def test_internal_error_shape(monkeypatch) -> None:
    from rag.api import routes

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(routes, "answer_question", boom)
    response = client.post("/api/qa", json={"question": "测试问题"})

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["message"] == "RAG 服务暂时不可用"
