# Agent 4 — Exposure: MCP + FastAPI + CLI (SP_005, Standard)

You are Agent 4. You build **thin adapters** over the `QueryEngine` Protocol: a
streamable-HTTP MCP server (the primary remote surface — the consumer is an agent), a
FastAPI app, and the CLI. You **mock `QueryEngine`** until Agent 3 lands, coding only
against the Protocol. Read `CLAUDE.md` §7, `AGENTS.md`, `HELIXPAY_BUILD_SPEC.md` §5
(Agent 4), and `fanout/README.md`.

## Setup
- Worktree: `git worktree add .claude/worktrees/SP_005 -b sprint/SP_005-exposure main`
- Sprint plan `workspace/sprints/SP_005_exposure.md` — `tier: Standard`,
  `isolation: git-worktree`,
  `touches_paths: [helixpay/mcp/**, helixpay/api/**, helixpay/cli.py, test/unit/api/**]`.

## Owns (write only here)
- `helixpay/mcp/**` — MCP server (streamable-HTTP transport).
- `helixpay/api/**` — FastAPI app.
- `helixpay/cli.py` — `helixpay ask "..."`, `helixpay ingest ./data`.
- `test/unit/api/**`.

## Codes against (frozen — import, never redefine)
```python
from helixpay.contracts import QueryEngine, AnswerBundle, Contradiction, OrgNode, EntityDetail, Citation
# Mock QueryEngine until Agent 3's impl exists; depend ONLY on the Protocol surface:
#   ask(question)->AnswerBundle  get_entity(name)->EntityDetail
#   get_org_chart(as_of=None)->OrgNode  find_contradictions(topic=None)->list[Contradiction]
from helixpay.ingest.pipeline import run as ingest_run   # Agent 2 owns this; cli `ingest` calls it
from helixpay.config import load_config
```
> The `ingest` CLI subcommand calls Agent 2's `helixpay.ingest.pipeline.run` — do **not**
> reimplement ingestion. Until Agent 2 lands, import lazily / behind the subcommand so
> the rest of the CLI works.

## Build
- **MCP server (`mcp/`)** — **streamable-HTTP transport** (hard requirement; stdio is
  local-only and breaks the live-URL story). Tools, typed per object type: `ask`,
  `get_entity`, `get_org_chart`, `find_contradictions`, `get_sources`, `search`. Each
  tool is a thin pass-through to the `QueryEngine`. Mount under `/mcp`.
- **FastAPI (`api/`)** — `POST /ask`, `GET /entity/{name}`, `GET /org-chart`,
  `GET /contradictions`, `GET /health` (returns green). Pydantic response models reuse
  the contract types. Bind the app so compose can serve it on `127.0.0.1:8000`.
- **CLI (`cli.py`)** — `helixpay ask "..."` (prints the answer + citations + any
  contradiction), `helixpay ingest ./data`.

## Conventions
- Adapters are **thin** — no business logic, no DB access, no raw SQL. All reasoning is
  the `QueryEngine`'s job. Secrets from env. Dependency-inject the engine so tests use a
  mock. `GET /health` must not require the LLM keys.
- MCP and FastAPI share the one ASGI app where practical so a single port serves both
  (`/mcp` + REST), matching the deploy model (`127.0.0.1:8000` behind the proxy).

## Dependencies (declare in sprint plan; do NOT edit pyproject)
`fastapi`, `uvicorn`, `mcp` (the MCP Python SDK), `httpx` (tests).

## Done when
- MCP tools are callable over HTTP (streamable-HTTP) against a mock engine; `/health`
  green; `helixpay ask "..."` answers via the mock. Swapping the mock for Agent 3's real
  `QueryEngine` requires no adapter change.
- Tests green; mypy clean.

## Hand-off
Agent 5 runs your app in compose on `127.0.0.1:8000` and fronts `/mcp` via the proxy.
Confirm the app's import path + the uvicorn entrypoint name in your delivery report so
Agent 5 can wire it (this is the frozen "gate entrypoint" Agent 5 depends on — name it:
e.g. `helixpay.api.app:app`).
