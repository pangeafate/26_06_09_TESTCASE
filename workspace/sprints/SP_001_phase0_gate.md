---
sprint_id: SP_001
tier: Foundational
features: [ontology-substrate, frozen-contracts, deterministic-backbone]
user_stories: []
schema_touched: true
structure_touched: true
status: In Progress
isolation: shared-tree
branch: ""
worktree: ""
agent_owner: "orchestrator (gate)"
touches_paths:
  - pyproject.toml
  - helixpay/__init__.py
  - helixpay/config.py
  - helixpay/contracts/**
  - helixpay/db/**
  - helixpay/seed/**
  - CLAUDE.md
  - .claude/**
  - test/conftest.py
  - test/unit/contracts/**
  - test/unit/seed/**
  - test/integration/db/**
fix_type: ""
touches_checklist_items: [gate-scaffold, gate-schema, gate-contracts, gate-repository, gate-config, gate-claudemd, gate-claude-dir, gate-seed-roster, gate-metric-vocab, gate-query-fixture]
---

# SP_001: Phase 0 Gate — Frozen Substrate for the HelixPay Ontology Build

## Sprint Goal

Build the serial foundation that every downstream build agent imports against, then
**freeze** it: repo scaffold, `db/schema.sql`, the four `contracts/**` Protocols + models,
the Postgres `Repository` implementation, `config.py`, the HelixPay `CLAUDE.md` §7
conventions, `.claude/` commands + verifier stub, a minimal seeded query fixture, and the
**deterministic backbone** (entities/links roster parsed from `org-chart.md`+`overview.md`;
`metric_vocab` controlled vocabulary loaded from the dashboards/financials). This is the
gate from `HELIXPAY_BUILD_SPEC.md` §5; the build cannot fan out to Agents 1–6 until it is
frozen, because they would otherwise collide on shared types. Architecture is already
debated and frozen in `HELIXPAY_BUILD_SPEC.md` §2–§4; this sprint implements it.

## Current State

- DEV_RULES governance is wired in (root `CLAUDE.md` + `AGENTS.md`, validators, hooks).
- `CLAUDE.md` carries a **placeholder** "HelixPay Project Conventions (authored at the gate)"
  section (spec §7) — not yet authored.
- `data/` holds the 44-file HelixPay dataset (md/pdf/html/image/slack/email/code).
- No `helixpay/` package, no schema, no contracts, no config — nothing to import against.
- Toolchain: Python 3.13 + uv + Docker present; no local Postgres (verify via the
  `pgvector/pgvector:pg16` container, which is how the build runs).

## Desired End State

- `helixpay/` package importable; `pip`/`uv` install resolves from `pyproject.toml` (Py ≥3.12).
- `helixpay/contracts/` exports `models` (Document, Chunk, Entity, Claim, Link, Contradiction,
  Citation, AnswerBundle) and the four Protocols (SourceConnector, Repository, QueryEngine)
  exactly per spec §4 — importable, type-checkable, never redefined downstream.
- `helixpay/db/schema.sql` applies cleanly onto pgvector pg16 (extension + 8 tables +
  indexes/constraints) per spec §3.
- `helixpay/db/repository.py` provides `PostgresRepository` implementing the `Repository`
  Protocol; idempotent `upsert_document` (no-op on duplicate `content_hash`),
  `resolve_entity` matches the seeded roster first, `canonical_predicate` maps via
  `metric_vocab`, hybrid search methods present.
- `helixpay/config.py` reads `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`, `DATABASE_URL` and pins
  model ids (extraction=`claude-sonnet-4-6`, synthesis=`claude-opus-4-8`, embeddings=voyage 1024d).
  No secret literals.
- Deterministic backbone: running the seed loads ~70 roster entities (people/teams) +
  reports_to/member_of links from `org-chart.md`, org/product aliases from `overview.md`,
  and a controlled `metric_vocab` (revenue, arr, ebitda, monthly_burn, runway, nps, churn,
  net_new_merchants, total_paid_merchants, headcount, …) with alias lists.
- A minimal hand-written **query fixture** (a few entities/claims/links/one contradiction)
  so Agent 3 can build `ask()` against a live DB before real extraction lands.
- `CLAUDE.md` §7 authored (stack/conventions/ontology-rules/gotchas).
- `.claude/commands/{ingest,verify}.md` and `.claude/agents/verifier.md` present.
- **Freeze proof:** `python -c "import helixpay.contracts ..."` succeeds; schema applies on a
  throwaway pgvector container; the seed + fixture load without error; contract + seed unit
  tests pass.

## What We're NOT Doing

- No loaders, extraction, query engine, MCP/API/CLI, Docker compose, Makefile, or eval harness
  — those are Agents 1–6 (spec §5/§6). The gate only freezes the shared layer they import.
- No real LLM/extraction calls; the backbone is deterministic parsing only.
- No `.env.example`/compose/`make up` (Agent 5 owns the run wiring); the gate verifies schema
  via a direct `docker run` throwaway container.
- No golden ground-truth set or `eval/**` (Agent 6 authors those independently).

## Technical Approach

1. **Scaffold** — `pyproject.toml` (name `helixpay`, Py≥3.12, deps: `psycopg[binary,pool]`,
   `pydantic`, `pyyaml`; dev: `pytest`). `helixpay/__init__.py`, package dirs.
2. **Contracts (spec §4, refined by Stage 3 review — see Review Log)** — `contracts/models.py`
   as frozen `pydantic`/`dataclass` models; `contracts/connector.py`, `contracts/repository.py`,
   `contracts/query.py` as `@runtime_checkable typing.Protocol` classes. `contracts/__init__.py`
   re-exports. **Frozen seam decisions:**
   - `resolve_entity(name, entity_type=None, context: dict|None=None) -> Entity|None` — `context`
     carries team/location/source hints so Agent 2 disambiguates the two Marias / two Tans; a bare
     ambiguous name with no context resolves to `None` (never a silent arbitrary pick). [C1]
   - `supersede_claim(old_id, new_id, valid_to) -> None` added to `Repository` — supersession flows
     through the frozen seam (sets `valid_to`/`superseded_by`), never a delete. [H2]
   - `add_chunks(chunks, embeddings) -> list[int]` — `tsv` dropped from the signature; computed in
     DB as a GENERATED column. Embeddings are produced upstream by the ingest pipeline (Voyage). [H3]
   - `canonical_predicate(raw) -> str` documented "returns `raw` unchanged if unknown; never raises." [M-1]
   - Typed returns: `OrgNode`/`EntityDetail` TypedDicts in `models.py` back `get_org_subtree`/
     `get_entity`/`get_org_chart` instead of bare `dict`. [M2]
3. **Schema (spec §3, refined by review)** — `db/schema.sql`: `CREATE EXTENSION vector`; the 8
   tables; HNSW on `chunks.embedding`; `chunks.tsv` a **GENERATED** `tsvector` column (GIN
   indexed) [H3]; `(subject_entity_id, predicate)` index + a partial-UNIQUE natural key on
   `claims(subject_entity_id, predicate, object_value, source_chunk_id)` for insert idempotency
   [H1]; `links.link_type` set extended with **`dotted_line_to`** [C2]; UNIQUE on
   `documents.content_hash`. `db/migrate.py` applies it following GL-ERROR-LOGGING (per-statement
   failure surfaced, exit 0/1/2, connection string never logged) [H-2].
4. **Repository** — `db/connection.py` (psycopg connection/pool from `DATABASE_URL`);
   `db/repository.py` `PostgresRepository` implementing every `Repository` method. Raw SQL
   confined to `db/` per convention. Idempotency on `content_hash`; roster-first
   `resolve_entity`; `canonical_predicate` via `metric_vocab`.
5. **Deterministic backbone** — `seed/roster.py` exposes a **pure** `parse_org_chart(text) -> ...`
   and `parse_overview(text) -> ...` with **zero `db/` imports** [H-3]; they parse the exec table,
   nested team trees, the dotted-line note (→ `dotted_line_to` links) [C2], and product/company
   aliases (HPB/Helix Brasil as one entity w/ aliases; POS ≠ POS Self-Service as distinct
   products) [L2]. Seeded links/claims are stamped `as_of=2026-04-15` (org-chart export date) +
   `seeded=true` so Agent 3's freshest-wins resolver dates them [M1]. `seed/metric_vocab.py`
   defines the controlled vocab **data-derived** from the dashboards/overview with alias lists
   covering the literal eval strings (`"annual recurring revenue"`/`"ARR"`→`arr`) [H4].
   `seed/run_seed.py` writes everything through `PostgresRepository` (no raw SQL outside `db/`).
6. **Query fixture** — `seed/fixtures.py` (NOT a top-level `fixtures/` — avoids the layer/SQL
   boundary break and the Agent-6 `eval/` naming clash) [C-2, M-3]: inserts a handful of
   entities + claims **via `Repository`**, incl. one deliberate value-conflict contradiction
   across two sources, so Agent 3 has live rows.
7. **Conventions** — author `CLAUDE.md` §7 in place of the placeholder; add `.claude/`
   commands + verifier-agent stub (`isolation: worktree`).
8. **Freeze verification** — import check; `docker run` pgvector → `migrate.py` → `run_seed.py`;
   pytest.

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `pyproject.toml` | Create | Package + deps (uv), Py≥3.12 |
| `helixpay/__init__.py` | Create | Package marker/version |
| `helixpay/config.py` | Create | Env-only secrets + pinned model ids |
| `helixpay/contracts/models.py` | Create | Frozen domain models (spec §4) |
| `helixpay/contracts/connector.py` | Create | `SourceConnector` Protocol |
| `helixpay/contracts/repository.py` | Create | `Repository` Protocol |
| `helixpay/contracts/query.py` | Create | `QueryEngine` Protocol |
| `helixpay/contracts/__init__.py` | Create | Public re-exports |
| `helixpay/db/schema.sql` | Create | Ontology schema (spec §3) |
| `helixpay/db/connection.py` | Create | psycopg connection/pool |
| `helixpay/db/migrate.py` | Create | Apply schema.sql |
| `helixpay/db/repository.py` | Create | `PostgresRepository` impl |
| `helixpay/db/__init__.py` | Create | Package marker |
| `helixpay/seed/roster.py` | Create | Parse org-chart/overview → entities/links/aliases |
| `helixpay/seed/metric_vocab.py` | Create | Controlled metric vocabulary |
| `helixpay/seed/run_seed.py` | Create | Orchestrate seed (via Repository) |
| `helixpay/seed/fixtures.py` | Create | Minimal seeded rows for Agent 3 (via Repository) |
| `helixpay/seed/__init__.py` | Create | Package marker |
| `CLAUDE.md` | Modify | Author §7 conventions (replace placeholder) |
| `.claude/commands/ingest.md` | Create | `make ingest` command doc (notes Agent-5 dep) |
| `.claude/commands/verify.md` | Create | `make test && make demo` command doc (notes Agent-5 dep) |
| `.claude/agents/verifier.md` | Create | Verifier-agent stub (`isolation: worktree`) |
| `test/conftest.py` | Create | Registers `db` mark; `db_url` fixture skips if `DATABASE_URL` unset (no fallback creds) |
| `test/unit/contracts/test_models.py` | Create | Model construction + invariants |
| `test/unit/contracts/test_protocols.py` | Create | `@runtime_checkable` Protocol name-check (+ mypy in freeze for signatures) |
| `test/unit/seed/test_roster.py` | Create | Parse correctness on inline fixtures + name-trap distinctness; real-`data/` parse marked `smoke` |
| `test/unit/seed/test_metric_vocab.py` | Create | Canonicalization incl. unknown-passthrough (never raises) |
| `test/integration/db/test_repository_integration.py` | Create | Schema-applies + content_hash + supersede idempotency (DB-gated) |

## Testing Strategy

Following `practices/GL-TDD.md`, red→green per unit:

1. **Contracts** — tests construct each model with valid/invalid data (Citation requires
   `source_uri`+`as_of`; AnswerBundle carries `contradictions`/`as_of_coverage`). A structural
   test asserts `PostgresRepository` is accepted where the `Repository` Protocol is expected
   (runtime-checkable / attribute presence), catching signature drift at the freeze.
2. **Seed roster** — pure-function parse tests over `org-chart.md`: Wei Chen=CEO→Board;
   Daniel Tan≠Tan Wei Ming; Maria Santos≠Maria Silva resolve to distinct entities; reports_to
   chain (Sara Wijaya→Daniel Tan→Arjun Kapoor→Wei Chen); product aliases (POS ≠ POS Self-Service).
3. **Metric vocab** — `canonical_predicate("annual recurring revenue") == "arr"`; unknown
   predicate passes through unchanged.
4. **Repository integration (DB-gated)** — skipped unless `DATABASE_URL` is set; applies schema
   to a throwaway pgvector container, asserts `upsert_document` is a no-op on duplicate
   `content_hash`, and `resolve_entity` hits the seeded roster first.
5. Unit tests (1–3) run with no DB; integration (4) runs in freeze verification via `docker run`.

## Success Criteria

- [ ] `import helixpay.contracts` and the four Protocols import with no error
- [ ] `db/schema.sql` applies cleanly on `pgvector/pgvector:pg16` (extension + 8 tables + indexes)
- [ ] `PostgresRepository` implements every `Repository` method; structural Protocol test passes
- [ ] Seed loads roster (≥60 entities, reports_to + member_of links) + `metric_vocab`; name traps resolve distinctly
- [ ] Query fixture loads incl. ≥1 first-class contradiction row
- [ ] `config.py` reads the three env secrets; no secret literals anywhere (validator clean)
- [ ] `CLAUDE.md` §7 authored; `.claude/` commands + verifier stub present
- [ ] Contract + seed unit tests pass; DB integration test passes under `docker run`
- [ ] All existing validators/tests still pass
- [ ] PROGRESS.md updated

### Doc Reconciliation Checklist

Complete at Stage 6 (Documentation). Tick each meta-doc whose subject matter this sprint touched.

- [ ] `FEATURE_LIST.md` — gate deliverables marked
- [ ] `PROJECT_ROADMAP.md` — Phase 0 milestone status
- [ ] `ARCHITECTURE.md` — substrate/layers recorded
- [ ] `DATA_SCHEMA.md` — the 8-table ontology schema
- [ ] `CODEBASE_STRUCTURE.md` — `helixpay/` layout
- [ ] `USER_STORIES.md` — if acceptance criteria satisfied
- [ ] `last-reconciled` bumped on each touched meta-doc
- [ ] `python validators/validate_doc_reality.py .` returns 0
- [ ] `python validators/validate_doc_freshness.py .` returns 0
- [ ] `.docs_reconciled` lockfile present naming SP_001

## Review Log

### Pre-Implementation Review
- **Iteration 1** (2026-06-09): architect-reviewer found 2 CRITICAL, 4 HIGH, 4 MEDIUM, 3 LOW. Files reviewed: workspace/sprints/SP_001_phase0_gate.md, HELIXPAY_BUILD_SPEC.md §3/§4, data/org-chart.md, data/overview.md
- **Iteration 2** (2026-06-09): code-reviewer found 2 CRITICAL, 4 HIGH, 5 MEDIUM, 3 LOW. Files reviewed: workspace/sprints/SP_001_phase0_gate.md, HELIXPAY_BUILD_SPEC.md §4/§5/§7, CLAUDE.md, practices/GL-TDD.md, practices/GL-ERROR-LOGGING.md

**Resolution — All CRITICAL and HIGH addressed:**
1. **C1 (resolve_entity can't disambiguate name traps)**: froze `resolve_entity(name, entity_type=None, context=None)`; ambiguous bare name → `None`, never a silent pick.
2. **C2 (dotted-line links unrepresented)**: added `dotted_line_to` to `links.link_type`; roster parses the dotted-line note into those links.
3. **H1 (claims not idempotent on re-ingest)**: added partial-UNIQUE natural key on `claims(subject_entity_id, predicate, object_value, source_chunk_id)`.
4. **H2 (no supersession method)**: added `supersede_claim(old_id, new_id, valid_to)` to the Repository Protocol + impl.
5. **H3 (embedding/tsv ownership unpinned)**: `tsv` is a DB GENERATED column; `add_chunks(chunks, embeddings)`; embeddings produced upstream by ingest. Pinned in CLAUDE.md §7.
6. **H4 (metric_vocab might no-op contradictions)**: vocab data-derived from dashboards/overview; tests assert eval-relevant aliases (`"annual recurring revenue"`→`arr`) canonicalize.
7. **code-C-1 (wrong test tree)**: tests moved under existing `test/unit/**` + `test/integration/**`; added `test/conftest.py`.
8. **code-C-2 / M-3 (fixtures break layer/SQL boundary + Agent-6 name clash)**: query fixture is `helixpay/seed/fixtures.py`, writes only through `Repository`.
9. **code-H-2 (migrate.py error contract)**: migrate.py follows GL-ERROR-LOGGING — per-statement failure surfaced, exit codes, no connection string in logs.
10. **code-H-3 (parse not DB-isolated)**: `seed/roster.py` exposes pure `parse_*` functions with zero `db/` imports; writes happen only in `run_seed.py`.
11. **code-H-4 (DATABASE_URL test guard)**: `conftest.py` skips DB tests when `DATABASE_URL` is unset; no fallback credential anywhere.

**Deferred (MEDIUM/LOW, non-blocking, tracked):** M2 typed-dict returns (OrgNode/EntityDetail) — done in models; M-1 canonical_predicate never-raises — done; M-4 mypy signature gate — added to freeze verification; M1 as_of stamping — done in seed; L1/L3 exact roster count — pin in test after first parse; L-1 `.claude/commands` annotate Agent-5 dependency — done; M-2 real-data parse test marked `smoke` — done.

### Post-Implementation Review
- **Iteration 1** (2026-06-09): code-reviewer (plan-blind) found 1 CRITICAL, 3 HIGH, 3 MEDIUM, 2 LOW. Files reviewed: helixpay/db/schema.sql, helixpay/db/repository.py, helixpay/seed/roster.py, helixpay/seed/run_seed.py, helixpay/seed/fixtures.py, test/integration/db/test_repository_integration.py
- **Iteration 2** (2026-06-09): security-auditor (plan-blind) found 0 CRITICAL/HIGH/MEDIUM, 3 LOW. Files reviewed: helixpay/config.py, helixpay/db/connection.py, helixpay/db/migrate.py, helixpay/db/repository.py, helixpay/seed/run_seed.py, helixpay/seed/fixtures.py, test/conftest.py. Verdict: no SQL injection, no secret-leak path; every value parameterized; secrets env-only.

**Resolution — All CRITICAL and HIGH addressed:**
1. **C-1 (claims natural key dup on NULL subject)**: `claims_natural_key` now COALESCEs `subject_entity_id`; `add_claim` ON CONFLICT target matches the index; fallback SELECT gets `LIMIT 1`.
2. **H-3 (add_chunks not idempotent)**: added `UNIQUE(document_id, ordinal)` to `chunks` + `ON CONFLICT DO NOTHING` with existing-row fallback; tested.
3. **H-2 (org root ignored as_of)**: `_org_root_id(as_of)` now applies the same date filter as the edge query; tested with a past date.
4. **H-4 (contradiction (a,b)/(b,a) dup)**: `add_contradiction` normalizes the pair to (min,max); tested both orders dedupe to one row.
5. **M-5 (run_seed connection leak)**: `main()` closes the connection in `finally`; exception narrowed to `(MissingEnvError, psycopg.Error)`.
6. **M-6 (path-local cycle guard)**: `get_org_subtree` uses a single global `visited` set (no double-emit under multi-parent/cycle).
7. **M-7 / sec-LOW (non-finite embedding)**: `_vector_literal` rejects nan/inf with a clean ValueError (both reviewers).
8. **LOW-8 (empty citation)**: `get_sources` filters rows lacking any source (no `source_uri=""` citations).
9. **LOW-9 (test gaps)**: added tests for add_chunks idempotency, resolve_entity context disambiguation (shared alias), contradiction-pair dedup, and as_of org-subtree filtering. Suite now 38 green.

**Deferred (LOW, non-blocking):** migrate splitter hardening (sec-LOW; trusted schema only — documented assumption); single-parent enforcement on `links` (a `CHECK`/trigger) left for the extraction slice where multi-parent could arise.
