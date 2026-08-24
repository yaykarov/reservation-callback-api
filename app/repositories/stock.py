"""Атомарные операции над складским остатком.

Все изменения reserved/quantity — ОДНИМ условным UPDATE с RETURNING:
условие достаточности остатка проверяет сама БД в том же выражении,
read-modify-write в Python отсутствует по построению. Пустой RETURNING
означает «условие не выполнилось» и возвращается как False, не исключение.
"""

import uuid
from collections.abc import Iterable

from sqlalchemy import update

from app.models import Stock
from app.repositories.base import BaseRepository


class StockRepository(BaseRepository):
    async def reserve(self, product_id: uuid.UUID, qty: int) -> bool:
        """Захватить qty единиц: reserved += qty, если quantity - reserved >= qty."""
        stmt = (
            update(Stock)
            .where(Stock.product_id == product_id, Stock.quantity - Stock.reserved >= qty)
            .values(reserved=Stock.reserved + qty)
            .returning(Stock.product_id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def release(self, product_id: uuid.UUID, qty: int) -> bool:
        """Вернуть qty единиц в доступный остаток (cancel/expire): reserved -= qty."""
        stmt = (
            update(Stock)
            .where(Stock.product_id == product_id, Stock.reserved >= qty)
            .values(reserved=Stock.reserved - qty)
            .returning(Stock.product_id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def commit_reservation(self, product_id: uuid.UUID, qty: int) -> bool:
        """Списать подтверждённый резерв: quantity -= qty и reserved -= qty одним UPDATE."""
        stmt = (
            update(Stock)
            .where(Stock.product_id == product_id, Stock.reserved >= qty)
            .values(quantity=Stock.quantity - qty, reserved=Stock.reserved - qty)
            .returning(Stock.product_id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def reserve_many(self, items: Iterable[tuple[uuid.UUID, int]]) -> uuid.UUID | None:
        """Зарезервировать несколько позиций в одной транзакции.

        Дубликаты product_id схлопываются суммированием qty, затем позиции
        сортируются по product_id ASC ДО первого запроса к БД: все транзакции
        захватывают блокировки строк stock в одном и том же порядке, поэтому
        встречный порядок [A, B] / [B, A] не приводит к дедлоку.

        Возвращает None при успехе, иначе product_id первой позиции с нехваткой
        остатка. При неуспехе вызывающий сервис обязан откатить ВСЮ транзакцию:
        уже выполненные reserve() этого вызова остаются в её незакоммиченном
        состоянии и сами по себе не отменяются.
        """
        collapsed: dict[uuid.UUID, int] = {}
        for product_id, qty in items:
            collapsed[product_id] = collapsed.get(product_id, 0) + qty
        ordered = sorted(collapsed.items())  # ASC по product_id — анти-дедлок
        for product_id, qty in ordered:
            if not await self.reserve(product_id, qty):
                return product_id
        return None
