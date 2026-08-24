"""Engine и фабрика сессий SQLAlchemy 2.0 async (asyncpg).

Транзакция = один HTTP-запрос: сессия выдаётся через get_session (DI),
commit() делает ТОЛЬКО сервисный слой, репозитории максимум flush().
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Единственный engine процесса; создаётся лениво (не при импорте модуля)."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            echo=settings.db_echo,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,  # инвариант проекта: атрибуты доступны после commit
            autoflush=False,
        )
    return _session_factory


async def dispose_engine() -> None:
    """Закрыть пул соединений (lifespan shutdown приложения/воркера)."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI-dependency: сессия на запрос. Commit здесь НЕ делается — это дело сервиса."""
    async with get_session_factory()() as session:
        yield session
