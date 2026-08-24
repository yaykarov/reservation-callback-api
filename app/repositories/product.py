"""Доступ к товарам."""

import uuid
from collections.abc import Iterable

from sqlalchemy import select

from app.models import Product
from app.repositories.base import BaseRepository


class ProductRepository(BaseRepository):
    async def get_ids_by_skus(self, skus: Iterable[str]) -> dict[str, uuid.UUID]:
        """sku -> product_id для существующих товаров (отсутствующие просто не попадут)."""
        stmt = select(Product.sku, Product.id).where(Product.sku.in_(list(skus)))
        rows = (await self._session.execute(stmt)).all()
        return {sku: product_id for sku, product_id in rows}
