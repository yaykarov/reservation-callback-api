# Callback API для управления резервированием товаров

Асинхронное API: Python 3.12, FastAPI, SQLAlchemy 2.0 (async), asyncpg, Alembic, PostgreSQL.
Версия PostgreSQL прибита: **postgres:16-alpine** — ровно этот образ в docker-compose.yml,
в фикстуре testcontainers и в `POSTGRES_IMAGE` (.env.example). Менять только синхронно везде.
Dev-БД слушает на хосте порт **5439** (`localhost:5439`, published-порт compose тоже 5439:5432).
Принимает callback-запросы от внешних сервисов на резервирование товаров, отдаёт статус резерва.

## Доменные инварианты (КРИТИЧНО — нарушение любого из них = баг)

1. **Идемпотентность.** Повторный callback с тем же `idempotency_key` возвращает тот же
   результат (HTTP 200), а НЕ создаёт второй резерв и НЕ отдаёт 409.
   409 — только для конфликта состояния (невалидный переход стейт-машины).
2. **Атомарность остатка.** Резерв делается одним SQL-выражением:
   `UPDATE ... WHERE quantity - reserved >= :n RETURNING ...`,
   либо через `SELECT ... FOR UPDATE` внутри той же транзакции.
   Read-modify-write в Python (прочитал → посчитал → записал) ЗАПРЕЩЁН.
3. **Стейт-машина.** `PENDING -> CONFIRMED | CANCELLED | EXPIRED`. Переходы только вперёд.
   Невалидный переход = доменное исключение (→ HTTP 409), а не молчаливый no-op.
4. **Транзакция = один HTTP-запрос.** Session per request, `expire_on_commit=False`.
   `commit()` — ТОЛЬКО в сервисном слое. Репозитории НИКОГДА не коммитят
   (допустим только `flush()`).
5. **Инварианты дублируются констрейнтами БД**, а не только кодом:
   `UNIQUE (idempotency_key)`, `CHECK (reserved >= 0)`, `CHECK (reserved <= quantity)`.

## Архитектура

```
app/api/           # роутеры FastAPI, DI, HTTP-коды. НЕ знает про SQLAlchemy
app/schemas/       # pydantic-схемы запросов/ответов. Только они уходят наружу
app/services/      # бизнес-логика, стейт-машина, транзакции (commit здесь). НЕ знает про HTTP
app/repositories/  # SQL/ORM-доступ. НЕ знает про бизнес-правила, НЕ коммитит
app/models/        # ORM-модели SQLAlchemy 2.0 (Mapped/mapped_column) + констрейнты
app/core/          # config (pydantic-settings), db (engine/session), logging, исключения
app/worker/        # фоновые задачи (экспирация резервов)
migrations/        # Alembic (async env.py)
tests/unit/        # без БД
tests/integration/ # с PostgreSQL (testcontainers)
tests/api/         # httpx.AsyncClient + ASGITransport
```

Границы слоёв:
- `api` не импортирует SQLAlchemy; `services` не импортируют FastAPI/Request/Response;
  `repositories` не содержат бизнес-правил.
- ORM-модели никогда не уходят наружу — на границе API только pydantic-схемы.

## Стиль кода

- Полная типизация. `mypy --strict` по `app/` обязан проходить.
- ruff: line-length 100, правила `E,F,I,B,ANN,ASYNC,S,UP`.
- ЗАПРЕЩЕНО: `requests`, `time.sleep`, `psycopg2`, `session.query()` (legacy 1.x style),
  синхронный I/O в хендлерах, lazy-load в async-коде (только явные
  `selectinload` / `joinedload` в запросе).
- Конфиг только через pydantic-settings (`app/core/config.py`). Никаких `os.getenv` по коду.
- Ошибки: свои доменные исключения (`app/core/exceptions.py`) + один exception handler
  в `app/api`. Тела ошибок — RFC 9457 (Problem Details, `application/problem+json`).
- Логи: структурный JSON, `request_id` через `contextvars`, прокидывается middleware.

## Коды ответов callback-эндпоинта

- `202` — callback принят, резерв создан (PENDING)
- `200` — повтор с тем же `idempotency_key`, возвращён сохранённый результат
- `409` — конфликт состояния (невалидный переход стейт-машины)
- `422` — ошибка валидации тела
- `401` — невалидная HMAC-подпись или просроченный timestamp

## Команды проекта

```bash
make up        # docker compose up -d --wait (postgres + migrate)
make down      # docker compose down (БЕЗ -v — том с данными не трогаем)
make test      # pytest -q
make cov       # pytest --cov=app --cov-report=term-missing --cov-fail-under=85
make lint      # ruff format --check . && ruff check . && mypy app
make migrate   # alembic upgrade head
alembic revision --autogenerate -m "..."   # новая миграция (существующие НЕ править)
uvicorn app.main:app --reload              # локальный запуск
```

Зависимости ставить только через менеджер пакетов (`uv add ...` / `uv sync`),
не голым `pip install`.

Гейт покрытия (Stop-хук final_gate.sh): порог 85% временно ослаблен файлом
`.coverage-grace` в корне (тесты пишутся только в фазе 6). **Фаза 6, обязательный
пункт: удалить `.coverage-grace` и убедиться, что final_gate.sh падает при <85%.**
Сами тесты фазы 1, ruff и mypy гейтятся жёстко и в grace-период.

## Частые ошибки (проверяй себя перед коммитом)

- **Коммит в репозитории.** `session.commit()` разрешён только в сервисном слое.
  В репозиториях максимум `flush()`.
- **Забытый `await`.** Корутина без await молча не выполняется. Особенно:
  `session.execute`, `session.commit`, `client.post`, `asyncio.gather` с непроверенными
  результатами.
- **Lazy-load вне сессии / в async.** `MissingGreenlet` или обращение к relationship после
  закрытия сессии. Всегда явные `selectinload`/`joinedload` в самом запросе.
- **Отсутствие FOR UPDATE / атомарного UPDATE.** Любое чтение остатка с последующей записью —
  гонка. Только атомарный `UPDATE ... WHERE ... RETURNING` или `SELECT ... FOR UPDATE`.
- **409 вместо 200 на повторный idempotency_key** — повтор это успех, не конфликт.
- **`os.getenv` в коде** вместо pydantic-settings.
- **Правка существующей миграции** в `migrations/versions/` — только новая ревизия.
