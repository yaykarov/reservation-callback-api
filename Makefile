.PHONY: up down test cov lint migrate migrate-down migrate-reset

up:
	docker compose up -d --wait

down:
	docker compose down

test:
	pytest -q

cov:
	pytest --cov=app --cov-report=term-missing --cov-fail-under=85

lint:
	ruff format --check .
	ruff check .
	mypy app

migrate:
	alembic upgrade head

# Откат на одну ревизию. Только локальная БД (гейт require_local_db.py).
migrate-down:
	@python3 scripts/require_local_db.py
	ALLOW_DOWNGRADE=1 alembic downgrade -1

# Полный откат схемы (downgrade base). Только локальная БД + явное подтверждение.
migrate-reset:
	@python3 scripts/require_local_db.py
	@printf 'ВНИМАНИЕ: полный откат схемы (alembic downgrade base). Введи "yes" для продолжения: '; \
	read ans; [ "$$ans" = "yes" ] || { echo "отменено" >&2; exit 1; }
	ALLOW_DOWNGRADE=1 alembic downgrade base
