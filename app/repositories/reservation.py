"""Доступ к резервам, их позициям и журналу событий."""

import uuid
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import selectinload

from app.models import Reservation, ReservationEvent, ReservationItem, ReservationStatus
from app.repositories.base import BaseRepository


class ReservationRepository(BaseRepository):
    async def create_if_absent(
        self,
        idempotency_key: str,
        external_id: str,
        expires_at: datetime | None,
    ) -> tuple[Reservation, bool]:
        """Создать резерв, если ключ идемпотентности ещё не занят.

        INSERT ... ON CONFLICT (idempotency_key) DO NOTHING RETURNING — гонко-
        устойчиво: из двух одновременных запросов с одним ключом вставит ровно
        один, второй получит пустой RETURNING (PostgreSQL дождётся исхода
        конкурирующей вставки по уникальному индексу) и прочитает существующую
        строку отдельным SELECT.

        Возвращает (резерв, created): created=False — дубликат, найден существующий.
        """
        stmt = (
            pg_insert(Reservation)
            .values(
                idempotency_key=idempotency_key,
                external_id=external_id,
                expires_at=expires_at,
            )
            .on_conflict_do_nothing(constraint="uq_reservations_idempotency_key")
            .returning(Reservation)
        )
        created = (await self._session.scalars(stmt)).one_or_none()
        if created is not None:
            return created, True
        existing = await self.get_by_idempotency_key(idempotency_key)
        if existing is None:  # pragma: no cover — резервы не удаляются
            raise RuntimeError(f"idempotency_key {idempotency_key!r} занят, но строка не найдена")
        return existing, False

    async def add_items(
        self, reservation_id: uuid.UUID, items: Iterable[tuple[uuid.UUID, int]]
    ) -> None:
        """Добавить позиции (product_id, qty) к резерву. Без commit — только flush."""
        self._session.add_all(
            ReservationItem(reservation_id=reservation_id, product_id=product_id, qty=qty)
            for product_id, qty in items
        )
        await self._session.flush()

    async def get_by_id(
        self, reservation_id: uuid.UUID, *, with_items: bool = False
    ) -> Reservation | None:
        stmt = select(Reservation).where(Reservation.id == reservation_id)
        if with_items:
            stmt = stmt.options(selectinload(Reservation.items))
        return (await self._session.scalars(stmt)).one_or_none()

    async def get_by_idempotency_key(
        self, idempotency_key: str, *, with_items: bool = False
    ) -> Reservation | None:
        stmt = select(Reservation).where(Reservation.idempotency_key == idempotency_key)
        if with_items:
            stmt = stmt.options(selectinload(Reservation.items))
        return (await self._session.scalars(stmt)).one_or_none()

    async def update_status(
        self,
        reservation_id: uuid.UUID,
        expected: ReservationStatus,
        new: ReservationStatus,
    ) -> bool:
        """Условный переход статуса одним UPDATE (гонко-устойчивая стейт-машина).

        WHERE status = :expected: из двух одновременных переходов пройдёт ровно
        один, второй получит False (0 строк) — сервис перечитает статус и решит,
        конфликт это (409) или идемпотentный повтор.
        """
        stmt = (
            update(Reservation)
            .where(Reservation.id == reservation_id, Reservation.status == expected)
            .values(status=new)
            .returning(Reservation.id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def add_event(
        self,
        reservation_id: uuid.UUID,
        from_status: ReservationStatus | None,
        to_status: ReservationStatus,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Записать событие перехода в журнал. from_status=None — создание резерва."""
        self._session.add(
            ReservationEvent(
                reservation_id=reservation_id,
                from_status=None if from_status is None else from_status.value,
                to_status=to_status.value,
                payload=payload,
            )
        )
        await self._session.flush()

    async def lock_expired_batch(self, limit: int = 100) -> Sequence[Reservation]:
        """Захватить пачку протухших резервов для воркера экспирации.

        FOR UPDATE SKIP LOCKED: параллельные воркеры не встают в очередь за
        одними и теми же строками и не обрабатывают один резерв дважды —
        залоченные другим воркером строки просто пропускаются.
        """
        stmt = (
            select(Reservation)
            .where(
                Reservation.status == ReservationStatus.PENDING,
                Reservation.expires_at.is_not(None),
                Reservation.expires_at < func.now(),
            )
            .order_by(Reservation.expires_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return (await self._session.scalars(stmt)).all()
