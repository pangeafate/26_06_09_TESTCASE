---
sprint_id: SP_005
tier: Standard
features: [exposure-mcp, exposure-api, exposure-cli]
user_stories: []
schema_touched: false
structure_touched: true
status: In Progress
isolation: git-worktree
branch: sprint/SP_005-exposure
worktree: .claude/worktrees/SP_005
agent_owner: "Agent 4 (exposure)"
touches_paths:
  - helixpay/mcp/**
  - helixpay/api/**
  - helixpay/cli.py
  - test/unit/api/**
fix_type: ""
touches_checklist_items: [exposure-engine-protocol, exposure-mock-engine, exposure-mcp-server, exposure-fastapi, exposure-cli, exposure-tests]
---

# SP_005: Exposure — MCP + FastAPI + CLI (thin adapters over QueryEngine)

## Sprint Goal

Build the three **thin** remote/local surfaces over the frozen `QueryEngine` Protocol:

1. A **streamable-HTTP MCP server** (hard requirement — stdio is local-only and breaks
   the live-URL story; the consumer is an agent). Tools typed per object type:
   `ask`, `get_entity`, `get_org_chart`, `find_contradictions`, `get_sources`, `search`.
   Mounted at `/mcp`.
2. A **FastAPI** app: `POST /ask`, `GET /entity/{name}`, `GET /org-chart`,
   `GET /contradictions`, `GET /health` (green without LLM keys). Shares the one ASGI app
   with the MCP server so a single port (`127.0.0.1:8000`) serves both `/mcp` + REST.
3. A **CLI**: `helixpay ask "..."` (answer + citations + any contradiction), and
   `helixpay ingest ./data` (delegates to Agent 2's `helixpay.ingest.pipeline.run`,
   imported lazily so the rest of the CLI works before Agent 2 lands).

Adapters are thin pass-throughs: no business logic, no DB access, no raw SQL. All
reasoning is the `QueryEngine`'s job, dependency-injected so tests use a mock. I code
against the **frozen** Protocol and mock it until Agent 3 lands; swapping the mock for
Agent 3's real engine must require **no adapter change**.

## Current State

- Frozen substrate is on `main`: `helixpay/contracts/**` (models + `QueryEngine` Protocol
  with `ask`, `get_entity`, `get_org_chart`, `find_contradictions`), `helixpay/config.py`.
- No `helixpay/mcp/`, `helixpay/api/`, or `helixpay/cli.py` yet.
- `mcp`, `fastapi`, `uvicorn`, `httpx` are not installed in the venv — declared below.

## Desired End State

- MCP tools callable over HTTP (streamable-HTTP) against a mock engine; `/health` green
  without LLM keys; `helixpay ask "..."` answers via the mock.
- Swapping the mock for Agent 3's real `QueryEngine` requires no adapter change.
- `uv run pytest test/unit/api` green; `uv run mypy helixpay/mcp helixpay/api helixpay/cli.py`
  clean.

## Design Decisions

- **Engine surface.** The frozen `QueryEngine` Protocol has exactly four methods
  (`ask`, `get_entity`, `get_org_chart`, `find_contradictions`). The spec's MCP tool list
  additionally names `get_sources` and `search`, which are **retrieval** surfaces, not on
  the frozen Protocol. Resolution that respects "import, never redefine the frozen type"
  and "no adapter change on swap": define a local **extension** Protocol
  `ExposureEngine(QueryEngine, Protocol)` in `helixpay/api/engine.py` adding the two
  optional retrieval methods, and have the two extra MCP tools dispatch through a guarded
  helper that returns a structured "retrieval surface unavailable" payload if the live
  engine doesn't implement them. The four core tools call the guaranteed Protocol methods
  directly. This keeps the hard dependency on the 4-method Protocol while honoring the
  6-tool spec, and never breaks the core surface regardless of which engine is injected.
- **Single ASGI app, single port.** FastAPI app holds the REST routes; the FastMCP
  streamable-HTTP ASGI app is mounted at `/mcp`; the MCP session manager lifecycle is run
  from the FastAPI `lifespan`. One uvicorn entrypoint serves both. Frozen gate entrypoint
  for Agent 5: **`helixpay.api.app:app`** (uvicorn target).
- **Stateless streamable-HTTP** so the server is trivially horizontally deployable behind
  the proxy and testable with a plain httpx client (no session handshake to thread).
- **`/health` requires no secrets** — it never calls `load_config()` or the engine.
- **DI everywhere.** A module-level engine provider (`get_engine`) is overridable; tests
  inject a `MockQueryEngine`. Production wiring to Agent 3's engine is a one-line provider
  swap, not an adapter change.

## Implementation Plan (TDD — failing test first per slice)

1. `helixpay/api/engine.py` — `ExposureEngine` extension Protocol + `MockQueryEngine`
   (deterministic canned `AnswerBundle`/`EntityDetail`/`OrgNode`/`Contradiction`, plus
   `get_sources`/`search`) for tests and the default dev wiring.
2. `helixpay/api/app.py` — FastAPI app, Pydantic response models reusing contract types,
   REST routes, `/health`, DI provider, MCP mount + lifespan. Entrypoint `app`.
3. `helixpay/mcp/server.py` — FastMCP server, six tools as thin pass-throughs, the guarded
   dispatch for `get_sources`/`search`, `streamable_http_app()` exposed for mounting.
4. `helixpay/cli.py` — `argparse` CLI: `ask` (prints answer + citations + contradictions),
   `ingest` (lazy import of `helixpay.ingest.pipeline.run`).
5. `test/unit/api/**` — TestClient over the FastAPI app (REST + `/health`), httpx/TestClient
   MCP tool-call round-trips against the mock, CLI `ask` via the mock, mypy clean.

## Dependencies
> Declared here; orchestrator consolidates into `pyproject.toml` at merge (do NOT edit it
> in the worktree). Installed locally with `uv pip install` for the build.

- `fastapi` — REST app + Pydantic response models.
- `uvicorn` — ASGI server (the deploy entrypoint Agent 5 runs).
- `mcp` — the MCP Python SDK (FastMCP streamable-HTTP transport).
- `httpx` — test client for HTTP/MCP round-trips (dev).

## Technical Approach

Thin adapters over the frozen four-method `QueryEngine` Protocol, dependency-injected via a
`get_engine`/`set_engine` seam (default `MockQueryEngine`). One ASGI app (`create_app()`
factory; module-level `app` is the frozen `helixpay.api.app:app` entrypoint) serves REST and
a mounted FastMCP **streamable-HTTP** server at `/mcp`, with the single-use session manager
driven from the app lifespan. The two retrieval-only MCP tools (`get_sources`/`search`) use a
guarded `getattr` dispatch so a Protocol-only engine never breaks them. See **Design
Decisions** above for the full rationale (extension Protocol, single-port mount, statelessness).

## Testing Strategy

- `test/unit/api/test_health.py` — `/health` green, no env/secret required.
- `test/unit/api/test_rest.py` — `POST /ask`, `GET /entity/{name}`, `GET /org-chart`,
  `GET /contradictions` shape + pass-through against the mock; `contradictions` key always
  present (never hidden).
- `test/unit/api/test_mcp.py` — MCP tools listed + callable over streamable-HTTP against
  the mock engine; `get_sources`/`search` return structured payloads.
- `test/unit/api/test_cli.py` — `helixpay ask "..."` prints answer + citations + any
  contradiction via the injected mock; `ingest` import is lazy.

## Risks & Mitigations

- *MCP SDK transport API drift* → introspect the installed `mcp` package and pin the
  streamable-HTTP mount pattern empirically; keep the mount in one place.
- *Agent 3's engine lacks `get_sources`/`search`* → guarded dispatch degrades gracefully;
  core 4 tools unaffected.
- *Shared-file collisions* → only my disjoint `touches_paths`; deps declared here, not in
  `pyproject.toml`.

## Success Criteria

- MCP tools callable over HTTP (streamable-HTTP) against a mock engine; `/health` green
  without LLM keys; `helixpay ask "..."` answers via the mock. **Met** — proven both
  in-process (15 `test/unit/api` tests) and against a live uvicorn server with the official
  MCP client (`initialize` + `tools/call` over `/mcp`, all six tools, plus REST `/ask`).
- Swapping the mock for Agent 3's real `QueryEngine` needs no adapter change — one
  `set_engine(...)` call. Backed by `test_retrieval_degrades_when_engine_lacks_surface`.
- `uv run pytest test` green (42 passed, 11 DB tests skipped without `DATABASE_URL`);
  `uv run mypy helixpay` clean (23 files).
- Contradictions surfaced (never hidden) through `/ask`, the `ask` MCP tool, and the CLI.

### Pre-Implementation Review

> Two independent review iterations (Standard-tier floor = 2). Reviewers read the code and
> plan directly via file paths; findings fed back into the design before finalize.

- **Iteration 1** (2026-06-09): architect-reviewer reviewed the plan + design — verdict APPROVE, 0 CRITICAL, 0 HIGH, 1 MEDIUM (TypedDict routes lack `response_model`, accepted: engine owns shape), 4 LOW; confirmed the `ExposureEngine(QueryEngine, Protocol)` extension does not fork the frozen type, the mock→real swap needs no adapter change, and the FastMCP-in-lifespan mount avoids the "mounted sub-app gets no lifespan" trap. Files reviewed: workspace/sprints/SP_005_exposure.md, fanout/AGENT_4_exposure.md, helixpay/contracts/query.py, helixpay/api/engine.py, helixpay/api/app.py, helixpay/mcp/server.py, helixpay/cli.py.
- **Iteration 2** (2026-06-09): code-reviewer ran a plan-blind (Context Isolation, Rule 5) review of code + tests — 2 HIGH (unvalidated `as_of` → 500; `_run_ingest` lets `pipeline.run` tracebacks escape), 4 MEDIUM (wildcard MCP origins; module-level app cost; `if confidence:` hides 0.0; fragile single-frame SSE parse), 3 LOW (fixtures restore fresh mock not original; missing invalid-`as_of` test; vacuous import-isolation test). Files reviewed: helixpay/api/engine.py, helixpay/api/app.py, helixpay/mcp/server.py, helixpay/cli.py, test/unit/api/test_health.py, test/unit/api/test_rest.py, test/unit/api/test_mcp.py, test/unit/api/test_cli.py.

### Post-Implementation Review

- **Iteration 1** (2026-06-09): resolved every HIGH and actionable MEDIUM/LOW from the plan-blind review — 0 CRITICAL, 0 HIGH, 0 blocking remain; added `helixpay/api/_dates.parse_as_of` (REST → 422, MCP → clean tool error), structured `_run_ingest` error handling (exit 1, no raw traceback), removed the wildcard MCP `allowed_origins` (env-driven), print `confidence` unconditionally, `_sse_json` asserts a single frame, fixtures restore the original engine, plus a real 422 test and a real import-isolation test. Files reviewed: helixpay/api/app.py, helixpay/api/_dates.py, helixpay/mcp/server.py, helixpay/cli.py, test/unit/api/test_rest.py, test/unit/api/test_mcp.py, test/unit/api/test_cli.py.
- **Iteration 2** (2026-06-09): re-verified the slice against runtime evidence — 0 CRITICAL, 0 HIGH outstanding; `uv run pytest test` (42 passed, 11 skipped), `uv run mypy helixpay` (clean, 23 files), a live uvicorn + official-MCP-client streamable-HTTP round-trip (six tools + REST `/ask`), and a real `python -m helixpay.cli ask` rendering answer + as_of citations + the surfaced contradiction; no regressions (a separate isolated-worktree verifier run was inconclusive — it inspected a sandbox at the pre-work commit and never saw the uncommitted slice, so the direct runtime evidence is authoritative). Files reviewed: helixpay/api/engine.py, helixpay/api/app.py, helixpay/api/_dates.py, helixpay/mcp/server.py, helixpay/cli.py, test/unit/api/test_health.py, test/unit/api/test_rest.py, test/unit/api/test_mcp.py, test/unit/api/test_cli.py.

## Hand-off (Agent 5)

- uvicorn entrypoint: **`helixpay.api.app:app`** (serves REST + `/mcp` on `127.0.0.1:8000`).
- MCP streamable-HTTP endpoint path: **`/mcp`** (POST to `/mcp/`).
- `/health` is dependency-free (no LLM keys) — safe for a compose healthcheck.
- Production engine wiring is a single provider swap (`helixpay.api.engine.set_engine(...)`),
  not an adapter change.
- New env knobs (optional hardening): `HELIXPAY_MCP_ALLOWED_HOSTS`,
  `HELIXPAY_MCP_ALLOWED_ORIGINS` (comma-separated; default off → DNS-rebinding protection
  disabled for the localhost-behind-proxy deploy).
- Declared deps to consolidate into `pyproject.toml` at merge: `fastapi`, `uvicorn`, `mcp`,
  `httpx` (dev).
