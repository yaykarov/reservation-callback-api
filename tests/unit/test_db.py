"""Юнит-тесты ленивых синглтонов app/core/db.py (без обращений к БД:
соединение открывается только при первом запросе, а его здесь нет)."""

from app.core import db


async def test_engine_and_factory_are_lazy_singletons() -> None:
    await db.dispose_engine()
    engine = db.get_engine()
    assert db.get_engine() is engine
    factory = db.get_session_factory()
    assert db.get_session_factory() is factory

    agen = db.get_session()
    session = await anext(agen)
    assert session.bind is engine
    await agen.aclose()

    await db.dispose_engine()
    assert db.get_engine() is not engine
    await db.dispose_engine()
