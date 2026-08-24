# reservation-callback-api

Асинхронное callback-API управления резервированием товаров:
Python 3.12, FastAPI, SQLAlchemy 2.0 (async, asyncpg), Alembic, PostgreSQL 16.

## Запуск одной командой

```bash
docker compose up -d --build --wait
# либо: make up
```

Поднимает PostgreSQL (postgres:16-alpine, healthcheck), one-shot контейнер миграций
(`alembic upgrade head`) и API, которое стартует только после успешных миграций
(`depends_on: service_completed_successfully`). API — http://localhost:8000
(порт меняется через `API_PORT`), проверка: `curl http://localhost:8000/health`.

Локально без docker: `uv sync && uvicorn app.main:app --reload`
(нужна БД из `DATABASE_URL`, см. `.env.example`). Тесты: `make test`
(testcontainers сами поднимают одноразовый PostgreSQL). Линт: `make lint`.

## Эндпоинты

| Метод | Путь | Ответы |
|---|---|---|
| POST | `/api/v1/reservations` | `202` резерв создан (PENDING), `200` повтор `idempotency_key` (тот же ответ), `409` нехватка остатка, `404` неизвестный sku, `422` невалидное тело |
| GET | `/api/v1/reservations/{id}` | `200`, `404` |
| POST | `/api/v1/reservations/{id}/confirm` | `200`, `409` невалидный переход, `404` |
| POST | `/api/v1/reservations/{id}/cancel` | `200`, `409` невалидный переход, `404` |
| GET | `/health` | `200` |

Тело создания: `{"idempotency_key": "...", "external_id": "...",
"items": [{"sku": "...", "qty": 1}]}`. Дубликаты sku в items схлопываются
суммированием. Ошибки — `{"detail": "...", "code": "..."}`. Каждый ответ несёт
`X-Request-ID`; логи — структурный JSON с `request_id` на каждый callback,
переход статуса и ошибку.

## Стейт-машина

```
PENDING ──confirm──> CONFIRMED   (остаток списывается: quantity -= qty, reserved -= qty)
   │ ────cancel───>  CANCELLED   (резерв возвращается: reserved -= qty)
   └────expires_at──> EXPIRED    (лениво при чтении/переходе; резерв возвращается)
```

Переходы только вперёд и только из PENDING; любой другой переход — `409
invalid_state_transition`. Экспирация ленивая: протухший PENDING переводится в
EXPIRED тем же гонко-устойчивым условным UPDATE при первом обращении.

## Как исключены гонки

Захват остатка — одно атомарное SQL-выражение, условие проверяет сама БД:

```sql
UPDATE stock SET reserved = reserved + :qty
WHERE product_id = :pid AND quantity - reserved >= :qty
RETURNING product_id;
```

Read-modify-write в Python отсутствует: PostgreSQL сериализует конкурентные
UPDATE одной строки, поэтому при остатке M из N параллельных запросов успешны
ровно M (покрыто тестом: 50 конкурентных запросов на остаток 10 → ровно 10
успехов). Инварианты продублированы констрейнтами БД (`CHECK reserved >= 0`,
`CHECK reserved <= quantity`, `UNIQUE idempotency_key`) — вторая линия обороны.
Многопозиционные операции сортируют позиции по `product_id` ASC до первого
запроса, поэтому встречные [A,B]/[B,A] не дедлочатся. Переход статуса — условный
`UPDATE ... WHERE status = 'PENDING' RETURNING`: из гонки confirm×cancel
побеждает ровно один. Serialization failure (40001) и deadlock (40P01)
ретраятся целой транзакцией (новая сессия, экспоненциальная пауза с джиттером).
Транзакция = один HTTP-запрос, commit только в сервисном слое.

## Как работает идемпотентность

`INSERT ... ON CONFLICT (idempotency_key) DO NOTHING RETURNING`: из двух
одновременных запросов с одним ключом строку вставляет ровно один, второй
получает пустой RETURNING и читает сохранённый в `response_snapshot` ответ
победителя — повтор возвращает **тот же ответ** с кодом `200`, второй резерв не
создаётся и остаток повторно не захватывается (покрыто конкурентным тестом).
Неуспешный запрос (нехватка остатка) откатывается целиком, поэтому ключ не
«сгорает» и может быть переиспользован.

## Покрытие (pytest --cov=app --cov-branch)

| Модуль | Cover |
|---|---|
| app/api/* (errors, middleware, routes) | 88–100% |
| app/core/* (config, db, exceptions, logging, retry) | 91–100% |
| app/models/* | 100% |
| app/repositories/* | 100% |
| app/schemas/* | 100% |
| app/services/reservation.py | 93% |
| **TOTAL (46 тестов)** | **97%** |
