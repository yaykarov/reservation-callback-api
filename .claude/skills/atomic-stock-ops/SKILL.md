---
name: atomic-stock-ops
description: Atomic stock reservation in PostgreSQL - single conditional UPDATE ... RETURNING (or SELECT FOR UPDATE), DB CHECK constraints, race-safe status transitions, retry on serialization failure. Apply when writing or reviewing any code that changes product stock or reservation status.
---

# atomic-stock-ops

**Когда применять:** любое изменение `reserved`/`quantity` или статуса резерва; ревью гонок.

## Инвариант

Резерв — ОДНО SQL-выражение. Read-modify-write в Python (прочитал остаток → сравнил →
записал) запрещён: между чтением и записью пролезает конкурентный запрос.

## Схема с констрейнтами (вторая линия обороны)

```sql
CREATE TABLE products (
    id       uuid PRIMARY KEY,
    quantity integer NOT NULL,
    reserved integer NOT NULL DEFAULT 0,
    CONSTRAINT ck_products_reserved_non_negative CHECK (reserved >= 0),
    CONSTRAINT ck_products_reserved_le_quantity  CHECK (reserved <= quantity)
);
```

## Готовый SQL: захват остатка

```sql
UPDATE products
SET reserved = reserved + :n
WHERE id = :product_id
  AND quantity - reserved >= :n
RETURNING id, quantity, reserved;
```

0 строк → нехватка товара (`InsufficientStockError`). PostgreSQL сам сериализует
конкурентные UPDATE одной строки — при остатке M и N запросах успешны ровно M.

## Готовый SQL: возврат остатка (cancel/expire)

```sql
UPDATE products
SET reserved = reserved - :n
WHERE id = :product_id
  AND reserved >= :n
RETURNING id, reserved;
```

## Готовый SQL: гонко-устойчивый переход статуса

```sql
UPDATE reservations
SET status = :new_status, updated_at = now()
WHERE id = :reservation_id
  AND status = 'PENDING'
RETURNING id;
```

0 строк → резерв уже не PENDING → перечитай статус и кинь
`InvalidStateTransitionError` (double-confirm/двойной cancel не проходят).

## Вариант с SELECT FOR UPDATE

Когда решение сложнее одного условия (несколько строк, доменные проверки):

```python
stmt = select(Product).where(Product.id == pid).with_for_update()
product = (await session.execute(stmt)).scalar_one()
# проверки и изменение — строка залочена до конца транзакции
```

Правила: FOR UPDATE и изменение — в ОДНОЙ транзакции; несколько строк лочить только
в детерминированном порядке (ORDER BY id) — иначе дедлок; не держать лок через внешние
HTTP-вызовы.

## Ретрай сериализации

Ошибки 40001 (serialization_failure) и 40P01 (deadlock_detected) ретраятся на уровне
СЕРВИСА новой транзакцией (2–3 попытки, экспоненциальная пауза через `asyncio.sleep`).
Ретрай внутри той же транзакции бесполезен — она уже abort'нута.

```python
from sqlalchemy.exc import DBAPIError

for attempt in range(3):
    try:
        async with async_session_factory() as session:
            result = await do_reserve(session, cmd)
            await session.commit()
            return result
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) not in ("40001", "40P01") or attempt == 2:
            raise
        await asyncio.sleep(0.05 * 2**attempt)
```
