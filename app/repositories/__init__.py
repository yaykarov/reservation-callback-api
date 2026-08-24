"""Репозитории: SQL/ORM-доступ без бизнес-правил. Commit — только в сервисном слое."""

from app.repositories.base import BaseRepository
from app.repositories.product import ProductRepository
from app.repositories.reservation import ReservationRepository
from app.repositories.stock import StockRepository

__all__ = [
    "BaseRepository",
    "ProductRepository",
    "ReservationRepository",
    "StockRepository",
]
