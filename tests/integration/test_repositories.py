"""Интеграционные тесты репозиториев (rollback-изоляция)."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import ReservationEvent, ReservationStatus, Stock
from app.repositories import ProductRepository, ReservationRepository, StockRepository
from tests.conftest import SeedStock

Factory = async_sessionmaker[AsyncSession]


async def test_reserve_insufficient_returns_false(
    session_factory: Factory, seed_stock: SeedStock
) -> None:
    product_id, _ = await seed_stock(quantity=2)
    async with session_factory() as s:
        repo = StockRepository(s)
        assert await repo.reserve(product_id, 2) is True
        assert await repo.reserve(product_id, 1) is False  # 0 строк, не исключение
        await s.commit()


async def test_release_more_than_reserved_returns_false(
    session_factory: Factory, seed_stock: SeedStock
) -> None:
    product_id, _ = await seed_stock(quantity=5, reserved=1)
    async with session_factory() as s:
        repo = StockRepository(s)
        assert await repo.release(product_id, 2) is False
        assert await repo.release(product_id, 1) is True
        await s.commit()


async def test_commit_reservation_decrements_both(
    session_factory: Factory, seed_stock: SeedStock
) -> None:
    product_id, _ = await seed_stock(quantity=5, reserved=3)
    async with session_factory() as s:
        repo = StockRepository(s)
        assert await repo.commit_reservation(product_id, 3) is True
        stock = (await s.execute(select(Stock).where(Stock.product_id == product_id))).scalar_one()
        assert (stock.quantity, stock.reserved) == (2, 0)
        await s.commit()


async def test_reserve_many_collapses_sorts_and_reports_failure(
    session_factory: Factory, seed_stock: SeedStock
) -> None:
    a, _ = await seed_stock(quantity=10)
    b, _ = await seed_stock(quantity=1)
    async with session_factory() as s:
        repo = StockRepository(s)
        # дубликаты схлопнуты: b требует 2 > 1 -> неуспех, возвращён именно b
        failed = await repo.reserve_many([(b, 1), (a, 2), (b, 1)])
        assert failed == b
        await s.rollback()
    async with session_factory() as s:
        repo = StockRepository(s)
        assert await repo.reserve_many([(a, 2), (b, 1)]) is None
        assert await repo.release_many([(a, 2), (b, 1)]) is None
        assert await repo.release_many([(a, 1)]) == a  # уже нечего возвращать
        await s.rollback()


async def test_create_if_absent_race_free_duplicate(
    session_factory: Factory,
) -> None:
    async with session_factory() as s:
        repo = ReservationRepository(s)
        first, created1 = await repo.create_if_absent("dup-key", "ext-1", None)
        second, created2 = await repo.create_if_absent("dup-key", "ext-OTHER", None)
        assert created1 is True
        assert created2 is False
        assert second.id == first.id
        assert second.external_id == "ext-1"  # тело победителя, не проигравшего
        by_key = await repo.get_by_idempotency_key("dup-key")
        assert by_key is not None and by_key.id == first.id
        await s.commit()


async def test_update_status_is_conditional(session_factory: Factory) -> None:
    async with session_factory() as s:
        repo = ReservationRepository(s)
        r, _ = await repo.create_if_absent("k1", "ext", None)
        ok = await repo.update_status(r.id, ReservationStatus.PENDING, ReservationStatus.CONFIRMED)
        again = await repo.update_status(
            r.id, ReservationStatus.PENDING, ReservationStatus.CANCELLED
        )
        assert ok is True
        assert again is False
        fresh = await repo.get_by_id(r.id, fresh=True)
        assert fresh is not None and fresh.status is ReservationStatus.CONFIRMED
        await s.commit()


async def test_lock_expired_batch_selects_only_due_pending(session_factory: Factory) -> None:
    async with session_factory() as s:
        repo = ReservationRepository(s)
        past = datetime.now(UTC) - timedelta(minutes=1)
        future = datetime.now(UTC) + timedelta(minutes=10)
        expired, _ = await repo.create_if_absent("expired", "ext", past)
        await repo.create_if_absent("alive", "ext", future)
        confirmed, _ = await repo.create_if_absent("confirmed", "ext", past)
        await repo.update_status(
            confirmed.id, ReservationStatus.PENDING, ReservationStatus.CONFIRMED
        )

        batch = await repo.lock_expired_batch(limit=10)
        assert [r.id for r in batch] == [expired.id]
        await s.commit()


async def test_add_items_and_add_event(session_factory: Factory, seed_stock: SeedStock) -> None:
    product_id, sku = await seed_stock(quantity=5)
    async with session_factory() as s:
        repo = ReservationRepository(s)
        r, _ = await repo.create_if_absent("k-items", "ext", None)
        await repo.add_items(r.id, [(product_id, 2)])
        await repo.add_event(r.id, None, ReservationStatus.PENDING, payload={"source": "test"})
        loaded = await repo.get_by_id(r.id, with_items=True, fresh=True)
        assert loaded is not None
        assert [(i.product_id, i.qty, i.product.sku) for i in loaded.items] == [
            (product_id, 2, sku)
        ]
        events = (
            (
                await s.execute(
                    select(ReservationEvent).where(ReservationEvent.reservation_id == r.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(events) == 1 and events[0].to_status == "PENDING"
        await s.commit()


async def test_get_ids_by_skus_ignores_missing(
    session_factory: Factory, seed_stock: SeedStock
) -> None:
    product_id, sku = await seed_stock(quantity=1)
    async with session_factory() as s:
        repo = ProductRepository(s)
        mapping = await repo.get_ids_by_skus([sku, "MISSING-SKU"])
        assert mapping == {sku: product_id}


async def test_flush_helper(session_factory: Factory) -> None:
    async with session_factory() as s:
        repo = ReservationRepository(s)
        await repo.create_if_absent("k-flush", "ext", None)
        await repo.flush()


async def test_get_by_id_missing_is_none(session_factory: Factory) -> None:
    async with session_factory() as s:
        repo = ReservationRepository(s)
        assert await repo.get_by_id(uuid.uuid4()) is None
        assert await repo.get_by_idempotency_key("nope", with_items=True, fresh=True) is None
