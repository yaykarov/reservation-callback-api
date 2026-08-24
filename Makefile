.PHONY: up down test cov lint migrate

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
