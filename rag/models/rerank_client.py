import importlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence
from urllib import error, request

from ..config import get_settings


@dataclass(slots=True)
class RerankClient:
    """统一重排客户端，支持本地模型与远端 API。"""

    mode: str | None = None
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    timeout: int | None = None
    model_path: str | None = None
    device: str | None = None
    batch_size: int = 16
    _local_model: object | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        settings = get_settings()
        self.mode = (self.mode or settings.rerank_mode).strip().lower()
        self.model = self.model or settings.rerank_model
        self.api_key = self.api_key or settings.rerank_api_key
        self.base_url = (self.base_url or settings.rerank_base_url).rstrip("/")
        self.timeout = self.timeout or settings.rerank_timeout
        self.model_path = (getattr(settings, "rerank_model_path", None) or "").strip() or None

        if self.mode not in {"local", "remote"}:
            raise ValueError(f"不支持的 RERANK_MODE: {self.mode}")

        if self.mode == "remote" and not self.api_key:
            raise RuntimeError("RERANK_MODE=remote 时，环境变量 RERANK_API_KEY 必须配置")

    def _resolve_cached_snapshot_dir(self) -> str | None:
        """优先解析本机 Hugging Face cache 中已经下载好的 snapshot。"""
        if not self.model:
            return None

        cache_root = Path.home() / ".cache" / "huggingface" / "hub"
        repo_dir = cache_root / f"models--{self.model.replace('/', '--')}"
        if not repo_dir.exists():
            return None

        refs_main = repo_dir / "refs" / "main"
        if refs_main.exists():
            commit = refs_main.read_text(encoding="utf-8").strip()
            snapshot_dir = repo_dir / "snapshots" / commit
            if snapshot_dir.exists():
                return str(snapshot_dir)

        snapshots_dir = repo_dir / "snapshots"
        if not snapshots_dir.exists():
            return None

        candidates = [path for path in snapshots_dir.iterdir() if path.is_dir()]
        if not candidates:
            return None

        candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        return str(candidates[0])

    def _resolve_local_model_name(self) -> str:
        if self.model_path:
            path = Path(self.model_path).expanduser()
            if path.exists():
                return str(path)

        cached_snapshot = self._resolve_cached_snapshot_dir()
        if cached_snapshot:
            return cached_snapshot

        return self.model or ""

    def _resolve_local_model(self):
        if self._local_model is not None:
            return self._local_model

        try:
            module = importlib.import_module("sentence_transformers")
            CrossEncoder = getattr(module, "CrossEncoder")
        except ImportError as exc:
            raise RuntimeError("未安装 sentence-transformers，无法执行本地重排") from exc

        kwargs: dict[str, object] = {}
        if self.device:
            kwargs["device"] = self.device
        self._local_model = CrossEncoder(self._resolve_local_model_name(), **kwargs)
        return self._local_model

    def _local_rerank_scores(self, query: str, documents: Sequence[str]) -> list[float]:
        model = self._resolve_local_model()
        pairs = [(query, text) for text in documents]
        scores = model.predict(pairs, batch_size=self.batch_size)
        return [float(score) for score in scores]

    def _remote_rerank_scores(self, query: str, documents: Sequence[str]) -> list[float]:
        payload = {
            "model": self.model,
            "query": query,
            "documents": list(documents),
        }
        data = json.dumps(payload).encode("utf-8")

        req = request.Request(
            url=f"{self.base_url}/rerank",
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
            raise RuntimeError(f"Rerank 请求失败: HTTP {exc.code}, {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Rerank 网络请求失败: {exc.reason}") from exc

        data_list = resp_data.get("data")
        if not isinstance(data_list, list):
            raise RuntimeError(f"Rerank 返回格式异常: {resp_data}")

        scores: list[float] = [0.0] * len(documents)
        for item in data_list:
            if not isinstance(item, dict):
                continue
            idx = item.get("index")
            score = item.get("relevance_score")
            if isinstance(idx, int) and 0 <= idx < len(scores):
                scores[idx] = float(score or 0.0)
        return scores

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        """返回 query 与候选文档的一组重排分数。"""
        if not query or not query.strip():
            raise ValueError("query 不能为空")
        if not documents:
            return []

        cleaned_query = query.strip()
        if self.mode == "remote":
            return self._remote_rerank_scores(cleaned_query, documents)
        return self._local_rerank_scores(cleaned_query, documents)
