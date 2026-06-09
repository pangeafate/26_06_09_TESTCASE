# Agent 5 — Infra & deploy (SP_006, FOUNDATIONAL)

You are Agent 5. You make the whole thing run with one command and deploy it live. You
own Docker, compose, the Makefile, and the VM deploy behind the existing TLS proxy.
Deploy is Foundational (high blast radius) — run the full lifecycle. Read `CLAUDE.md`,
`AGENTS.md`, `HELIXPAY_BUILD_SPEC.md` §5 (Agent 5) + §9, and `fanout/README.md`.

## Setup
- Worktree: `git worktree add .claude/worktrees/SP_006 -b sprint/SP_006-infra main`
- Sprint plan `workspace/sprints/SP_006_infra.md` — `tier: Foundational`,
  `isolation: git-worktree`,
  `touches_paths: [deploy/**, Dockerfile, docker-compose.yml, Makefile, .env.example]`.

## Owns (write only here)
- `deploy/**` (vhost config + deploy scripts), `Dockerfile`, `docker-compose.yml`,
  `Makefile`, `.env.example`.

## Frozen entrypoints you build on (don't change these names)
- Migrate: `python -m helixpay.db.migrate`   · Seed: `python -m helixpay.seed.run_seed`
- Ingest: `helixpay ingest ./data` (CLI, Agent 4) → calls `helixpay.ingest.pipeline.run`
- App (ASGI): confirm with Agent 4 — `helixpay.api.app:app`, served on `127.0.0.1:8000`,
  MCP under `/mcp`.
- Env: `DATABASE_URL`, `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY` (secrets from env only).

## Build
- **`docker-compose.yml`** — two services:
  - `db`: `pgvector/pgvector:pg16`, `POSTGRES_DB=helixpay`, volume `pgdata`, healthcheck
    `pg_isready -U postgres`. **Never exposed** publicly.
  - `app`: builds the Dockerfile, `env_file: .env`, `depends_on db healthy`, ports
    `127.0.0.1:8000:8000` (loopback only — the proxy reaches it).
- **`Dockerfile`** — Python 3.12, `uv`, install the package; entrypoint runs the ASGI
  app via uvicorn. Multi-stage if it helps image size.
- **`Makefile`** — the contract the grader runs:
  - `make up` → `docker compose up -d` (+ wait for db healthy + run migrate + seed)
  - `make ingest` → `docker compose run --rm app helixpay ingest ./data`
  - `make demo` → invokes Agent 6's harness (`eval/run.py`) against the running app
  - `make test` → `uv run pytest test` (+ Agent 6's two-level autotest)
  - `make fmt` → formatter
- **`.env.example`** — the three env vars, no real values.
- **vhost (`deploy/`)** — reverse-proxy config fronting `127.0.0.1:8000` (Caddy:
  `helixpay.<domain> { reverse_proxy 127.0.0.1:8000 }`, or nginx `location / { proxy_pass … }`).
  MCP ends up at `https://helixpay.<domain>/mcp`.

## Deploy target
- Droplet **`138.197.187.49`** (Docker + existing TLS reverse proxy + DNS already
  pointing). `.env` on the box (chmod 600, **not committed**). Ingest once after
  `docker compose up -d`. Idempotent, so re-running is the moving-target demo.
- CI/CD-first (Rule 11): deploy through version control; direct host access is
  emergency-only or read-only. After pushing, watch CI/deploy until verified.

## Conventions
- DB never exposed; app on loopback behind the proxy. Secrets only via `.env` on the
  box (never in git). One compose file serves both local (`localhost:8000`) and prod
  (proxy → loopback).

## Done when
- `make up && make ingest && make demo` is green **from a fresh clone** with only env
  vars set. The deploy is reachable at the domain; `/health` green; `/mcp` reachable
  over streamable-HTTP. CI on the pushed commit is green.

## Hand-off
Report: the exact `make` targets, the app ASGI path you wired, the vhost used, and the
live URL (for `SOLUTION.md`). Flag any entrypoint name that differed from the frozen set.
