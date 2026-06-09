# HelixPay — one-command run (local) and the contract the grader runs.
# Targets: up | ingest | demo | test | fmt   (HELIXPAY_BUILD_SPEC.md §5, §9)
#
# Requires a .env (copy from .env.example). Secrets only ever live in .env.

COMPOSE := docker compose
APP_RUN := $(COMPOSE) run --rm app

.PHONY: up ingest demo test fmt down logs ps

## up: build + start db & app, wait for db health, then migrate + seed (idempotent)
up:
	$(COMPOSE) up -d --build
	@echo "waiting for db to become healthy..."
	@n=0; until [ "$$($(COMPOSE) ps db --format '{{.Health}}')" = "healthy" ]; do \
		n=$$((n+1)); \
		if [ $$n -gt 60 ]; then echo " db did not become healthy in 60s" >&2; exit 1; fi; \
		printf '.'; sleep 1; \
	done; echo " healthy"
	$(APP_RUN) python -m helixpay.db.migrate
	$(APP_RUN) python -m helixpay.seed.run_seed

## ingest: idempotent ingestion over ./data inside the app container
ingest:
	$(APP_RUN) helixpay ingest ./data

## demo: run the eval harness (Agent 6) against the running app
demo:
	$(APP_RUN) python eval/run.py

## test: the product test suite (unit + DB-gated integration)
test:
	uv run pytest test

## fmt: format the code (ruff, fetched ephemerally via uvx — no project dep added)
fmt:
	uvx ruff format helixpay test eval deploy

## down: stop and remove containers (the pgdata volume is kept)
down:
	$(COMPOSE) down

## logs: follow the app logs
logs:
	$(COMPOSE) logs -f app

## ps: show container + health status
ps:
	$(COMPOSE) ps
