# HelixPay — one-command run (local) and the contract the grader runs.
# Targets: up | ingest | demo | test | fmt   (HELIXPAY_BUILD_SPEC.md §5, §9)
#
# Requires a .env (copy from .env.example). Secrets only ever live in .env.

COMPOSE := docker compose
APP_RUN := $(COMPOSE) run --rm app

.PHONY: up ingest ingest-record replay demo test fmt down logs ps

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

## ingest-record: the one PAID extraction over ./data. Persists claims AND writes the
## replay cache to ./.replay-cache (host-mounted so `replay` reuses it). Tier-1 cost.
ingest-record:
	$(COMPOSE) run --rm -v "$(PWD)/.replay-cache:/app/.replay-cache" app \
		python -m helixpay.ingest.replay record ./data --cache-dir ./.replay-cache

## replay: re-run resolve→canonicalize→persist→contradict from the cache with ZERO API
## calls (no LLM, no embeddings). Needs a prior `ingest-record`; run `up` first to apply
## new seeds/vocab. A prompt/chunking/document-content change requires a fresh record.
replay:
	$(COMPOSE) run --rm -v "$(PWD)/.replay-cache:/app/.replay-cache" app \
		python -m helixpay.ingest.replay replay ./data --cache-dir ./.replay-cache

## demo: run the eval harness (Agent 6) against the running app. Runs as a module
## (`-m eval.run`) so `eval` is importable from /app, and mounts the host `test/`
## tree (excluded from the image) so the golden ground-truth is available.
demo:
	$(COMPOSE) run --rm -v "$(PWD)/test:/app/test" app python -m eval.run

## audit: read-only extraction-quality audit over the configured DB (no LLM/Voyage,
## read-only session — never mutates). Advisory: prints provenance/grounding/resolution
## integrity, planted traps, and a suspicious-oversampled sample. Point DATABASE_URL at
## the full-corpus store to audit it; add `--strict` to exit 1 on any ERROR/failed trap.
audit:
	$(APP_RUN) python -m helixpay.audit

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
