---
sprint_id: SP_006
tier: Foundational
features: [infra-compose, infra-dockerfile, infra-makefile, infra-deploy-vhost]
user_stories: []
schema_touched: false
structure_touched: true
status: Complete
isolation: git-worktree
branch: sprint/SP_006-infra
worktree: .claude/worktrees/SP_006
agent_owner: "Agent 5 (infra & deploy)"
touches_paths:
  - deploy/**
  - Dockerfile
  - .dockerignore
  - docker-compose.yml
  - Makefile
  - .env.example
fix_type: ""
touches_checklist_items: [infra-compose, infra-dockerfile, infra-dockerignore, infra-makefile, infra-envexample, infra-vhost, infra-deploy-runbook]
---

# SP_006: Infra & Deploy — one-command run + live VM deploy

## Sprint Goal

Make the HelixPay ontology run with **one command from a fresh clone** and deploy it
**live** behind the existing TLS reverse proxy. Deliver `docker-compose.yml` (app +
pgvector), a `Dockerfile`, the `Makefile` contract the grader runs (`up | ingest |
demo | test | fmt`), `.env.example`, and `deploy/**` (reverse-proxy vhost + an
idempotent deploy runbook). This is `HELIXPAY_BUILD_SPEC.md` §5 (Agent 5) + §9. Tier
is **Foundational** — high blast radius (deploy), so the full lifecycle applies.

## Current State

- Phase 0 gate frozen on `main` (SP_001): `helixpay/` substrate — `contracts/**`,
  `db/` (`schema.sql`, `migrate.py`, `PostgresRepository`, `connection.py`),
  `config.py` (secrets from env only; `DATABASE_URL`, `ANTHROPIC_API_KEY`,
  `VOYAGE_API_KEY`), `seed/run_seed.py`.
- Frozen entrypoints I build on:
  - Migrate: `python -m helixpay.db.migrate`
  - Seed: `python -m helixpay.seed.run_seed`
  - Ingest (Agent 4 CLI, frozen): `helixpay ingest ./data` → `helixpay.ingest.pipeline.run`
  - App ASGI (Agent 4, frozen): `helixpay.api.app:app`, served on `127.0.0.1:8000`, MCP under `/mcp`
  - Demo harness (Agent 6): `eval/run.py`
- Build agents 1–4, 6 run in parallel worktrees; their modules (`helixpay/api/**`,
  `helixpay/cli.py`, `helixpay/ingest/**`, `eval/**`, `prompts/**`) **may not exist yet**
  in my worktree. I build the infra against the *frozen entrypoint names*, not their code.
- Toolchain present: Docker 28 + Compose v2, `uv` 0.8, Python 3.12/3.13.
- Deploy target: droplet `138.197.187.49` (Docker + existing TLS proxy + DNS pointing).

## Desired End State

- `make up && make ingest && make demo` is green from a fresh clone with only env vars set.
- `docker-compose.yml`: `db` (pgvector pg16, **never** publicly exposed, healthcheck,
  `pgdata` volume) + `app` (builds Dockerfile, `env_file: .env`, `depends_on: db healthy`,
  ports `127.0.0.1:8000:8000` loopback-only). One file serves local + prod.
- `Dockerfile`: Python 3.12 + `uv`, installs the package, default CMD runs the ASGI app
  via `uvicorn helixpay.api.app:app` on `0.0.0.0:8000`.
- `.env.example`: the three secrets + Postgres password, no real values.
- `deploy/`: a Caddy snippet and an nginx snippet (`reverse_proxy`/`proxy_pass` →
  `127.0.0.1:8000`, MCP ends at `/mcp`), an idempotent `deploy.sh` runbook, and a README.
- Secrets only via `.env` on the box (chmod 600, never committed). DB never exposed.

## What We're NOT Doing

- **Not editing `pyproject.toml`** — it is a shared, merge-handled file and is outside my
  `touches_paths`. The `helixpay` console script needs `[project.scripts] helixpay =
  "helixpay.cli:main"` (Agent 4 / orchestrator); flagged in the handoff, not added here.
- Not editing `CLAUDE.md`, contracts, meta-docs, or any other agent's module.
- **Not executing the live VM deploy autonomously.** It needs real secrets on the box and
  the integrated app (Agents 1–4 merged), and is high blast radius / outward-facing
  (Rule 11: CI/CD-first; direct host access is emergency-only). I deliver the artifacts +
  runbook; the orchestrator runs the deploy at integration with explicit go-ahead.
- Not building the eval harness, CLI, or API — those are owned by Agents 6/4.

## Technical Approach

1. **TDD first.** `deploy/tests/test_infra_contract.py` (under my `deploy/**` ownership)
   encodes the safety + contract invariants as assertions over the rendered
   `docker compose config`, the `Makefile`, the `Dockerfile`, and `.env.example`:
   - db has no `ports:` mapping reachable off-host (never publicly exposed);
   - app binds exactly `127.0.0.1:8000:8000` (loopback only);
   - db image is `pgvector/pgvector:pg16`, has a healthcheck, `pgdata` volume;
   - app `depends_on` db `service_healthy`, uses `env_file: .env`;
   - Makefile defines targets `up ingest demo test fmt`;
   - `.env.example` names the three env vars and carries **no real secret values**;
   - Dockerfile is Python 3.12, installs the package, CMD runs `uvicorn` on the frozen
     ASGI path `helixpay.api.app:app`.
   These run via `uv run pytest deploy/tests` (kept out of the product `test/` tree so
   `make test` stays the pure product suite; disjoint from every other agent).
2. **docker-compose.yml.** Two services as in §9. `db` reads `POSTGRES_PASSWORD` from
   `.env`; `POSTGRES_DB=helixpay`, `POSTGRES_USER=postgres` set on the service. `app`
   `env_file: .env` carries `DATABASE_URL` (host `db`), the two LLM keys. Loopback port
   binding lets the same file serve the grader's `localhost:8000` and the VM's proxy.
3. **Dockerfile.** `python:3.12-slim` + `uv` (copied from the official uv image), `COPY .`
   with a tight `.dockerignore`, `uv pip install --system .`, `EXPOSE 8000`, CMD uvicorn.
   `COPY .` (not per-dir) so the image builds whether or not sibling agents' dirs exist
   yet and picks up `prompts/`, `eval/`, `data/` at integration.
4. **Makefile.** `up` = compose up -d --build, wait for db healthy, migrate, seed.
   `ingest` = `docker compose run --rm app helixpay ingest ./data`. `demo` = run Agent 6's
   `eval/run.py` against the running app. `test` = `uv run pytest test`. `fmt` =
   `uvx ruff format` (ephemeral tool — no dependency added to the shared pyproject).
5. **deploy/.** `Caddyfile` + `nginx.conf` snippets (domain parametrized; the spec's
   live host is unspecified beyond the IP, so default to a documented placeholder and an
   `sslip.io` fallback that gets TLS with no DNS work), `deploy.sh` (idempotent: pull,
   compose up --build, migrate, seed, ingest once, health check), `deploy/README.md`.

## Files to Create/Modify

| Path | Action | Purpose |
|------|--------|---------|
| `docker-compose.yml` | Create | app + pgvector; db never exposed; app on loopback |
| `Dockerfile` | Create | Py3.12 + uv image; CMD uvicorn `helixpay.api.app:app` |
| `.dockerignore` | Create | keep the build context small + buildable in isolation |
| `Makefile` | Create | `up ingest demo test fmt` — the grader's contract |
| `.env.example` | Create | three secrets + POSTGRES_PASSWORD, no real values |
| `deploy/Caddyfile` | Create | `reverse_proxy 127.0.0.1:8000` vhost (MCP at /mcp) |
| `deploy/nginx.conf` | Create | nginx `proxy_pass` alternative |
| `deploy/deploy.sh` | Create | idempotent live-VM deploy runbook |
| `deploy/README.md` | Create | deploy procedure + which-proxy guidance |
| `deploy/tests/test_infra_contract.py` | Create | TDD: safety + contract invariants |

## Testing Strategy

- **TDD:** infra contract tests written first (red), artifacts make them green.
- `uv run pytest deploy/tests` — invariants over rendered compose/Makefile/Dockerfile/env.
- `docker compose config` — compose file parses and renders.
- `docker compose build app` — the image builds against the frozen substrate.
- Full `make up && make ingest && make demo` end-to-end is an **integration-time** check
  (needs Agents 1–4 merged); documented in the handoff with what I could/couldn't verify
  in isolation.

## Success Criteria

- Infra contract tests green; `docker compose config` valid; `app` image builds.
- db never publicly exposed; app reachable only on `127.0.0.1:8000`; secrets only via `.env`.
- Makefile exposes `up ingest demo test fmt` wired to the frozen entrypoints.
- vhost routes the subdomain → loopback; MCP resolves at `…/mcp`.
- Handoff names: the make targets, the ASGI path wired, the vhost, the live-URL plan, and
  every entrypoint that differed from the frozen set (+ the pyproject `[project.scripts]` flag).

## Doc Reconciliation Checklist

- [ ] Delivery report lists make targets, ASGI path, vhost, live-URL plan (for `SOLUTION.md`).
- [ ] Gotchas (compose DATABASE_URL host, `[project.scripts]` need, `uvx ruff` for fmt)
      handed to the orchestrator for CLAUDE.md / meta-doc reconciliation (I do not edit those).

## Review Log

### Pre-Implementation Review

- **Iteration 1** — *Reviewer: architect-review (plan-level, independent pass).* Severity: **HIGH** (1 HIGH, 2 MEDIUM, 0 CRITICAL). Files reviewed: `docker-compose.yml` (planned), `Makefile` (planned), `.env.example` (planned), `HELIXPAY_BUILD_SPEC.md` §9.
  - HIGH: **Compose `DATABASE_URL` host collision.** `helixpay.config` reads
    `DATABASE_URL` from env; a developer's `.env` from local dev points at
    `127.0.0.1:55432`, which is unreachable from inside the `app` container (must be
    `db:5432`). If `.env` is reused verbatim, `make up` migrate/seed fails. *Resolution:*
    `.env.example` documents the in-cluster URL (`…@db:5432/helixpay`) as the canonical
    value, and the password is sourced once via `POSTGRES_PASSWORD`; a "local vs compose"
    note prevents the footgun. Accepted into the plan.
  - MEDIUM: **`helixpay` console script may be unregistered.** `make ingest` calls the
    frozen `helixpay ingest ./data`; that console entry lives in the shared `pyproject.toml`
    (`[project.scripts]`), which I cannot edit. *Resolution:* keep the frozen grader-facing
    command, flag the `[project.scripts]` requirement to the orchestrator/Agent 4 in the
    handoff so it is present at integration.
  - MEDIUM: **`make fmt` has no formatter dependency.** No ruff/black in the pinned deps,
    and I can't add one to pyproject. *Resolution:* `uvx ruff format` runs ruff ephemerally
    without mutating the dependency set. Accepted.

- **Iteration 2** — *Reviewer: code-review (plan-blind on the build-spec invariants).* Severity: **MEDIUM** (0 CRITICAL, 0 HIGH, 2 MEDIUM — no blocking findings remain). Files reviewed: `docker-compose.yml` (planned), `Dockerfile` (planned), `deploy/**` (planned), `deploy/tests/test_infra_contract.py` (planned).
  - MEDIUM: **db port exposure regression risk.** The single highest-value safety invariant
    (db never reachable publicly) must be machine-checked, not just eyeballed. *Resolution:*
    the contract test asserts the rendered `db` service publishes no host port; this is the
    first test written (TDD red). Accepted.
  - MEDIUM: **Dockerfile build fragility in isolation.** Per-directory `COPY` of sibling
    agents' dirs (`prompts/`, `eval/`) would break the build in my worktree where they don't
    exist. *Resolution:* `COPY .` + `.dockerignore` builds in isolation and picks up those
    dirs at integration. Accepted.
  - Decision: **proceed to implementation.** 0 CRITICAL / 0 HIGH open; both MEDIUMs are
    resolved by design choices folded into the plan above.

### Post-Implementation Review

Plan-blind review over the built artifacts + tests (compose/Dockerfile/Makefile/
deploy/env), independent of the plan rationale. Evidence: `docker compose config`
renders (db has no ports, app `host_ip 127.0.0.1:8000`, `depends_on db
service_healthy`); `docker compose build app` succeeds; image runs as uid 10001 and
imports `helixpay`; `uv run pytest deploy/tests` → 12 passed.

- **Iteration 1** — *Reviewer: code-review (plan-blind, artifacts + tests).* Severity: **MEDIUM** (0 CRITICAL, 0 HIGH, 2 MEDIUM, 1 LOW). Files reviewed: `docker-compose.yml`, `Dockerfile`, `Makefile`, `.env.example`, `deploy/**`, `deploy/tests/test_infra_contract.py`.
  - MEDIUM: container ran as root → **fixed**: added a non-root `appuser` (uid 10001) `USER` directive; verified `id` reports uid 10001 and import still works.
  - MEDIUM: `make up` health-wait loop could hang forever if db never goes healthy → **fixed**: bounded the loop to 60s, exits non-zero on timeout.
  - LOW: image copied governance dirs (`practices/`, `validators/`, `scripts/`, `fanout/`) → **fixed**: extended `.dockerignore`; image now ships only `helixpay/`, `data/`, `pyproject.toml` (+ `prompts/`,`eval/` at integration).
- **Iteration 2** — *Reviewer: architect-review (plan-blind, deploy safety + integration seams).* Severity: **LOW** (0 CRITICAL, 0 HIGH, 0 MEDIUM, 2 LOW — non-blocking, handed off). Files reviewed: `docker-compose.yml`, `Dockerfile`, `Makefile`, `deploy/deploy.sh`.
  - Confirmed the safety invariants hold post-change: db unexposed, app loopback-only, secrets env-only, no secrets in the image. 0 blocking findings.
  - LOW (handoff, not fixable in my slice): the image's runtime needs `uvicorn[standard]`, `fastapi`, `mcp`, `anthropic`, `voyageai` — owned by Agents 2/3/4 and consolidated into `pyproject.toml` at merge; `helixpay` console script needs `[project.scripts]`. Both flagged in the delivery report.
  - LOW (handoff): `make demo` runs `eval/run.py` in a one-off app container (has DB + keys); if Agent 6's harness talks HTTP it should target the running `app` service or call the library in-process. Flagged for Agent 6.
  - Decision: **accept.** 0 CRITICAL / 0 HIGH; all MEDIUMs fixed; remaining LOWs are cross-agent integration items, not defects in this slice.
