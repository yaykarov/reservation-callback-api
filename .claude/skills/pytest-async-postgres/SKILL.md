---
name: pytest-async-postgres
description: Test infrastructure - testcontainers PostgreSQL fixture, per-test transaction rollback, separate sessions for concurrency tests, httpx.AsyncClient over ASGITransport, asyncio_mode=auto. Apply when writing conftest.py, fixtures, or any integration/api test.
---

# pytest-async-postgres

**Когда применять:** conftest.py, фикстуры БД/клиента, интеграционные и API-тесты.

**Версия Postgres прибита: `postgres:16-alpine`.** Ровно этот образ в фикстуре
testcontainers, в docker-compose.yml и в `POSTGRES_IMAGE` из `.env.example`.
Другие теги (16, 17, latest) не использовать; менять версию — только синхронно
во всех трёх местах.

## Контейнер + миграции (session scope)

```python
# tests/conftest.py
import pytest
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def pg_url() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as pg:
        url = pg.get_connection_url()
        _run_alembic_upgrade(url)  # реальная схема с констрейнтами, НЕ create_all
        yield url


def _run_alembic_upgrade(url: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
```

## Изоляция: транзакция + rollback после теста

```python
@pytest.fixture()
async def session(pg_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(pg_url, poolclass=NullPool)
    async with engine.connect() as conn:
        trans = await conn.begin()
        factory = async_sessionmaker(bind=conn, expire_on_commit=False,
                                     join_transaction_mode="create_savepoint")
        async with factory() as s:
            yield s
        await trans.rollback()
    await engine.dispose()
```

`join_transaction_mode="create_savepoint"` позволяет коду звать `commit()` (SAVEPOINT),
а внешний rollback всё откатывает.

## Конкурентные тесты — БЕЗ rollback-фикстуры

Rollback-изоляция даёт один connection — конкуренции не будет. Каждой корутине — своя
сессия, чистка через TRUNCATE:

```python
async def test_concurrent_reserve_exactly_m_wins(pg_url: str) -> None:
    engine = create_async_engine(pg_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    await _seed_product(factory, quantity=M)

    async def one_request(i: int) -> bool:
        async with factory() as s:
            try:
                await reserve(s, product_id, n=1, idempotency_key=f"k-{i}")
                await s.commit()
                return True
            except InsufficientStockError:
                return False

    results = await asyncio.gather(*(one_request(i) for i in range(N)))
    assert sum(results) == M
    assert await _reserved(factory, product_id) == M  # ассерт и на БД
    await _truncate_all(engine)
    await engine.dispose()
```

## API-клиент без сети

```python
from httpx import ASGITransport, AsyncClient


@pytest.fixture()
async def client(session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_session] = lambda: session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
```

## Правила

- `asyncio_mode = "auto"` уже в pyproject — декоратор `@pytest.mark.asyncio` не нужен.
- Никаких `time.sleep`/`asyncio.sleep` для синхронизации — только `gather`/события.
- TTL-тесты — инъекцией времени (clock-зависимость в сервисе), не ожиданием.
- Каждый тест независим от порядка запуска.
