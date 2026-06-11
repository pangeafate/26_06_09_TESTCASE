---
status: living
last-reconciled: 2026-06-11
authoritative-for: [phases, milestones]
---

# Project Roadmap

Build orchestration: `HELIXPAY_BUILD_SPEC.md` (gate → 5 build agents + 1 eval agent
→ adversarial verify → `/goal`).

## Phase 0 — Gate (serial foundation) ✅ COMPLETE (SP_001, 2026-06-09)

Froze the shared substrate every build agent imports: scaffold, `db/schema.sql`,
`contracts/**` + the Postgres `Repository`, `config.py`, `CLAUDE.md` §7, `.claude/**`,
the deterministic roster + `metric_vocab`, and the query fixture. Freeze proven:
contracts import, schema applies on pgvector pg16, seed loads (12 metrics / 63
entities / 99 links), mypy clean, 38 tests green.

## Phase 1 — Parallel build (next) ⬜

Fan out to worktree-isolated agents (disjoint ownership, spec §6):

- **Agent 1** — loaders / ingestion normalization (`ingest/loaders/**`)
- **Agent 2** — extraction & ontology *(critical path)* (`ingest/extract/**`, `resolve.py`, `contradict.py`, `prompts/`)
- **Agent 3** — query brain (`query/**`)
- **Agent 4** — exposure: MCP + API + CLI (`mcp/**`, `api/**`, `cli.py`)
- **Agent 5** — infra & deploy (`deploy/**`, Docker/compose/Makefile, vhost)
- **Agent 6** — eval & ground truth, author-independent (`eval/**`, `tests/golden/**`)

## Phase 2 — Integrate + adversarial verify ⬜

Integrate; Agent 6 runs extraction precision/recall on the golden set + the deep-
question answer checks; one fixer resolves findings; `/simplify` for CLAUDE.md compliance.

## Phase 3 — Live deploy (in progress — operator-gated)

Deploy is **decoupled from the full ingest** (SP_016). Phases:

- **Phase A** (code complete, pending operator push): push `main` → CI gateway → CI deploy →
  `deploy.sh` brings up the app with the seeded backbone (schema + deterministic seed, no full corpus).
  App serves at `https://helixpay.serverado.app`; `verify_mcp.py` confirms MCP reachable.
- **Phase B** (operator-gated, paid ~1h): SP_015 proof signed + MCP green → `scripts/full_run.py`
  (one governed 44-doc extraction) → `scripts/prod_seed.sh` (pg_dump → pg_restore with
  `CREATE EXTENSION vector` ordering).
- **Phase C** (operator-gated, paid ~Opus pass): live `eval.run` Level-2 → recall ≥85%,
  zero uncited claims, both contradictions surfaced → sign `SP016_live_verification.md`.

Full procedure in `workspace/acceptance/SP016_live_verification.md`.

## `/goal` (done condition)

`make test` green · `make demo` answers every eval question with `as_of`-stamped
citations and surfaces ≥1 real contradiction · app reachable at the domain.
