"""Ретрай транзакции при сбоях сериализации/дедлоках PostgreSQL.

Ретраится ЦЕЛАЯ транзакция: `operation` обязан сам открыть сессию, выполнить
use-case и закоммитить (commit — в сервисном слое). Ретраить внутри уже
abort-нутой транзакции бессмысленно — PostgreSQL отвергнет любые команды в ней.
"""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable

from asyncpg.exceptions import DeadlockDetectedError, SerializationError
from sqlalchemy.exc import DBAPIError

logger = logging.getLogger(__name__)

#: 40001 serialization_failure, 40P01 deadlock_detected
RETRYABLE_SQLSTATES: frozenset[str] = frozenset({"40001", "40P01"})

_RETRYABLE_PG_ERRORS = (SerializationError, DeadlockDetectedError)


def _sqlstate(exc: BaseException) -> str | None:
    # у asyncpg-исключений код в .sqlstate, у DBAPI-обёрток встречается .pgcode
    state = getattr(exc, "sqlstate", None) or getattr(exc, "pgcode", None)
    return state if isinstance(state, str) else None


def is_retryable_error(exc: BaseException) -> bool:
    """Ошибка сериализации (40001) или дедлок (40P01) — в т.ч. внутри DBAPIError.

    SQLAlchemy заворачивает ошибки asyncpg в sqlalchemy.exc.DBAPIError; исходное
    исключение лежит в .orig (и дальше в .orig.__cause__ у asyncpg-адаптера),
    поэтому проверяем всю цепочку и по типам, и по SQLSTATE.
    """
    if isinstance(exc, _RETRYABLE_PG_ERRORS) or _sqlstate(exc) in RETRYABLE_SQLSTATES:
        return True
    if isinstance(exc, DBAPIError):
        orig: BaseException | None = exc.orig
        while orig is not None:
            if isinstance(orig, _RETRYABLE_PG_ERRORS) or _sqlstate(orig) in RETRYABLE_SQLSTATES:
                return True
            orig = orig.__cause__
    return False


async def retry_transaction[T](
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 0.05,
    max_delay: float = 1.0,
) -> T:
    """Выполнить `operation` (целую транзакцию) с ретраем на 40001/40P01.

    3 попытки по умолчанию, экспоненциальная задержка с джиттером.
    Повтор безопасен ТОЛЬКО если operation идемпотентна на уровне транзакции:
    упавшая попытка откатывается PostgreSQL целиком, следующая начинается
    с чистого состояния и новой сессии.
    """
    for attempt in range(1, attempts + 1):
        try:
            return await operation()
        except Exception as exc:
            if not is_retryable_error(exc) or attempt == attempts:
                raise
            delay = min(max_delay, base_delay * 2 ** (attempt - 1))
            delay *= 0.5 + random.random()  # noqa: S311 — джиттер, не криптография
            logger.warning(
                "retryable DB conflict, retrying transaction",
                extra={
                    "attempt": attempt,
                    "max_attempts": attempts,
                    "delay_seconds": round(delay, 3),
                    "error": type(exc).__name__,
                },
            )
            await asyncio.sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover
