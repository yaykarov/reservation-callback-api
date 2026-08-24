"""API-тесты: идемпотентность, стейт-машина, нехватка остатка, экспирация, ошибки."""

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.routes import get_reservation_service
from app.core.config import Settings
from app.main import app
from app.models import Reservation, Stock
from app.services.reservation import ReservationService
from tests.conftest import SeedStock


def _body(sku: str, qty: int = 1, key: str | None = None) -> dict[str, Any]:
    return {
        "idempotency_key": key or f"key-{uuid.uuid4().hex}",
        "external_id": "ext-1",
        "items": [{"sku": sku, "qty": qty}],
    }


async def _stock_row(
    factory: async_sessionmaker[AsyncSession], product_id: uuid.UUID
) -> tuple[int, int]:
    async with factory() as s:
        stock = (
            await s.execute(
                select(Stock)
                .where(Stock.product_id == product_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        return stock.quantity, stock.reserved


async def test_health(client: AsyncClient) -> None:
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_create_returns_202_and_reserves(
    client: AsyncClient, seed_stock: SeedStock, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    product_id, sku = await seed_stock(quantity=10)
    r = await client.post("/api/v1/reservations", json=_body(sku, qty=3))
    assert r.status_code == 202
    data = r.json()
    assert data["status"] == "PENDING"
    assert data["items"] == [{"sku": sku, "product_id": str(product_id), "qty": 3}]
    assert await _stock_row(session_factory, product_id) == (10, 3)


async def test_duplicate_skus_are_collapsed(client: AsyncClient, seed_stock: SeedStock) -> None:
    _, sku = await seed_stock(quantity=10)
    body = _body(sku)
    body["items"] = [{"sku": sku, "qty": 2}, {"sku": sku, "qty": 3}]
    r = await client.post("/api/v1/reservations", json=body)
    assert r.status_code == 202
    assert [i["qty"] for i in r.json()["items"]] == [5]


async def test_idempotent_replay_returns_200_and_same_body(
    client: AsyncClient, seed_stock: SeedStock, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    product_id, sku = await seed_stock(quantity=10)
    body = _body(sku, qty=2)
    first = await client.post("/api/v1/reservations", json=body)
    second = await client.post("/api/v1/reservations", json=body)
    assert first.status_code == 202
    assert second.status_code == 200
    assert second.json() == first.json()
    # второй резерв не создан, остаток захвачен один раз
    async with session_factory() as s:
        count = len((await s.execute(select(Reservation.id))).all())
    assert count == 1
    assert await _stock_row(session_factory, product_id) == (10, 2)


async def test_insufficient_stock_409_and_key_not_burned(
    client: AsyncClient, seed_stock: SeedStock, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    product_id, sku = await seed_stock(quantity=1)
    body = _body(sku, qty=5)
    r = await client.post("/api/v1/reservations", json=body)
    assert r.status_code == 409
    assert r.json()["code"] == "insufficient_stock"
    assert await _stock_row(session_factory, product_id) == (1, 0)
    # неуспех откатился целиком: тот же ключ можно использовать снова
    body["items"][0]["qty"] = 1
    retry = await client.post("/api/v1/reservations", json=body)
    assert retry.status_code == 202


async def test_unknown_sku_404(client: AsyncClient) -> None:
    r = await client.post("/api/v1/reservations", json=_body("NO-SUCH-SKU"))
    assert r.status_code == 404
    assert r.json()["code"] == "product_not_found"


async def test_get_unknown_id_404(client: AsyncClient) -> None:
    r = await client.get(f"/api/v1/reservations/{uuid.uuid4()}")
    assert r.status_code == 404
    assert r.json()["code"] == "reservation_not_found"


async def test_validation_422(client: AsyncClient, seed_stock: SeedStock) -> None:
    _, sku = await seed_stock(quantity=1)
    r = await client.post("/api/v1/reservations", json=_body(sku, qty=0))
    assert r.status_code == 422
    r = await client.post(
        "/api/v1/reservations",
        json={"idempotency_key": "k", "external_id": "e", "items": []},
    )
    assert r.status_code == 422


async def test_confirm_commits_stock_and_forbids_further_transitions(
    client: AsyncClient, seed_stock: SeedStock, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    product_id, sku = await seed_stock(quantity=10)
    rid = (await client.post("/api/v1/reservations", json=_body(sku, qty=4))).json()["id"]

    confirm = await client.post(f"/api/v1/reservations/{rid}/confirm")
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "CONFIRMED"
    assert await _stock_row(session_factory, product_id) == (6, 0)

    again = await client.post(f"/api/v1/reservations/{rid}/confirm")
    assert again.status_code == 409
    assert again.json()["code"] == "invalid_state_transition"
    cancel = await client.post(f"/api/v1/reservations/{rid}/cancel")
    assert cancel.status_code == 409
    # повторные попытки ничего не списали
    assert await _stock_row(session_factory, product_id) == (6, 0)


async def test_cancel_releases_stock(
    client: AsyncClient, seed_stock: SeedStock, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    product_id, sku = await seed_stock(quantity=10)
    rid = (await client.post("/api/v1/reservations", json=_body(sku, qty=4))).json()["id"]
    cancel = await client.post(f"/api/v1/reservations/{rid}/cancel")
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "CANCELLED"
    assert await _stock_row(session_factory, product_id) == (10, 0)
    get = await client.get(f"/api/v1/reservations/{rid}")
    assert get.json()["status"] == "CANCELLED"


async def test_lazy_expiration_on_read_and_confirm_conflict(
    client: AsyncClient,
    seed_stock: SeedStock,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """TTL инъектируется отрицательным: резерв создаётся уже протухшим."""
    product_id, sku = await seed_stock(quantity=10)
    expired_service = ReservationService(
        session_factory=session_factory, settings=Settings(reservation_ttl_seconds=-5)
    )
    app.dependency_overrides[get_reservation_service] = lambda: expired_service

    rid = (await client.post("/api/v1/reservations", json=_body(sku, qty=3))).json()["id"]
    assert await _stock_row(session_factory, product_id) == (10, 3)

    get = await client.get(f"/api/v1/reservations/{rid}")
    assert get.status_code == 200
    assert get.json()["status"] == "EXPIRED"
    assert await _stock_row(session_factory, product_id) == (10, 0)

    confirm = await client.post(f"/api/v1/reservations/{rid}/confirm")
    assert confirm.status_code == 409
    assert confirm.json()["code"] == "invalid_state_transition"


async def test_expired_reservation_confirm_is_409_without_prior_read(
    client: AsyncClient,
    seed_stock: SeedStock,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    product_id, sku = await seed_stock(quantity=10)
    expired_service = ReservationService(
        session_factory=session_factory, settings=Settings(reservation_ttl_seconds=-5)
    )
    app.dependency_overrides[get_reservation_service] = lambda: expired_service
    rid = (await client.post("/api/v1/reservations", json=_body(sku, qty=3))).json()["id"]

    confirm = await client.post(f"/api/v1/reservations/{rid}/confirm")
    assert confirm.status_code == 409
    # экспирация случилась лениво прямо в confirm и вернула остаток
    assert await _stock_row(session_factory, product_id) == (10, 0)
