---
status: living
last-reconciled: 2026-06-10
authoritative-for: [active-sprint, sprint-history]
---

# Progress

> **Note**: Archive to `PROGRESS_ARCHIVE_NNN.md` when this file exceeds 25 sprints.

## Active Sprint

**Current:** SP_016
**Started:** 2026-06-10
**Stage:** Phase A code complete — pending operator live deploy (Phases B/C operator-gated)

<!-- NOTE: The **Current:** format is required by validate_sprint.py's active sprint detection. -->

SP_016 — Functional live system — gated deploy. Phase A code complete:
  - `deploy/deploy.sh` decoupled from full ingest (no more unguarded `helixpay ingest ./data`).
  - `.github/workflows/deploy.yml` CI/CD deploy job wired (gated on gateway job).
  - `scripts/verify_mcp.py` MCP agent-reachability verifier (streamable-HTTP, exits non-zero on failure).
  - `scripts/prod_seed.sh` production seed transfer (pg_dump → restore, SP015 proof guard).
  - `deploy/tests/test_infra_contract.py` extended with SP_016 invariants.
  - `test/unit/scripts/test_verify_mcp.py` and `test_prod_seed.py` new unit tests.
  - `workspace/acceptance/SP016_live_verification.md` signed-artifact template with exact operator steps.
  - Meta-docs reconciled (Rule 16).
  Phases B + C (full corpus load + live eval) are operator-gated — pending operator smoke.
  Plan: `workspace/sprints/SP_016_live_deploy.md`.

Prior: SP_008 — DEV_RULES Reinforcement. SP_001 — Phase 0 Gate.

## Phase 1 Integration

**Branch:** `merge/integration` (off `main` @ SP_008). The six worktree slices
(SP_002–SP_007) merged in dependency order. Two expected conflicts resolved:
`helixpay/ingest/__init__.py` (SP_002+SP_003 add/add → docstring union) and
`PROGRESS.md` (SP_004 → take-main). Real engine wired into the exposure startup
(`helixpay.api.app.wire_engine`, gated on `DATABASE_URL`). Runtime deps
consolidated into one `pyproject.toml` + `helixpay` console script + regenerated
`uv.lock` (DEV_REINFORCE F-2). **Integrated tree: 260 passed / 22 db-skipped,
mypy clean (52 files), 11/11 validators PASS, dev-gateway green via `.venv`.**
Deploy decoupled from full ingest (SP_016 Phase A): `deploy.sh` brings the
app live with the seeded backbone only; the full corpus (44 docs) loads via
`scripts/full_run.py` after the SP_015 gate opens. Phases B + C are
operator-gated (see `workspace/acceptance/SP016_live_verification.md`).

## Sprint History

### SP_018: RDD/SRP refactor — separate domain logic from I/O

- **Status**: Complete
- **Date**: 2026-06-10
- **Summary**: Behavior-preserving SRP split driven by a `/my-rdd-review` audit. Extracted
  pure domain logic out of three I/O-mixed hot spots into four new pure modules:
  `query/citations.py` (citation resolve/dedup/confidence, out of `synthesis.enforce_citations`),
  `ingest/extract/validate.py` + `glean.py` (per-item coerce/validate/loss-accounting and
  gleaning dedup, out of `ChunkExtractor`), and `ingest/assemble.py` (claim/link build +
  same-source supersession decision, out of `pipeline`). Also fixed `.validators.yml`
  `module_size.source_roots` (was `[src,scripts,skills]` — scanned nothing; now `[helixpay,
  scripts]`) so the GL-RDD size sensor actually scans the codebase. No contract/schema/DB
  change. Plan-blind review: no CRITICAL, no behavior change.
- **Tests added**: +40 (test_citations 12, test_glean 8, test_validate 6, test_assemble 14);
  560 unit passing, mypy clean, module-size sensor clean over 83 files.

### SP_002–SP_007: HelixPay Phase 1 six-agent fan-out

- **Status**: Complete (integrated on `merge/integration`)
- **Date**: 2026-06-10
- **Summary**: SP_002 source loaders (8 formats); SP_003 extraction/embedding/
  contradiction/resolution pipeline; SP_004 query+ask engine (cited, contradiction-
  surfacing); SP_005 exposure (FastAPI + streamable-HTTP MCP + CLI); SP_006 infra
  (Docker/compose/Makefile/deploy, live DNS+TLS); SP_007 eval/ground-truth harness.
- **Tests added**: 260 passing on the integrated tree (22 db-gated skips).

### SP_001: Phase 0 Gate

- **Status**: Complete
- **Date**: 2026-06-09
- **Summary**: Froze the shared substrate — contracts, schema, Repository, config,
  seed roster + metric_vocab, query fixture. Schema applies on pgvector pg16; seed
  loads 12 metrics / 63 entities / 99 links; mypy clean.
- **Tests added**: +38

### SP_016: Functional live system — gated deploy (Phase A)

- **Status**: Phase A code complete; Phases B+C pending operator smoke
- **Date**: 2026-06-10
- **Summary**: Deploy decoupled from full ingest; CI/CD deploy job wired;
  `verify_mcp.py` MCP verifier; `prod_seed.sh` production seed transfer;
  infra contract tests extended; meta-docs reconciled (Rule 16).
  Phases B (full run) + C (live eval) are operator-gated.
  Acceptance template: `workspace/acceptance/SP016_live_verification.md`.
- **Tests added**: +16 (infra contract extensions + test_verify_mcp + test_prod_seed)

### SP_008: DEV_RULES Reinforcement

- **Status**: Complete
- **Date**: 2026-06-09
- **Summary**: Implemented DEV_REINFORCE findings — status advisory, orphan-worktree
  WI-4, declared-deps field + validator + consolidation script, package-root
  scaffolding, env pin, integration-as-owned-phase.
- **Tests added**: +13 validator tests

<!-- Example:
### SP_130: Workout Tracking Foundation

- **Status**: Complete
- **Date**: 2026-03-28
- **Summary**: Exercise logging with 3-tier fuzzy matching, category-specific PR detection, muscle group recency suggestions with 48h cooldown
- **Tests added**: +208 new tests (5,867 total)

### SP_129: Knowledge Briefing Relevance Fix

- **Status**: Complete
- **Date**: 2026-03-25
- **Summary**: Added `expected_outcome` to `InitiativeItem`; fixed BM25 data truncation that caused empty knowledge sections in briefings
- **Tests added**: +7 new tests (5,659 total)

### SP_105: Thesis to Hypothesis Full Rename

- **Status**: Complete
- **Date**: 2026-01-10
- **Summary**: Renamed all thesis references to hypothesis across database tables, domain models, services, and tests
- **Tests added**: +0 (rename only)
-->
