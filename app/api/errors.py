"""Единый маппинг доменных исключений в HTTP-ответы вида {detail, code}."""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.core.exceptions import (
    DomainError,
    InsufficientStockError,
    InvalidStateTransitionError,
    ProductNotFoundError,
    ReservationNotFoundError,
)
from app.core.logging import get_logger

logger = get_logger(__name__)

_STATUS_BY_EXC: dict[type[DomainError], int] = {
    ProductNotFoundError: status.HTTP_404_NOT_FOUND,
    ReservationNotFoundError: status.HTTP_404_NOT_FOUND,
    InsufficientStockError: status.HTTP_409_CONFLICT,
    InvalidStateTransitionError: status.HTTP_409_CONFLICT,
}


async def _domain_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)  # noqa: S101 — хендлер зарегистрирован на DomainError
    http_status = _STATUS_BY_EXC.get(type(exc), status.HTTP_400_BAD_REQUEST)
    logger.warning("domain_error", code=exc.code, detail=exc.detail, status_code=http_status)
    return JSONResponse(status_code=http_status, content={"detail": exc.detail, "code": exc.code})


async def _unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.error("unhandled_error", error=repr(exc), exc_info=exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "internal server error", "code": "internal_error"},
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, _domain_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)
