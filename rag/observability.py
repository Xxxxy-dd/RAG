from __future__ import annotations

import contextvars
import json
import logging
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware


_TRACE_ID_CTX: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")
_RESERVED_LOG_RECORD_KEYS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "message",
    "asctime",
}


def new_trace_id() -> str:
    return uuid.uuid4().hex


def set_trace_id(trace_id: str | None) -> contextvars.Token[str]:
    value = (trace_id or "").strip()
    if not value:
        value = new_trace_id()
    return _TRACE_ID_CTX.set(value)


def get_trace_id() -> str:
    return _TRACE_ID_CTX.get().strip()


@contextmanager
def bind_trace_id(trace_id: str | None):
    token = set_trace_id(trace_id)
    try:
        yield get_trace_id()
    finally:
        _TRACE_ID_CTX.reset(token)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": get_trace_id() or None,
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
            "pid": os.getpid(),
        }

        for key, value in record.__dict__.items():
            if key in _RESERVED_LOG_RECORD_KEYS or key.startswith("_"):
                continue
            payload[key] = value

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str | int | None = None) -> None:
    resolved_level = level or os.getenv("LOG_LEVEL", "INFO")
    root = logging.getLogger()
    root.setLevel(resolved_level)

    if root.handlers:
        for handler in root.handlers:
            handler.setFormatter(JsonFormatter())
            handler.setLevel(resolved_level)
        return

    handler = logging.StreamHandler()
    handler.setLevel(resolved_level)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)


class RequestTraceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        incoming_trace_id = request.headers.get("x-trace-id")
        start = time.perf_counter()
        with bind_trace_id(incoming_trace_id) as trace_id:
            request.state.trace_id = trace_id
            logger = logging.getLogger("rag.api")
            logger.info(
                "request_start",
                extra={
                    "event": "request_start",
                    "method": request.method,
                    "path": request.url.path,
                    "client": request.client.host if request.client else None,
                },
            )
            response = await call_next(request)
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            response.headers["x-trace-id"] = trace_id
            logger.info(
                "request_end",
                extra={
                    "event": "request_end",
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "elapsed_ms": elapsed_ms,
                },
            )
            return response