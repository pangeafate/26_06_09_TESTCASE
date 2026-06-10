---
sprint_id: SP_009
tier: Foundational
features: [provenance-contracts-v2, provenance-schema-v2, repository-v2]
user_stories: []
schema_touched: true
structure_touched: true
status: In Progress
isolation: branch-only
branch: sprint/SP_009-contracts-v2
worktree: ""
agent_owner: "Agent A (gate)"
fix_type: ""
dependencies: []
dev_dependencies: []
touches_paths:
  - helixpay/contracts/models.py
  - helixpay/contracts/repository.py
  - helixpay/db/schema.sql
  - helixpay/db/repository.py
  - helixpay/db/migrate.py
  - helixpay/ingest/normalize.py
  - test/unit/contracts/**
  - test/unit/ingest/test_normalize.py
  - test/integration/db/**
touches_checklist_items: [v2-claim-evidence, v2-claim-offsets, v2-link-document-id, v2-contradiction-link-refs, v2-repo-link-sources, v2-repo-chunk-sources, v2-repo-known-hashes, v2-repo-links-filter, v2-shared-normalize, v2-schema-migration]
---

# SP_009: Contract & Schema Amendment v2 — provenance substrate (the round-2 gate)

## Sprint Goal

This is the **gating sprint** for fan-out #2 — the round-2 analogue of SP_001. It
amends the **frozen** contracts and schema once, so the three downstream slices
(SP_011 provenance-persist, SP_012 provenance-surface, SP_013 eval+ingest) can be
built in parallel against a stable, byte-identical substrate. It is the **only**
sprint that touches `helixpay/contracts/**`, `helixpay/db/schema.sql`, and
`helixpay/db/repository.py`.

Per CLAUDE.md these are *proposed contract changes migrated forward across all
slices*, not per-module forks. Every change is **additive and backward-compatible**:
new columns are nullable, new Protocol methods are additive, and existing rows /
callers degrade to today's behavior until re-ingested.

Scope (from `research/provenance-evidence-and-ux-pipeline-design.md` gaps 1–4,
`research/query-design-and-best-practices.md` chunk-citation hole, and
`research/ingest-append-and-task-fit.md` compute-idempotency):

1. **`Claim.evidence` + `char_start`/`char_end`** — carry the verbatim grounding
   span and its offsets on the model and the `claims` table (gaps 1, 2).
2. **`Link.document_id`** — mirror `Claim` so relationship provenance is a direct
   join, not claims-only (gap 3).
3. **`Contradiction` link references** — `link_a_id`/`link_b_id` so graph conflicts
   can be first-class rows (gap 4).
4. **`Repository` Protocol additions** (declared *and* implemented in
   `PostgresRepository`, so downstream slices never edit `db/repository.py`):
   - `get_link_sources(link_ids) -> list[Citation]`
   - `get_chunk_sources(chunk_ids) -> list[Citation]` (closes the query
     chunk-citation hole)
   - `known_content_hashes() -> set[str]` (compute-idempotency: re-ingest → near-free)
   - `get_links(from_entity_id=…, link_type=…)` filter overload
   - `add_claim` / `add_link` accept and persist the new provenance columns.
5. **Shared `helixpay/ingest/normalize.py`** — one canonical value-normalization util
   (numeric words, currency/unit suffixes, `~`/approx) imported by contradiction
   detection, the eval matcher, and consensus rollup, so the three never drift.

## Current State

- Contracts are frozen on `main` and byte-identical across every round-1 slice
  (hash verified at Phase-1 integration). `Claim`/`Link`/`Contradiction`/`Citation`
  live in `helixpay/contracts/models.py`; the `Repository` Protocol in
  `helixpay/contracts/repository.py`; the one implementation in
  `helixpay/db/repository.py`; the schema in `helixpay/db/schema.sql`.
- `claims` has no `evidence`/offset column; `links` has no `document_id`;
  `contradictions` references claims only; `get_sources` is claims-only;
  no `known_content_hashes`. Value normalization is duplicated (eval harness +
  `grounding.py`) with no shared owner.

## Desired End State

- `Claim.evidence`, `Claim.char_start`, `Claim.char_end`, `Link.document_id`,
  `Contradiction.link_a_id`/`link_b_id` exist on both the pydantic models and the
  schema; `migrate.py` applies the additive DDL statement-by-statement (no
  dollar-quoted bodies — CLAUDE.md gotcha).
- `PostgresRepository` implements the four new read methods and the extended
  `add_claim`/`add_link`, with DB-integration tests (`db`-marked, auto-skip without
  `DATABASE_URL`).
- `helixpay/ingest/normalize.py` exists with unit tests covering the cases the
  recall + provenance work depends on (`eighteen months ≡ 18 months`,
  `SGD 14.2M ≡ 14.2 million`, `~18 ≡ 18`).
- `uv run pytest test` green; `uv run mypy helixpay` clean. Frozen-contract
  consumers (round-1 slices) still import and pass unchanged.

## Scope

In: the additive contract/schema/repository/normalize changes above + their tests.
Out: any *use* of the new fields (persisting evidence, surfacing link citations,
wiring `known_content_hashes` into the CLI, consensus rollup) — those are SP_011/
SP_012/SP_013. This sprint only makes the capability *exist*.

## Technical Approach

- **Models** — add nullable fields to `Claim`/`Link`/`Contradiction`; no field
  removed or retyped, so existing structured-output validation and round-1 imports
  are unaffected.
- **Schema** — append `ALTER TABLE … ADD COLUMN IF NOT EXISTS …` statements
  (idempotent, BOM-free, no `$$` bodies). Offsets are `INT`; `evidence` is `TEXT`;
  `links.document_id BIGINT REFERENCES documents(id)`; contradiction link refs
  `BIGINT REFERENCES links(id)`.
- **Repository** — implement the four reads with plain SQL inside `helixpay/db/`
  (no raw SQL escapes the module — CLAUDE.md). `get_chunk_sources`/`get_link_sources`
  return `Citation` with `snippet` = `evidence` when present else chunk-prefix.
  `known_content_hashes` is a single `SELECT content_hash FROM documents`.
- **normalize** — pure function module, no I/O, fully unit-testable; the eval matcher
  and `contradict.values_conflict` import it in their own sprints (SP_013/SP_011) so
  this sprint only ships the util + tests.

## Testing Strategy

- `test/unit/contracts/test_models.py` — new fields default to `None`, round-trip
  validate, and old payloads (without them) still validate (backward-compat).
- `test/unit/ingest/test_normalize.py` — the equivalence cases above + non-matches.
- `test/integration/db/test_repository_integration.py` — migrate applies the new
  DDL on `pgvector/pg16`; `add_claim` persists+reads back `evidence`/offsets;
  `add_link` persists `document_id`; `get_link_sources`/`get_chunk_sources`/
  `known_content_hashes`/`get_links(from_entity_id=…)` return correct rows.

## Risks & Mitigations

- *A table-level `UNIQUE(expr)` slips into the migration* → use `CREATE UNIQUE INDEX`
  for any expression key (CLAUDE.md freeze-rerun gotcha). No new expression keys are
  planned here.
- *Downstream slices edit `db/repository.py` and collide* → this sprint **owns all of
  `db/repository.py`**; SP_011/012/013 only call it. Stated in each downstream plan.
- *Contract drift vs round-1 byte-identical guarantee* → additive-only; re-run the
  Phase-1 contract-hash check after merge before opening the slice worktrees.

## Success Criteria

- New fields + methods exist, additive, with passing unit + DB-integration tests;
  `uv run pytest test` green, `uv run mypy helixpay` clean.
- A round-1 slice (e.g. exposure) imports the amended contracts with zero changes.
- Branch `sprint/SP_009-contracts-v2` merges to the round-2 integration branch
  **before** SP_011/012/013 worktrees are cut.

### Pre-Implementation Review

> Foundational tier — review-iteration floor = 2 (GL-SELF-CRITIQUE). Architect +
> plan-blind code review over the contract diff and migration before implementation.

- **Iteration 1** (2026-06-10): architect-reviewer (independent) found 2 CRITICAL, 4 HIGH, 4 MEDIUM, 2 LOW. Verdict GO-WITH-CHANGES. Files reviewed: workspace/sprints/SP_009_contracts_v2.md, CLAUDE.md, helixpay/contracts/models.py, helixpay/contracts/repository.py, helixpay/db/schema.sql, helixpay/db/repository.py, helixpay/db/migrate.py, helixpay/ingest/contradict.py, helixpay/ingest/extract/grounding.py. Folded in: Citation.link_id (additive) so link citations carry an anchor; link-pair uniqueness index + pair-ordering for contradictions (UNIQUE(claim_a_id,claim_b_id) gives no protection when both NULL); get_links new param appended last & typed int (frozen signature, not an overload); claims/links natural-key indexes left byte-identical (idempotency regression guard added); idempotent-apply_schema test; first-write-wins documented for new provenance columns.
- **Iteration 2** (2026-06-10): code-reviewer (independent, plan-blind on diff intent) found 3 CRITICAL, 5 HIGH, 4 MEDIUM, 3 LOW. Verdict GO-WITH-CHANGES; same top-three (Citation.link_id, normalize contract, link-pair dedup) plus the full edge-case matrix for test_normalize.py. Files reviewed: helixpay/db/repository.py, helixpay/db/schema.sql, helixpay/db/migrate.py, helixpay/contracts/models.py, helixpay/contracts/repository.py, helixpay/ingest/contradict.py, helixpay/ingest/extract/grounding.py, test/integration/db/test_repository_integration.py, test/unit/contracts/test_models.py, test/unit/contracts/test_protocols.py, test/conftest.py. Locked normalize contract: returns (text, float|None); float path stays gated to pure numbers so "18 months" is not equal to "18 days" and the planted Q1 revenue/ARR conflict is preserved; word-numbers expand in the text form only; ~/approx strips with NO math.isclose tolerance widening. get_chunk_sources(chunk_ids) returns one citation per chunk (chunk-text prefix, no claim join); get_link_sources snippets from the link source chunk. Out of scope (deferred to SP_011 hand-off): rewiring contradict.py/grounding.py to import the shared util — this sprint is purely additive so today's imports keep working.

### Post-Implementation Review

- Iteration 1 — (pending; plan-blind over the amended contracts/schema/repository)
- Iteration 2 — (pending; re-verify against migrate + DB-integration runtime evidence)

## Hand-off (to SP_011 / SP_012 / SP_013)

- New `Claim`/`Link`/`Contradiction` fields and four `Repository` methods are live;
  consume them — do **not** re-edit `helixpay/contracts/**`, `schema.sql`, or
  `db/repository.py`.
- Import value normalization from `helixpay.ingest.normalize` — do not add a second copy.
- Merge order: SP_009 first; then the three slices branch from the post-merge commit.
