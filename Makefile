# wyrd.exe story engine. Servers bind to 127.0.0.1 only.
.PHONY: setup dev api web test test-live lint typecheck check-providers check-models

# Ports. `make dev` moves the web app to the next free port if 3000 is taken by another app;
# set WEB_PORT (e.g. `make dev WEB_PORT=3001`) to require a specific port instead.
API_PORT ?= 8000
WEB_PORT_DEFAULT := 3000
WEB_PORT ?=

setup:
	uv sync
	cd apps/web && pnpm install
	@if [ ! -f .env ]; then cp .env.example .env && echo "Created .env from .env.example — add your API keys."; fi
	uv run python -m apps.api.db.migrate

dev:
	@port=$$(python3 scripts/pick_port.py $(or $(WEB_PORT),$(WEB_PORT_DEFAULT)) $(if $(WEB_PORT),--strict)) || exit 1; \
	echo "wyrd.exe: API http://127.0.0.1:$(API_PORT) · web http://127.0.0.1:$$port"; \
	trap 'kill 0' INT TERM EXIT; \
	uv run uvicorn apps.api.main:app --host 127.0.0.1 --port $(API_PORT) --reload --reload-dir apps/api --timeout-graceful-shutdown 3 & \
	(cd apps/web && WYRD_API_URL=http://127.0.0.1:$(API_PORT) pnpm exec next dev --hostname 127.0.0.1 --port $$port) & \
	wait

api:
	uv run uvicorn apps.api.main:app --host 127.0.0.1 --port $(API_PORT) --reload --reload-dir apps/api --timeout-graceful-shutdown 3

web:
	@port=$$(python3 scripts/pick_port.py $(or $(WEB_PORT),$(WEB_PORT_DEFAULT)) $(if $(WEB_PORT),--strict)) || exit 1; \
	cd apps/web && WYRD_API_URL=http://127.0.0.1:$(API_PORT) pnpm exec next dev --hostname 127.0.0.1 --port $$port

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
