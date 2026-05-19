import json
from dataclasses import dataclass
from urllib import error, request

from ..config import get_settings


@dataclass(slots=True)
class ChatClient:
    """OpenAI 兼容聊天模型客户端。"""

    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    timeout: int | None = None

    def __post_init__(self) -> None:
        settings = get_settings()
        self.model = self.model or settings.llm_model
        self.api_key = self.api_key or settings.llm_api_key
        self.base_url = (self.base_url or settings.llm_base_url).rstrip("/")
        self.timeout = self.timeout or settings.llm_timeout

        if not self.api_key:
            raise RuntimeError("环境变量 LLM_API_KEY 未配置")

    def complete(self, prompt: str, system_prompt: str = "你是一个严谨的检索问答助手。") -> str:
        """发送一次聊天补全请求并返回文本。"""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        data = json.dumps(payload).encode("utf-8")

        req = request.Request(
            url=f"{self.base_url}/chat/completions",
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )

        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"LLM 请求失败: HTTP {exc.code}, {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"LLM 网络请求失败: {exc.reason}") from exc

        try:
            return resp_data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"LLM 返回格式异常: {resp_data}") from exc
