"""Общие фикстуры: testcontainers postgres:16-alpine + alembic, rollback-изоляция,
httpx.AsyncClient поверх ASGITransport с подменой сервиса через DI."""

import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator

import pytest

# Docker Desktop на macOS не даёт ryuk смонтировать ~/.docker/run/docker.sock;
# контейнер и так останавливается context-manager-ом фикстуры.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.postgres import PostgresContainer

from app.api.routes import get_reservation_service
from app.core.config import Settings
from app.main import app
from app.models import Product, Stock
from app.services.reservation import ReservationService

SeedStock = Callable[..., Awaitable[tuple[uuid.UUID, str]]]


def _run_alembic_upgrade(url: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def pg_url() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as pg:
        url = pg.get_connection_url()
        _run_alembic_upgrade(url)  # реальная схема с констрейнтами, НЕ create_all
        yield url


@pytest.fixture()
async def session_factory(pg_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Rollback-изоляция: все сессии теста живут в одной внешней транзакции,
    commit() кода превращается в SAVEPOINT, после теста всё откатывается."""
    engine = create_async_engine(pg_url, poolclass=NullPool)
    async with engine.connect() as conn:
        trans = await conn.begin()
        factory = async_sessionmaker(
            bind=conn,
            class_=AsyncSession,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        yield factory
        await trans.rollback()
    await engine.dispose()


@pytest.fixture()
def service(session_factory: async_sessionmaker[AsyncSession]) -> ReservationService:
    return ReservationService(session_factory=session_factory, settings=Settings())


@pytest.fixture()
async def client(service: ReservationService) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_reservation_service] = lambda: service
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def seed_stock(session_factory: async_sessionmaker[AsyncSession]) -> SeedStock:
    async def _seed(
        quantity: int, reserved: int = 0, sku: str | None = None
    ) -> tuple[uuid.UUID, str]:
        sku = sku or f"SKU-{uuid.uuid4().hex[:10]}"
        product_id = uuid.uuid4()
        async with session_factory() as s:
            s.add(Product(id=product_id, sku=sku, name=sku))
            s.add(Stock(product_id=product_id, quantity=quantity, reserved=reserved))
            await s.commit()
        return product_id, sku

    return _seed
