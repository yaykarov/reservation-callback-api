"""Точка входа FastAPI-приложения."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import register_exception_handlers
from app.api.middleware import request_context_middleware
from app.api.routes import health_router, router
from app.core.config import get_settings
from app.core.db import dispose_engine
from app.core.logging import configure_logging


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    configure_logging(get_settings().log_level)
    app = FastAPI(title="reservation-callback-api", lifespan=lifespan)
    app.middleware("http")(request_context_middleware)
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(router)
    return app


app = create_app()
