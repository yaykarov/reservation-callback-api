---
name: idempotency
description: Race-safe idempotency for callbacks - UNIQUE constraint + INSERT ON CONFLICT, returning the stored result with 200 on retry, never 409 and never a duplicate reservation. Apply when implementing or reviewing callback intake, idempotency_key handling, or duplicate-request bugs.
---

# idempotency

**Когда применять:** приём callback'а, обработка `idempotency_key`, баги с дублями/повторами.

## Инвариант

Повторный callback с тем же `idempotency_key` → HTTP 200 и ТОТ ЖЕ результат, что у первого
запроса. Не второй резерв. Не 409. Первый запрос → 202.

## Схема: ключ живёт в самой таблице резервов

```sql
CREATE TABLE reservations (
    id              uuid PRIMARY KEY,
    idempotency_key text        NOT NULL,
    product_id      uuid        NOT NULL REFERENCES products (id),
    quantity        integer     NOT NULL CHECK (quantity > 0),
    status          text        NOT NULL DEFAULT 'PENDING',
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_reservations_idempotency_key UNIQUE (idempotency_key)
);
```

UNIQUE-констрейнт обязателен: проверка «SELECT, если нет — INSERT» без него — гонка,
два одновременных повтора создадут два резерва.

## Готовый SQL: гонко-устойчивая вставка

```sql
INSERT INTO reservations (id, idempotency_key, product_id, quantity, status)
VALUES (:id, :key, :product_id, :quantity, 'PENDING')
ON CONFLICT (idempotency_key) DO NOTHING
RETURNING id;
```

- Вернулась строка → это ПЕРВЫЙ запрос: дальше атомарное списание остатка (скилл
  atomic-stock-ops), ответ 202.
- Строк нет → повтор: `SELECT * FROM reservations WHERE idempotency_key = :key`
  и ответ 200 с сохранённым результатом.

## Сервисный слой (SQLAlchemy)

```python
stmt = (
    insert(Reservation)
    .values(id=rid, idempotency_key=key, product_id=pid, quantity=n)
    .on_conflict_do_nothing(index_elements=["idempotency_key"])
    .returning(Reservation.id)
)  # from sqlalchemy.dialects.postgresql import insert
inserted_id = (await session.execute(stmt)).scalar_one_or_none()
if inserted_id is None:
    existing = await repo.get_by_idempotency_key(session, key)
    return ReplayResult(existing)  # → HTTP 200
```

## Грабли

- Повтор возвращает результат **как он сохранён**, даже если первый запрос кончился отказом
  «нехватка товара» — итог тоже часть идемпотентного ответа.
- Если тело повтора отличается от исходного при том же ключе — это ошибка клиента:
  допустимо 422 с указанием mismatch, но НЕ создание нового резерва.
- Ключ скоупится источником (`source + idempotency_key` в UNIQUE), если callback'и шлют
  несколько внешних систем.
- `ON CONFLICT DO NOTHING` не вернёт строку и при конфликте по ДРУГОМУ констрейнту —
  указывай `index_elements` явно.
