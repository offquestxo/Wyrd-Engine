# wyrd.exe story engine. Servers bind to 127.0.0.1 only.
.PHONY: setup dev api web test test-live lint typecheck check-providers check-models

setup:
	uv sync
	cd apps/web && pnpm install
	@if [ ! -f .env ]; then cp .env.example .env && echo "Created .env from .env.example — add your API keys."; fi
	uv run python -m apps.api.db.migrate

dev:
	@trap 'kill 0' INT TERM EXIT; \
	uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir apps/api & \
	(cd apps/web && pnpm dev) & \
	wait

api:
	uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir apps/api

web:
	cd apps/web && pnpm dev

lint:
	uv run ruff check .

typecheck:
	uv run mypy

test: lint typecheck
	uv run pytest
	cd apps/web && pnpm typecheck && pnpm lint

# Hits real APIs (network). Keyed sources are skipped when their key is missing.
test-live:
	uv run pytest -m live -v

check-providers:
	uv run python -m apps.api.providers.check

# Compare configured model IDs with each provider's live model list.
check-models:
	uv run python -m apps.api.providers.check --models
