.PHONY: config up down lint test test-common

config:
	docker compose config

up:
	docker compose up --build

down:
	docker compose down

test-common:
	cd packages/rag-common && uv run pytest

lint:
	cd packages/rag-common && uv run ruff check .
	cd packages/rag-common && uv run ruff format --check .
	@if [ -f frontend/package.json ]; then npm --prefix frontend run lint --if-present; fi

test: test-common
	@if [ -f frontend/package.json ]; then npm test --prefix frontend; fi
