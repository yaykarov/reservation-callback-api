"""Бизнес-логика резервирования: стейт-машина, транзакции, идемпотентность.

Каждый use-case выполняется в СВОЕЙ транзакции (commit только здесь) и целиком
ретраится на serialization failure / deadlock через retry_transaction —
на каждую попытку открывается новая сессия.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.db import get_session_factory
from app.core.exceptions import (
    InsufficientStockError,
    InvalidStateTransitionError,
    ProductNotFoundError,
    ReservationNotFoundError,
)
from app.core.logging import get_logger
from app.core.retry import retry_transaction
from app.models import Reservation, ReservationStatus
from app.repositories import ProductRepository, ReservationRepository, StockRepository
from app.schemas import ReservationCreateRequest, ReservationItemOut, ReservationResponse

logger = get_logger(__name__)


class ReservationService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._session_factory = session_factory or get_session_factory()
        self._settings = settings or get_settings()

    async def create(self, payload: ReservationCreateRequest) -> tuple[ReservationResponse, bool]:
        """Создать резерв (или отдать сохранённый ответ по повторному idempotency_key).

        Возвращает (ответ, replayed): replayed=True — повтор, HTTP-слой отдаст 200.
        """
        log = logger.bind(idempotency_key=payload.idempotency_key, external_id=payload.external_id)
        log.info("callback_received", items_count=len(payload.items))

        # дубликаты sku схлопываются до любого запроса к БД
        by_sku: dict[str, int] = {}
        for item in payload.items:
            by_sku[item.sku] = by_sku.get(item.sku, 0) + item.qty

        async def op() -> tuple[ReservationResponse, bool]:
            async with self._session_factory() as session:
                products = ProductRepository(session)
                stock = StockRepository(session)
                reservations = ReservationRepository(session)

                sku_to_id = await products.get_ids_by_skus(by_sku)
                missing = sorted(set(by_sku) - set(sku_to_id))
                if missing:
                    raise ProductNotFoundError(missing[0])
                id_to_sku = {pid: sku for sku, pid in sku_to_id.items()}
                # сортировка по product_id ASC до первого захвата блокировок
                items = sorted((sku_to_id[sku], qty) for sku, qty in by_sku.items())

                expires_at = datetime.now(UTC) + timedelta(
                    seconds=self._settings.reservation_ttl_seconds
                )
                reservation, created = await reservations.create_if_absent(
                    payload.idempotency_key, payload.external_id, expires_at
                )
                if not created:
                    if reservation.response_snapshot is None:  # pragma: no cover
                        raise RuntimeError(f"резерв {reservation.id} без response_snapshot")
                    log.info("reservation_replayed", reservation_id=str(reservation.id))
                    return (
                        ReservationResponse.model_validate(reservation.response_snapshot),
                        True,
                    )

                failed = await stock.reserve_many(items)
                if failed is not None:
                    # исключение => транзакция откатится целиком, включая строку резерва
                    log.warning(
                        "insufficient_stock",
                        sku=id_to_sku[failed],
                        product_id=str(failed),
                    )
                    raise InsufficientStockError(id_to_sku[failed])

                await reservations.add_items(reservation.id, items)
                response = ReservationResponse(
                    id=reservation.id,
                    external_id=reservation.external_id,
                    status=reservation.status,
                    expires_at=reservation.expires_at,
                    items=[
                        ReservationItemOut(sku=id_to_sku[pid], product_id=pid, qty=qty)
                        for pid, qty in items
                    ],
                )
                reservation.response_snapshot = response.model_dump(mode="json")
                await session.commit()
                log.info("reservation_created", reservation_id=str(reservation.id))
                return response, False

        return await retry_transaction(op)

    async def get(self, reservation_id: uuid.UUID) -> ReservationResponse:
        async def op() -> ReservationResponse:
            async with self._session_factory() as session:
                reservations = ReservationRepository(session)
                stock = StockRepository(session)
                reservation = await reservations.get_by_id(
                    reservation_id, with_items=True, fresh=True
                )
                if reservation is None:
                    raise ReservationNotFoundError(reservation_id)
                await self._expire_if_due(reservations, stock, reservation)
                await session.commit()  # фиксирует ленивую экспирацию, иначе no-op
                return ReservationResponse.from_reservation(reservation)

        return await retry_transaction(op)

    async def confirm(self, reservation_id: uuid.UUID) -> ReservationResponse:
        return await self._transition(reservation_id, ReservationStatus.CONFIRMED)

    async def cancel(self, reservation_id: uuid.UUID) -> ReservationResponse:
        return await self._transition(reservation_id, ReservationStatus.CANCELLED)

    async def _transition(
        self, reservation_id: uuid.UUID, target: ReservationStatus
    ) -> ReservationResponse:
        async def op() -> ReservationResponse:
            async with self._session_factory() as session:
                reservations = ReservationRepository(session)
                stock = StockRepository(session)
                reservation = await reservations.get_by_id(
                    reservation_id, with_items=True, fresh=True
                )
                if reservation is None:
                    raise ReservationNotFoundError(reservation_id)
                expired_now = await self._expire_if_due(reservations, stock, reservation)

                # сначала переход (row lock на резерве сериализует конкурентов),
                # и только при выигрыше — компенсация остатка
                won = reservation.status is ReservationStatus.PENDING and (
                    await reservations.update_status(
                        reservation.id, ReservationStatus.PENDING, target
                    )
                )
                if not won:
                    if expired_now:
                        # ленивая экспирация не должна откатиться вместе с 409
                        await session.commit()
                    fresh = await reservations.get_by_id(reservation_id, fresh=True)
                    current = fresh.status.value if fresh is not None else "UNKNOWN"
                    logger.warning(
                        "invalid_state_transition",
                        reservation_id=str(reservation_id),
                        current=current,
                        target=target.value,
                    )
                    raise InvalidStateTransitionError(current, target.value)

                items = [(item.product_id, item.qty) for item in reservation.items]
                apply = (
                    stock.commit_many
                    if target is ReservationStatus.CONFIRMED
                    else (stock.release_many)
                )
                failed = await apply(items)
                if failed is not None:  # pragma: no cover — сломан инвариант БД
                    raise RuntimeError(f"расхождение остатка по product_id={failed}")
                reservation.status = target
                await session.commit()
                logger.info(
                    "status_transition",
                    reservation_id=str(reservation.id),
                    from_status=ReservationStatus.PENDING.value,
                    to_status=target.value,
                )
                return ReservationResponse.from_reservation(reservation)

        return await retry_transaction(op)

    async def _expire_if_due(
        self,
        reservations: ReservationRepository,
        stock: StockRepository,
        reservation: Reservation,
    ) -> bool:
        """Ленивая экспирация: PENDING с истёкшим expires_at переводится в EXPIRED
        (условным UPDATE — гонко-устойчиво) и остаток возвращается.

        True — экспирация выполнена в ЭТОЙ транзакции (её нужно закоммитить)."""
        if reservation.status is not ReservationStatus.PENDING:
            return False
        if reservation.expires_at is None or reservation.expires_at > datetime.now(UTC):
            return False
        won = await reservations.update_status(
            reservation.id, ReservationStatus.PENDING, ReservationStatus.EXPIRED
        )
        if won:
            failed = await stock.release_many(
                (item.product_id, item.qty) for item in reservation.items
            )
            if failed is not None:  # pragma: no cover — сломан инвариант БД
                raise RuntimeError(f"расхождение остатка по product_id={failed}")
            reservation.status = ReservationStatus.EXPIRED
            logger.info(
                "status_transition",
                reservation_id=str(reservation.id),
                from_status=ReservationStatus.PENDING.value,
                to_status=ReservationStatus.EXPIRED.value,
                reason="lazy_expiration",
            )
            return True
        fresh = await reservations.get_by_id(reservation.id, with_items=True, fresh=True)
        if fresh is not None:
            reservation.status = fresh.status
        return False
