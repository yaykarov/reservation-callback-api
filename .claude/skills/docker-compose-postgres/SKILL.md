---
name: docker-compose-postgres
description: docker-compose layout for this project - postgres with healthcheck, one-shot migrate service, api depending on completed migrations, env wiring, safe volume handling. Apply when writing or changing docker-compose.yml, Dockerfile, or debugging container startup order.
---

# docker-compose-postgres

**Когда применять:** compose/Dockerfile, порядок старта сервисов, «БД ещё не готова».

## Эталонный docker-compose.yml

```yaml
services:
  postgres:
    image: postgres:16-alpine
    env_file: .env
    ports:
      - "127.0.0.1:5439:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB"]
      interval: 2s
      timeout: 3s
      retries: 15

  migrate:
    build: .
    command: alembic upgrade head
    env_file: .env
    environment:
      DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
    depends_on:
      postgres:
        condition: service_healthy
    restart: "no"

  api:
    build: .
    env_file: .env
    environment:
      DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
    ports:
      - "8000:8000"
    depends_on:
      migrate:
        condition: service_completed_successfully

volumes:
  pgdata:
```

Ключевые моменты:
- `migrate` — one-shot: `restart: "no"` + `service_completed_successfully` у api —
  приложение никогда не стартует на непрокатанной схеме и само миграции не гоняет;
- healthcheck обязателен: `depends_on` без condition ждёт только старт контейнера, не БД;
- `$$` в healthcheck — экранирование, чтобы переменную раскрыл контейнер, а не compose;
- внутри сети хост БД — `postgres`, снаружи — `localhost` (отсюда два DATABASE_URL);
- порт postgres — только на 127.0.0.1.

## Правила

- `docker compose down -v` — НИКОГДА (сносит том с данными; заблокировано хуком).
  Пересоздать чистую БД осознанно: `docker compose down && docker volume rm <proj>_pgdata`
  руками, вне агента.
- Проверка синтаксиса: `docker compose config -q`.
- Ожидание готовности: `docker compose up -d --wait` (используется в `make up`).
- Секреты в yaml не хардкодить — только `env_file`/`${VAR}`.
