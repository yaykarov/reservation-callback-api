"""Юнит-тесты ретрая (без БД)."""

import pytest
from asyncpg.exceptions import DeadlockDetectedError, SerializationError
from sqlalchemy.exc import DBAPIError

from app.core.retry import is_retryable_error, retry_transaction


class _AdapterError(Exception):
    """Имитация обёртки asyncpg-адаптера SQLAlchemy: sqlstate на промежуточном звене."""

    def __init__(self, sqlstate: str | None = None) -> None:
        super().__init__("adapter")
        self.sqlstate = sqlstate


def _dbapi(orig: BaseException) -> DBAPIError:
    return DBAPIError("UPDATE stock ...", None, orig)


def test_direct_asyncpg_errors_are_retryable() -> None:
    assert is_retryable_error(SerializationError("40001")) is True
    assert is_retryable_error(DeadlockDetectedError("40P01")) is True


def test_dbapi_wrapped_orig_and_cause_chain() -> None:
    assert is_retryable_error(_dbapi(SerializationError("x"))) is True
    assert is_retryable_error(_dbapi(_AdapterError("40P01"))) is True
    wrapper = _AdapterError()
    wrapper.__cause__ = DeadlockDetectedError("boom")
    assert is_retryable_error(_dbapi(wrapper)) is True


def test_non_retryable_errors() -> None:
    assert is_retryable_error(ValueError("nope")) is False
    assert is_retryable_error(_dbapi(_AdapterError("23505"))) is False  # unique violation
    assert is_retryable_error(_dbapi(_AdapterError(None))) is False


async def test_retry_transaction_retries_and_succeeds() -> None:
    attempts = 0

    async def op() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise SerializationError("conflict")
        return "ok"

    assert await retry_transaction(op, base_delay=0.001) == "ok"
    assert attempts == 3


async def test_retry_transaction_gives_up_after_attempts() -> None:
    attempts = 0

    async def op() -> None:
        nonlocal attempts
        attempts += 1
        raise DeadlockDetectedError("always")

    with pytest.raises(DeadlockDetectedError):
        await retry_transaction(op, attempts=3, base_delay=0.001)
    assert attempts == 3


async def test_retry_transaction_does_not_retry_foreign_errors() -> None:
    attempts = 0

    async def op() -> None:
        nonlocal attempts
        attempts += 1
        raise ValueError("domain bug")

    with pytest.raises(ValueError, match="domain bug"):
        await retry_transaction(op, base_delay=0.001)
    assert attempts == 1
