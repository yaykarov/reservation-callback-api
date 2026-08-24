---
name: alembic-async
description: Alembic with async SQLAlchemy - env.py via async_engine_from_config + run_sync, naming conventions for stable autogenerate, migration workflow rules. Apply when generating, reviewing, or debugging migrations.
---

# alembic-async

**Когда применять:** генерация/ревью миграций, проблемы с `alembic current`/`upgrade`.

## Устройство (уже в репозитории)

`migrations/env.py` — async-вариант: `async_engine_from_config` + `connection.run_sync(do_run_migrations)`; `DATABASE_URL` из окружения перекрывает `alembic.ini`; `target_metadata = Base.metadata` из `app.models`.

## Naming convention — обязательна для стабильного autogenerate

```python
# app/models/base.py
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
```

Без имён констрейнтов autogenerate не сможет их дропать, а диффы будут нестабильными.

## Рабочий цикл

```bash
alembic revision --autogenerate -m "add reservations table"
# 1) прочитать сгенерированный файл глазами (enum, server_default, CHECK autogenerate видит плохо)
# 2) прогнать на чистой БД:
alembic upgrade head
alembic current
```

## Правила

- Существующие файлы в `migrations/versions/` НЕ правятся (защищено хуком) — только новая ревизия.
- `alembic downgrade` в этом проекте не используется (заблокирован хуком); `downgrade()` в ревизии всё равно пиши корректным — это документация обратной операции.
- CHECK-констрейнты autogenerate часто НЕ видит — добавляй `op.create_check_constraint` руками и проверяй, что ревизия не пустая там, где не должна быть.
- Данные-миграции (backfill) — отдельной ревизией от DDL, идемпотентными UPDATE.
- Один логический блок изменений = одна ревизия; не смешивай несвязанные таблицы.
