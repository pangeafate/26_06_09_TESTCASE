# HelixPay — one-command run (local) and the contract the grader runs.
# Targets: up | ingest | demo | test | fmt   (HELIXPAY_BUILD_SPEC.md §5, §9)
#
# Requires a .env (copy from .env.example). Secrets only ever live in .env.

COMPOSE := docker compose
APP_RUN := $(COMPOSE) run --rm app

# The committed full-corpus snapshot — the canonical state the live instance serves
# (44 docs, 2347 claims, 67 contradictions). `make run` restores this at $0, no API keys.
SNAPSHOT := workspace/snapshots/helixpay_full-67-20260612.dump

.PHONY: run _env up restore ingest ingest-record replay recompute demo test fmt down logs ps

## run: ONE command from a fresh clone — the full 44-doc ontology at $0, no API keys.
## Bootstraps .env from the template if absent, brings up db+app, applies schema, then
## restores the committed full-corpus snapshot (the same dump→restore path prod uses).
## Fully key-free and $0 — no LLM, no embeddings. Only live `ask`/synthesis needs a real
## ANTHROPIC_API_KEY. (To re-run the genuine pipeline instead, see `make replay`.)
run: _env up restore
	@echo ""
	@echo "HelixPay is up — full ontology restored (zero API spend, no LLM): 44 docs, 2347 claims, 67 contradictions."
	@echo "  REST: http://127.0.0.1:8000      (POST /ask {\"question\": \"...\"} — needs a real ANTHROPIC_API_KEY)"
	@echo "  MCP:  http://127.0.0.1:8000/mcp   (streamable-HTTP, 12 tools)"
	@echo "  Inspect: docker compose exec db psql -U postgres -d helixpay -c 'select count(*) from claims;'"

## _env: create .env from the template if missing (restore/replay need no real secrets)
_env:
	@test -f .env || { cp .env.example .env && echo "created .env from .env.example (restore needs no real keys)"; }

## restore: load the committed full-corpus snapshot into the running db — $0, no API keys,
## no LLM. The same pg_dump→pg_restore mechanism prod uses (scripts/prod_seed.sh). Requires
## `make up` first (the migration creates the pgvector extension the dump's columns need).
restore:
	$(COMPOSE) exec -T db pg_restore --clean --if-exists --no-owner --no-acl -U postgres -d helixpay < $(SNAPSHOT)
	@echo "restored $(SNAPSHOT)"

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
## ingest: idempotent ingestion over the corpus (root 'data' — matches the canonical
## source_uri form in the replay cache and the live store; './data' would mismatch the key).
ingest:
	$(APP_RUN) helixpay ingest data

## ingest-record: the one PAID extraction over the corpus. Persists claims AND writes the
## replay cache to ./.replay-cache (host-mounted so `replay` reuses it). Tier-1 cost.
ingest-record:
	$(COMPOSE) run --rm -v "$(PWD)/.replay-cache:/app/.replay-cache" app \
		python -m helixpay.ingest.replay record data --cache-dir ./.replay-cache

## replay: re-run resolve→canonicalize→persist→contradict from the cache with ZERO API
## calls (no LLM, no embeddings). Needs the committed cache (or a prior `ingest-record`); run
## `up` first to apply seeds/vocab. The cache key is the source_uri, so the root MUST be
## 'data' (not './data') to match the recorded keys. A prompt/chunking/content change re-records.
replay:
	$(COMPOSE) run --rm -v "$(PWD)/.replay-cache:/app/.replay-cache" app \
		python -m helixpay.ingest.replay replay data --cache-dir ./.replay-cache

## recompute: deterministic, $0 contradiction precision sweep (clear-then-rewrite, no LLM).
## Mounts scripts/ (excluded from the image) so the canonical post-ingest sweep is runnable.
## The live instance additionally runs the cached LLM adjudication sweep (see SOLUTION.md §3).
recompute:
	$(COMPOSE) run --rm -v "$(PWD)/scripts:/app/scripts" app python scripts/recompute_contradictions.py

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
