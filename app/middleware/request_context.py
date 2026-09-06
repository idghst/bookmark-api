"""Request ID propagation and request completion logging."""

import logging
import re
from time import perf_counter
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.core.config import resolve_app_env
from app.core.errors import _error_response

REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,128}")
logger = logging.getLogger(__name__)


def _is_docs_path(path: str) -> bool:
    return path == "/openapi.json" or path.startswith(("/docs", "/redoc"))


def resolve_request_id(value: str | None) -> str:
    """Keep safe client IDs or create a fresh server request ID."""

    if value is not None and REQUEST_ID_PATTERN.fullmatch(value):
        return value
    return str(uuid4())


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request ID and log the completed request without headers."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = resolve_request_id(request.headers.get("X-Request-ID"))
        request.state.request_id = request_id
        started = perf_counter()
        status: int | None = None
        exception_type: str | None = None

        try:
            if resolve_app_env(
                request.headers.get("host", ""), str(request.url)
            ) == "production" and _is_docs_path(request.url.path):
                status = 404
                return _error_response(request, 404, "http_error", "HTTP error")
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception as error:
            if status is None:
                status = 500
            exception_type = type(error).__name__
            raise
        finally:
            logger.info(
                "request completed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": status,
                    "duration": round((perf_counter() - started) * 1000, 3),
                    "exception_type": exception_type,
                },
            )
