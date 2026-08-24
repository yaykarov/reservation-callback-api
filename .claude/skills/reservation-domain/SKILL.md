---
name: reservation-domain
description: Domain rules of the reservation service - status state machine (PENDING/CONFIRMED/CANCELLED/EXPIRED), allowed transitions, domain exceptions, expiration semantics. Apply when writing services, the status enum, transition logic, or the expiration worker.
---

# reservation-domain

**Когда применять:** логика в `app/services/`, enum статусов, воркер экспирации, маппинг доменных исключений.

## Стейт-машина

```
PENDING ──confirm──> CONFIRMED   (терминальный)
PENDING ──cancel───> CANCELLED   (терминальный)
PENDING ──ttl──────> EXPIRED     (терминальный, только воркер)
```

Переходы только вперёд. Из терминальных состояний переходов нет. Невалидный переход —
доменное исключение, НЕ молчаливый no-op и НЕ создание нового резерва.

## Каноничная реализация

```python
import enum


class ReservationStatus(enum.StrEnum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


ALLOWED_TRANSITIONS: dict[ReservationStatus, frozenset[ReservationStatus]] = {
    ReservationStatus.PENDING: frozenset(
        {ReservationStatus.CONFIRMED, ReservationStatus.CANCELLED, ReservationStatus.EXPIRED}
    ),
    ReservationStatus.CONFIRMED: frozenset(),
    ReservationStatus.CANCELLED: frozenset(),
    ReservationStatus.EXPIRED: frozenset(),
}


def ensure_transition(current: ReservationStatus, new: ReservationStatus) -> None:
    if new not in ALLOWED_TRANSITIONS[current]:
        raise InvalidStateTransitionError(current=current, requested=new)
```

Доменные исключения (`app/core/exceptions.py`): `DomainError` (база),
`InvalidStateTransitionError` → 409, `InsufficientStockError` → 409/422 по контракту,
`ReservationNotFoundError` → 404. Сервисы кидают ТОЛЬКО доменные исключения,
HTTP-коды навешивает exception handler в `app/api`.

## Семантика переходов

- **confirm/cancel** приходят callback'ами; проверка перехода должна быть гонко-устойчивой —
  условный UPDATE по текущему статусу (см. скилл atomic-stock-ops), а не if в Python.
- **CANCELLED и EXPIRED возвращают остаток**: `reserved -= n` тем же атомарным UPDATE
  в той же транзакции, что и смена статуса.
- **CONFIRMED** остаток не возвращает (товар выкуплен: `quantity -= n, reserved -= n`
  либо остаётся в reserved — решение фиксируется в реализации и документируется).
- **Экспирация** — только воркер (`app/worker/`), батчами:
  `UPDATE ... WHERE status = 'PENDING' AND created_at < now() - ttl RETURNING id` +
  возврат остатка, всё в одной транзакции на батч.
