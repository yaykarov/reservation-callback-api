"""Инварианты схемы, зафиксированные в метаданных моделей (без БД).

Дублируют смоук-проверки psql из фазы 1: если кто-то удалит констрейнт из модели,
эти тесты упадут раньше, чем сломается autogenerate.
"""

import uuid

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint

from app.models import (
    Base,
    Product,
    Reservation,
    ReservationEvent,
    ReservationItem,
    ReservationStatus,
    Stock,
)


def _constraint_names(table: str, kind: type) -> set[str]:
    return {
        c.name
        for c in Base.metadata.tables[table].constraints
        if isinstance(c, kind) and c.name is not None
    }


def _index_names(table: str) -> set[str]:
    return {i.name for i in Base.metadata.tables[table].indexes if i.name is not None}


def test_all_tables_registered() -> None:
    assert set(Base.metadata.tables) == {
        "products",
        "stock",
        "reservations",
        "reservation_items",
        "reservation_events",
    }


def test_reservation_status_members() -> None:
    assert {s.value for s in ReservationStatus} == {
        "PENDING",
        "CONFIRMED",
        "CANCELLED",
        "EXPIRED",
    }


def test_idempotency_key_is_unique() -> None:
    assert "uq_reservations_idempotency_key" in _constraint_names("reservations", UniqueConstraint)


def test_stock_check_constraints() -> None:
    checks = _constraint_names("stock", CheckConstraint)
    assert {
        "ck_stock_quantity_non_negative",
        "ck_stock_reserved_non_negative",
        "ck_stock_reserved_le_quantity",
    } <= checks


def test_reservation_status_check_constraint() -> None:
    checks = _constraint_names("reservations", CheckConstraint)
    assert any("status_valid" in name for name in checks)


def test_reservation_items_qty_positive_and_unique_pair() -> None:
    assert any(
        "qty_positive" in name for name in _constraint_names("reservation_items", CheckConstraint)
    )
    uq = next(
        c
        for c in Base.metadata.tables["reservation_items"].constraints
        if isinstance(c, UniqueConstraint)
    )
    assert [col.name for col in uq.columns] == ["reservation_id", "product_id"]


def test_all_foreign_keys_are_on_delete_restrict() -> None:
    for table in Base.metadata.tables.values():
        for constraint in table.constraints:
            if isinstance(constraint, ForeignKeyConstraint):
                assert constraint.ondelete == "RESTRICT", (
                    f"{table.name}: FK {constraint.name} без ON DELETE RESTRICT"
                )


def test_required_indexes_exist() -> None:
    expiry_index = next(
        i
        for i in Base.metadata.tables["reservations"].indexes
        if i.name == "ix_reservations_status_expires_at"
    )
    assert [col.name for col in expiry_index.columns] == ["status", "expires_at"]
    assert isinstance(expiry_index, Index)
    assert "ix_reservation_items_product_id" in _index_names("reservation_items")
    assert "ix_reservation_events_reservation_id" in _index_names("reservation_events")


def test_relationships_forbid_lazy_load() -> None:
    assert Reservation.items.property.lazy == "raise"
    assert ReservationItem.product.property.lazy == "raise"
    assert ReservationItem.reservation.property.lazy == "raise"


def test_status_stored_as_varchar_not_native_enum() -> None:
    status_type = Base.metadata.tables["reservations"].columns["status"].type
    assert getattr(status_type, "native_enum", True) is False


def test_uuid_primary_keys_have_server_default() -> None:
    for table_name in ("products", "reservations", "reservation_items", "reservation_events"):
        pk_col = next(iter(Base.metadata.tables[table_name].primary_key.columns))
        assert pk_col.server_default is not None, f"{table_name}.id без gen_random_uuid()"
        assert pk_col.type.python_type is uuid.UUID


def test_event_from_status_nullable_to_status_not() -> None:
    events = Base.metadata.tables["reservation_events"].columns
    assert events["from_status"].nullable is True
    assert events["to_status"].nullable is False


def test_stock_pk_is_product_fk() -> None:
    stock_pk = [col.name for col in Base.metadata.tables["stock"].primary_key.columns]
    assert stock_pk == ["product_id"]
    assert Product.__tablename__ == "products"
    assert Stock.__tablename__ == "stock"
    assert ReservationEvent.__tablename__ == "reservation_events"
