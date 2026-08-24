"""Middleware: request_id в contextvars — попадает в каждую JSON-строку лога."""

import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import Request, Response

from app.core.logging import get_logger

logger = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


async def request_context_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        request_id=request_id, method=request.method, path=request.url.path
    )
    response = await call_next(request)
    response.headers[REQUEST_ID_HEADER] = request_id
    logger.info("request_completed", status_code=response.status_code)
    return response
