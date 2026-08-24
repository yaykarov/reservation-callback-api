"""Доменные исключения. Слой api маппит их в HTTP-коды (сервисы про HTTP не знают)."""

import uuid


class DomainError(Exception):
    """Базовое доменное исключение; code уходит клиенту в теле {detail, code}."""

    code = "domain_error"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class ProductNotFoundError(DomainError):
    code = "product_not_found"

    def __init__(self, sku: str) -> None:
        super().__init__(f"товар с sku {sku!r} не найден")
        self.sku = sku


class ReservationNotFoundError(DomainError):
    code = "reservation_not_found"

    def __init__(self, reservation_id: uuid.UUID) -> None:
        super().__init__(f"резерв {reservation_id} не найден")
        self.reservation_id = reservation_id


class InsufficientStockError(DomainError):
    code = "insufficient_stock"

    def __init__(self, sku: str) -> None:
        super().__init__(f"недостаточно остатка для sku {sku!r}")
        self.sku = sku


class InvalidStateTransitionError(DomainError):
    code = "invalid_state_transition"

    def __init__(self, current: str, target: str) -> None:
        super().__init__(f"недопустимый переход статуса {current} -> {target}")
        self.current = current
        self.target = target
