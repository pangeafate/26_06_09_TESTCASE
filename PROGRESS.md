---
status: living
last-reconciled: 2026-06-10
authoritative-for: [active-sprint, sprint-history]
---
<!-- Template: fill in sections below. Replace last-reconciled with today's ISO date when you copy. Remove this comment when populated. -->

# Progress

> **Note**: Archive to `PROGRESS_ARCHIVE_NNN.md` when this file exceeds 25 sprints.

## Active Sprint

**Current:** SP_011
**Started:** 2026-06-10
**Stage:** Complete — provenance produced on the ingest write path (items 1–4); unit-verified.

<!-- NOTE: The **Current:** format is required by validate_sprint.py's active sprint detection. -->

SP_011 — Provenance Persist (ingest side): claims now carry the verbatim `evidence`
span + located char offsets; links carry `document_id`; a graph-contradiction sweep
(`detect_link_conflicts`, reports_to-only) makes reporting conflicts first-class; seeded
reporting edges are emitted undated so the cited edge extracted from `org-chart.md`
coexists (corroborate, not replace). Plan: `workspace/sprints/SP_011_provenance_persist.md`.
Isolation: `git-worktree` (`sprint/SP_011-provenance-persist`). End-to-end replay-tier
confirmation over the real corpus is deferred (needs a live DB + recorded cache).

Prior: SP_010 — recall fixes + the $0 replay tier (record once, re-run the post-LLM
pipeline from cache) + the planted Confluence GA contradiction. SP_009 — provenance
contracts/schema v2 (evidence/offsets, link `document_id`, link-pair contradictions) +
the shared `normalize` util.

SP_008 — DEV_RULES Reinforcement: implement the DEV_RULES reinforcement
findings from the SP_002–SP_007 fan-out (status advisory, orphan-worktree WI-4,
declared-dependencies field + validator + consolidation script, package-root
scaffolding practice, env pin, integration-as-owned-phase). Plan:
`workspace/sprints/SP_008_dev_reinforce.md`. Touches the governance substrate
(validators/, scripts/, practices/, template, build spec) — disjoint from the
in-flight worktrees, so `isolation: shared-tree` on main is safe.

Prior: SP_001 — Phase 0 Gate froze the shared substrate (contracts, schema,
Repository, config, seed roster + metric_vocab, query fixture). Freeze proven:
schema applies on pgvector pg16, seed loads (12 metrics / 63 entities / 99
links), mypy clean, 38 tests green. Stages 3 + 5 complete.

## Phase 1 Integration

**Branch:** `merge/integration` (off `main` @ SP_008). The six worktree slices
(SP_002–SP_007) merged in dependency order. Two expected conflicts resolved:
`helixpay/ingest/__init__.py` (SP_002+SP_003 add/add → docstring union) and
`PROGRESS.md` (SP_004 → take-main). Real engine wired into the exposure startup
(`helixpay.api.app.wire_engine`, gated on `DATABASE_URL`). Runtime deps
consolidated into one `pyproject.toml` + `helixpay` console script + regenerated
`uv.lock` (DEV_REINFORCE F-2). **Integrated tree: 260 passed / 22 db-skipped,
mypy clean (52 files), 11/11 validators PASS, dev-gateway green via `.venv`.**
Remaining to go live: run the Agent-6 gate against a real pgvector DB
(`make up` → migrate → seed → ingest `data/` → `eval/run.py` ≥80% recall) and
deploy (`deploy.sh` → `/health` 200, `/mcp` live).

## Sprint History

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
