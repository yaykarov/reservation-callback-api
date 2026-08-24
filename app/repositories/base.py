"""Базовый репозиторий.

Правило слоя: репозиторий НЕ владеет транзакцией. session.commit()/rollback()
здесь запрещены — транзакцией управляет сервисный слой (один commit на
HTTP-запрос). Репозиторию доступен только flush(): отправить накопленные
изменения в БД в рамках открытой транзакции (например, получить server_default
PK), не завершая её.
"""

from sqlalchemy.ext.asyncio import AsyncSession


class BaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def flush(self) -> None:
        await self._session.flush()
