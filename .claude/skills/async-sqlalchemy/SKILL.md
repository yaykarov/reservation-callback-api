---
name: async-sqlalchemy
description: Patterns for SQLAlchemy 2.0 async with asyncpg - engine/sessionmaker setup, session-per-request, expire_on_commit=False, select() style, eager loading to avoid MissingGreenlet. Apply when writing anything in app/core/db.py, app/repositories/, or when hitting MissingGreenlet / lazy-load errors.
---

# async-sqlalchemy

**Когда применять:** любой код, трогающий сессии/запросы SQLAlchemy; ошибки `MissingGreenlet`; настройка engine.

## Engine и фабрика сессий (app/core/db.py)

```python
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(
    settings.database_url,  # postgresql+asyncpg://...
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=5,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # инвариант проекта: атрибуты доступны после commit
    autoflush=False,
)
```

## Session per request (FastAPI dependency)

```python
from collections.abc import AsyncIterator


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session  # commit НЕ здесь — commit делает сервисный слой
```

## Запросы — только 2.0 style

```python
from sqlalchemy import select

stmt = select(Reservation).where(Reservation.idempotency_key == key)
reservation = (await session.execute(stmt)).scalar_one_or_none()
```

Запрещено: `session.query(...)` (legacy 1.x), синхронный `Session`.

## Relationship: только явная загрузка

```python
from sqlalchemy.orm import selectinload

stmt = (
    select(Reservation)
    .options(selectinload(Reservation.product))
    .where(Reservation.id == rid)
)
```

Обращение `reservation.product` без options → `MissingGreenlet` в async. Lazy-load запрещён;
в моделях ставь `lazy="raise"` на relationship, чтобы ловить это в тестах:

```python
product: Mapped["Product"] = relationship(lazy="raise")
```

## Кто коммитит

- Репозиторий: `session.add(...)`, `await session.flush()` (получить PK) — и всё.
- Сервис: `await session.commit()` один раз в конце use-case; при исключении — `rollback`.
