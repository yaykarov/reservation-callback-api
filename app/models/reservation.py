"""Резервы, их позиции и события переходов статуса."""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.product import Product


class ReservationStatus(enum.StrEnum):
    """Стейт-машина резерва: PENDING -> CONFIRMED | CANCELLED | EXPIRED."""

    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


# native postgres ENUM не используем: VARCHAR + явный CHECK стабилен для autogenerate.
# create_constraint=False: CHECK объявлен явно в __table_args__, чтобы он был виден
# в metadata (иначе autogenerate-сравнение констрейнтов даёт ложный diff).
reservation_status_enum = Enum(
    ReservationStatus,
    name="reservation_status",
    native_enum=False,
    length=20,
    create_constraint=False,
    validate_strings=True,
)

_STATUS_VALUES = ", ".join(f"'{status.value}'" for status in ReservationStatus)


class Reservation(Base):
    __tablename__ = "reservations"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_reservations_idempotency_key"),
        CheckConstraint(f"status IN ({_STATUS_VALUES})", name="status_valid"),
        # выборка воркера экспирации: WHERE status = 'PENDING' AND expires_at < now()
        Index("ix_reservations_status_expires_at", "status", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[ReservationStatus] = mapped_column(
        reservation_status_enum,
        nullable=False,
        default=ReservationStatus.PENDING,
        server_default=ReservationStatus.PENDING.value,
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    response_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    items: Mapped[list["ReservationItem"]] = relationship(
        back_populates="reservation", lazy="raise"
    )


class ReservationItem(Base):
    __tablename__ = "reservation_items"
    __table_args__ = (
        CheckConstraint("qty > 0", name="qty_positive"),
        UniqueConstraint(
            "reservation_id", "product_id", name="uq_reservation_items_reservation_id"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    reservation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("reservations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    qty: Mapped[int] = mapped_column(Integer, nullable=False)

    reservation: Mapped[Reservation] = relationship(back_populates="items", lazy="raise")
    product: Mapped[Product] = relationship(lazy="raise")


class ReservationEvent(Base):
    """Журнал переходов статуса. from_status IS NULL = создание резерва."""

    __tablename__ = "reservation_events"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    reservation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("reservations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
