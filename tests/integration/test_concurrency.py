"""Конкурентные тесты. БЕЗ rollback-фикстуры: каждой корутине — своя сессия
на СВОЁМ соединении (NullPool), иначе конкуренции нет. Чистка — TRUNCATE."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.api.routes import get_reservation_service
from app.core.config import Settings
from app.main import app
from app.models import Product, Reservation, Stock
from app.services.reservation import ReservationService


@pytest.fixture()
async def engine(pg_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(pg_url, poolclass=NullPool)
    yield engine
    async with engine.connect() as conn:
        await conn.execute(
            text("TRUNCATE reservation_events, reservation_items, reservations, stock, products")
        )
        await conn.commit()
    await engine.dispose()


@pytest.fixture()
def factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture()
async def concurrent_client(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    service = ReservationService(session_factory=factory, settings=Settings())
    app.dependency_overrides[get_reservation_service] = lambda: service
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def _seed(factory: async_sessionmaker[AsyncSession], quantity: int) -> tuple[uuid.UUID, str]:
    sku = f"SKU-{uuid.uuid4().hex[:10]}"
    product_id = uuid.uuid4()
    async with factory() as s:
        s.add(Product(id=product_id, sku=sku, name=sku))
        s.add(Stock(product_id=product_id, quantity=quantity, reserved=0))
        await s.commit()
    return product_id, sku


def _body(sku: str, key: str, qty: int = 1) -> dict[str, Any]:
    return {"idempotency_key": key, "external_id": "ext", "items": [{"sku": sku, "qty": qty}]}


async def test_50_concurrent_requests_reserve_exactly_10(
    concurrent_client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    """Остаток 10, 50 параллельных запросов -> ровно 10 успехов (202),
    остальные 409; reserved == 10 и никогда не больше quantity."""
    product_id, sku = await _seed(factory, quantity=10)

    responses = await asyncio.gather(
        *(
            concurrent_client.post("/api/v1/reservations", json=_body(sku, key=f"k-{i}"))
            for i in range(50)
        )
    )
    codes = sorted(r.status_code for r in responses)
    assert codes.count(202) == 10, f"успехов {codes.count(202)}, ожидалось ровно 10: {codes}"
    assert codes.count(409) == 40
    assert all(r.json()["code"] == "insufficient_stock" for r in responses if r.status_code == 409)

    async with factory() as s:
        stock = (await s.execute(select(Stock).where(Stock.product_id == product_id))).scalar_one()
        reservations = (await s.execute(select(Reservation.id))).all()
    assert stock.reserved == 10
    assert stock.reserved <= stock.quantity
    assert len(reservations) == 10


async def test_concurrent_same_idempotency_key_creates_single_reservation(
    concurrent_client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    product_id, sku = await _seed(factory, quantity=10)
    body = _body(sku, key="same-key", qty=2)

    responses = await asyncio.gather(
        *(concurrent_client.post("/api/v1/reservations", json=body) for _ in range(5))
    )
    codes = sorted(r.status_code for r in responses)
    assert codes == [200, 200, 200, 200, 202], codes
    bodies = [r.json() for r in responses]
    assert all(b == bodies[0] for b in bodies), "повтор обязан отдавать тот же ответ"

    async with factory() as s:
        stock = (await s.execute(select(Stock).where(Stock.product_id == product_id))).scalar_one()
        count = len((await s.execute(select(Reservation.id))).all())
    assert count == 1, "повтор ключа не должен создавать второй резерв"
    assert stock.reserved == 2, "остаток захвачен ровно один раз"


async def test_concurrent_confirm_and_cancel_exactly_one_wins(
    concurrent_client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    product_id, sku = await _seed(factory, quantity=10)
    create = await concurrent_client.post("/api/v1/reservations", json=_body(sku, key="k", qty=4))
    rid = create.json()["id"]

    confirm, cancel = await asyncio.gather(
        concurrent_client.post(f"/api/v1/reservations/{rid}/confirm"),
        concurrent_client.post(f"/api/v1/reservations/{rid}/cancel"),
    )
    assert sorted([confirm.status_code, cancel.status_code]) == [200, 409]

    async with factory() as s:
        stock = (await s.execute(select(Stock).where(Stock.product_id == product_id))).scalar_one()
    if confirm.status_code == 200:
        assert (stock.quantity, stock.reserved) == (6, 0)  # списано
    else:
        assert (stock.quantity, stock.reserved) == (10, 0)  # возвращено
