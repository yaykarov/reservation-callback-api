"""Pydantic-схемы callback-эндпоинтов. Только они уходят наружу — ORM никогда."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from app.models.reservation import ReservationStatus

if TYPE_CHECKING:
    from app.models import Reservation


class ReservationItemIn(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    qty: int = Field(gt=0)


class ReservationCreateRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=255)
    external_id: str = Field(min_length=1, max_length=255)
    items: list[ReservationItemIn] = Field(min_length=1)


class ReservationItemOut(BaseModel):
    sku: str
    product_id: uuid.UUID
    qty: int


class ReservationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    external_id: str
    status: ReservationStatus
    expires_at: datetime | None
    items: list[ReservationItemOut]

    @classmethod
    def from_reservation(cls, reservation: "Reservation") -> "ReservationResponse":
        """Собрать ответ из ORM-резерва с загруженными items (+product)."""
        return cls(
            id=reservation.id,
            external_id=reservation.external_id,
            status=reservation.status,
            expires_at=reservation.expires_at,
            items=[
                ReservationItemOut(sku=item.product.sku, product_id=item.product_id, qty=item.qty)
                for item in sorted(reservation.items, key=lambda i: i.product_id)
            ],
        )


class ErrorResponse(BaseModel):
    detail: str
    code: str


class HealthResponse(BaseModel):
    status: str = "ok"
