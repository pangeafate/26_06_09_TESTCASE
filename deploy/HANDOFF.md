# SP_006 Infra & Deploy — Delivery / Hand-off (Agent 5)

Branch `sprint/SP_006-infra` · worktree `.claude/worktrees/SP_006`. Owns only
`deploy/**`, `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `Makefile`,
`.env.example`. No other agent's files touched.

## What shipped

| Artifact | Summary |
|---|---|
| `docker-compose.yml` | `db` (pgvector pg16, **no host ports** → never publicly exposed, `pg_isready` healthcheck, `pgdata` volume) + `app` (builds Dockerfile, `env_file: .env`, `depends_on db service_healthy`, ports `127.0.0.1:8000:8000` loopback only). One file serves local + prod. |
| `Dockerfile` | `python:3.12-slim` + `uv`, `uv pip install --system .`, runs as non-root `appuser` (uid 10001), `CMD uvicorn helixpay.api.app:app --host 0.0.0.0 --port 8000`. |
| `.dockerignore` | Ships only `helixpay/`, `data/`, `pyproject.toml` (+ `prompts/`, `eval/` at integration). Excludes venv/git/caches/tests/secrets/governance dirs. |
| `Makefile` | `up | ingest | demo | test | fmt` (+ `down`, `logs`, `ps`). |
| `.env.example` | `POSTGRES_PASSWORD`, `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`, `DATABASE_URL` — placeholders only. |
| `deploy/Caddyfile`, `deploy/nginx.conf` | reverse-proxy vhost → `127.0.0.1:8000`; MCP at `/mcp`. |
| `deploy/deploy.sh` | idempotent live-VM runbook (pull → build → health → migrate → seed → ingest → `/health`). |
| `deploy/README.md`, `deploy/tests/test_infra_contract.py` | runbook + 12 TDD invariant tests. |

## Make targets (the grader contract)

- `make up` → `docker compose up -d --build`, wait (bounded 60s) for db healthy, then
  `python -m helixpay.db.migrate` + `python -m helixpay.seed.run_seed` in the app container.
- `make ingest` → `docker compose run --rm app helixpay ingest ./data`.
- `make demo` → `docker compose run --rm app python eval/run.py`.
- `make test` → `uv run pytest test`.
- `make fmt` → `uvx ruff format helixpay test eval deploy` (ruff fetched ephemerally — no pyproject dep added).

Infra contract tests run with `uv run pytest deploy/tests` (kept out of `test/` so
`make test` stays the pure product suite).

## ASGI path wired

`helixpay.api.app:app`, served on `127.0.0.1:8000`, MCP under `/mcp` (streamable-HTTP).
Matches the frozen entrypoint in `AGENT_5_infra.md`. **No entrypoint name differed** from
the frozen set (migrate/seed via `python -m …`; ingest via `helixpay ingest ./data`).

## Vhost / live URL plan

Two snippets provided (use whichever proxy is on the droplet). Replace
`helixpay.example.com` with the real subdomain pointed at `138.197.187.49`; if none is
wired yet, `helixpay.138.197.187.49.sslip.io` gives an instant Caddy-TLS URL. Live MCP
lands at `https://<subdomain>/mcp`. **For `SOLUTION.md`:** the live URL is set when the
orchestrator runs the deploy on the box (see below).

## Verified in isolation

- `docker compose config` renders: db has no ports; app `host_ip 127.0.0.1` target 8000;
  app `depends_on db service_healthy`.
- `docker compose build app` succeeds; image runs as uid 10001; `import helixpay` works;
  `data/` present.
- `uv run pytest deploy/tests` → **12 passed**.

## REQUIRED at integration (cross-agent — I cannot do these from my slice)

1. **`pyproject.toml` runtime deps.** The image installs `.`; it needs the parallel
   agents' runtime deps consolidated into `[project.dependencies]`:
   `uvicorn[standard]`, `fastapi`, `mcp` (or the MCP SDK pkg), `anthropic`, `voyageai`
   (+ whatever Agents 1–4 declared). Without them the container starts but the app
   import fails. (Confirmed missing in the isolated image — expected.)
2. **`helixpay` console script.** `make ingest`/deploy use `helixpay ingest ./data`. Add
   to `pyproject.toml`: `[project.scripts]` → `helixpay = "helixpay.cli:main"` (Agent 4's
   `cli.py`). I do not edit the shared `pyproject.toml`. *Note:* the gate's
   `.claude/commands/ingest.md` references `python -m helixpay.ingest ./data` instead —
   reconcile to one canonical form (console script preferred; or add
   `helixpay/ingest/__main__.py`).
3. **`make demo` harness contract (Agent 6).** Runs `eval/run.py` in a one-off app
   container (has DB + keys). If the harness talks HTTP, target the running `app` service
   (`http://app:8000`) or call the library in-process.
4. **Live deploy (orchestrator, with go-ahead).** Not run autonomously — needs real
   secrets on the box + the integrated app, and is high-blast-radius/outward-facing
   (Rule 11). Procedure: put `.env` on the box (chmod 600), drop the vhost into the
   existing proxy, run `./deploy/deploy.sh`, confirm `/health` + `/mcp`, watch CI green.

## Gotchas for CLAUDE.md (orchestrator appends — I don't edit CLAUDE.md)

- Compose `DATABASE_URL` must use host `db` (the service name), not `127.0.0.1` — a local
  dev `.env` reused verbatim breaks `make up`. `.env.example` documents both forms.
- `make fmt` uses `uvx ruff` (ephemeral) so no formatter dependency is added to the
  pinned set.
- The db is intentionally unpublished; reach it only via the app container or
  `docker compose exec db psql`.
