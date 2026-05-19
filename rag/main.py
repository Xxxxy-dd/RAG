from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api.routes import router as rag_router
from .observability import RequestTraceMiddleware, configure_logging


configure_logging()
app = FastAPI(title="RAG QA Demo")
app.include_router(rag_router)
app.add_middleware(RequestTraceMiddleware)

LOGGER = logging.getLogger(__name__)


def _error_payload(code: str, message: str, details=None, trace_id: str | None = None) -> dict:
	return {
		"error": {
			"code": code,
			"message": message,
			"details": details,
			"trace_id": trace_id,
		},
	}


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc: StarletteHTTPException):
	code = "bad_request" if exc.status_code < 500 else "internal_error"
	message = exc.detail if isinstance(exc.detail, str) else "请求处理失败"
	trace_id = getattr(request.state, "trace_id", None)
	return JSONResponse(
		status_code=exc.status_code,
		content=_error_payload(code=code, message=message, trace_id=trace_id),
	)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc: RequestValidationError):
	trace_id = getattr(request.state, "trace_id", None)
	return JSONResponse(
		status_code=422,
		content=_error_payload(code="validation_error", message="请求参数校验失败", details=exc.errors(), trace_id=trace_id),
	)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc: Exception):
	trace_id = getattr(request.state, "trace_id", None)
	LOGGER.exception("Unhandled error on %s %s", request.method, request.url.path, extra={"event": "unhandled_exception"})
	return JSONResponse(
		status_code=500,
		content=_error_payload(code="internal_error", message="RAG 服务暂时不可用", trace_id=trace_id),
	)


@app.get("/")
def root() -> dict[str, str]:
	return {"status": "ok", "message": "RAG QA Demo backend is running"}


__all__ = ["app"]