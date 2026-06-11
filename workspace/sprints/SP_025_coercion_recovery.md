---
sprint_id: SP_025
tier: Foundational
features: []
user_stories:
  - "As an AI agent reasoning over the ontology, when I ask 'who contributes to helixpay/core' or 'where is the hot-file activity', the answer must exist — so the ~20% of extracted signal (out-of-vocab relations like contributor/employed_by and claims about files/repos/tickets/projects) that coercion silently dropped is instead preserved, not discarded."
schema_touched: true
structure_touched: false
status: Complete
isolation: branch-only
branch: sprint/SP_025-coercion-recovery
worktree: ""
agent_owner: "main (operator-directed)"
dependencies: [SP_009, SP_014, SP_018, SP_024]
dev_dependencies: []
touches_paths:
  - helixpay/ingest/extract/coerce.py
  - helixpay/ingest/extract/schemas.py
  - helixpay/contracts/models.py
  - helixpay/ingest/assemble.py
  - helixpay/db/schema.sql
  - helixpay/db/repository.py
  - helixpay/ingest/extract/ledger.py
  - helixpay/ingest/resolve.py
  - helixpay/ingest/pipeline.py
  - helixpay/query/engine.py
  - test/unit/ingest/test_coerce.py
  - test/unit/ingest/test_validate.py
  - test/unit/ingest/test_extractor.py
  - test/unit/ingest/test_resolve.py
  - test/unit/query/test_engine.py
  - test/integration/db/test_repository_integration.py
  - workspace/sprints/SP_025_coercion_recovery.md
touches_checklist_items: [coerce-subject-type-fallback, coerce-link-verb-fallback, links-raw-verb-column, fallback-other-collapse-guard]
---

# SP_025: coercion recovery — stop dropping out-of-vocab claims & relations

## Sprint Goal

A drop diagnostic over the smoke corpus (SP_024 ledger split, then a 2-doc content dump)
showed ~20% of every document's extracted items were dropped at coercion as `unmappable_enum`
— and the dumped content proved these are **real signal, not noise**: claims about files
(hot-file ranks), repositories (commit counts), tickets (HX-LOY-487 detail), projects
(Confluence GA-slip), and relations like `contributor`, `employed_by`, `manages_account`,
`critical_path_collaborator`. The ontology models only 6 subject types and 5 link verbs, and
the catch-all `other` / generic `mentions` were **not** being used as the fallback — items
outside the vocab were dropped outright.

Fix: fall back instead of dropping.
- **Claims**: an unknown `subject_type` coerces to the existing `other` catch-all (the catch-all
  exists for exactly this; dropping was effectively a bug).
- **Relations**: an unknown verb coerces to the generic `mentions` edge, preserving the original
  verb in a new nullable `links.raw_verb` so an agent can still read the relation's semantics.

## Scope & boundaries

- IN: coerce fallbacks (claims→other, relations→mentions+raw_verb); `RelationOut.raw_verb` +
  `Link.raw_verb`; `links.raw_verb` column (additive, ALTER … IF NOT EXISTS, **out of the
  natural key** — mirrors SP_009 `document_id`); `add_link` persists it; `get_links` reads it
  back automatically (`SELECT *` + `Link.model_fields`); ledger counts the fallbacks as
  `subject_type_fallback` / `link_fallback` coercions (not drops).
- OUT: no widening of the *canonical* vocab (the 5 link types / 6 subject types are unchanged);
  no contradiction-detection change (unknown verbs land as `mentions`, outside conflict logic);
  no MCP/query-surface exposure of `raw_verb` yet (write-side preservation only — surfacing it
  on the tool layer is follow-up). A relation with **no** verb at all still drops (nothing to
  preserve). `validation_error` / `unparseable_as_of` still drop (genuine defects).

## Design notes

- `raw_verb` rides outside `links_natural_key`, so distinct verbs on the same (pair, as_of)
  dedupe to one `mentions` edge, first-verb-wins (acceptable; rare).
- `lossy_drops` (SP_024) consequently collapses on real docs: the dominant `unmappable_enum`
  losses become coercions, so the SP_015 completeness gate can finally approach 9/9 on a
  genuinely-complete extraction.

## Testing Strategy

TDD. Unit: claim unknown-subject_type → `other` (+fallback coercion, 0 drops); relation
unknown-verb → `mentions`+`raw_verb` (+link_fallback); known verb → no raw_verb; no-verb still
drops; extractor↔coerce wiring counts fallbacks not drops. Integration (db): `add_link`
persists and `get_links` reads back `raw_verb`. Result: 638 unit passed, mypy clean.

## Success Criteria

- Smoke re-record (SP_025 code) shows `lossy_drops` collapse vs the SP_024 baseline (144/9docs)
  while golden recall holds; the dropped real facts now persist.
- Full suite + mypy green; DB round-trip of `raw_verb` verified.

## Reviews

### Pre-Implementation Review

Foundational ⇒ ≥2 independent iterations (per `practices/GL-SELF-CRITIQUE.md`).

- **Iteration 1** — architect-reviewer, plan + as-built, adversarial; NEEDED=yes but **1 CRITICAL** (the `other` fallback feeds the SP_020 entity-snap via `_other_compatible` → a file/repo/ticket named like a `product`/`customer`/seeded entity COLLAPSES onto it, violating "keep distinct entities distinct") + 1 HIGH (first-verb-wins dedup re-drops distinct out-of-vocab verbs) + LOWs, REQUEST-CHANGES. Files reviewed: SP_025_coercion_recovery.md, coerce.py, resolve.py, pipeline.py, schemas.py, models.py, schema.sql, repository.py.
- **Iteration 2** — architect-reviewer, plan + as-built (post-fix), confirmation; CRITICAL **resolved** by the `allow_snap` guard + transient `raw_subject_type` (also independently verified the relation-endpoint path can't collapse — `entity_type=None` never reaches the snap/mint block); 0 CRITICAL / 0 HIGH, 1 MEDIUM (first-verb-wins accepted + documented, key-later) + 4 LOW, APPROVE. Files reviewed: SP_025_coercion_recovery.md, coerce.py, resolve.py, pipeline.py, schemas.py, models.py, schema.sql, repository.py, assemble.py, query/engine.py, ledger.py + tests.

### Post-Implementation Review

Foundational ⇒ ≥2 independent iterations; plan-blind (Rule 5 — reviewer sees only code + tests).

- **Iteration 1** — code-reviewer, plan-blind over the diff; 0 CRITICAL / 0 HIGH, 2 MEDIUM (`raw_verb` not surfaced in `get_relationships`; first-verb-wins silent loss) + 3 LOW (stale coerce docstring; `SELECT *` fragility; nominal-subject `other` noise) — folded: surfaced `raw_verb` in `engine.get_relationships` + test; corrected coerce docstrings; first-verb-wins documented. End-to-end `raw_verb` persistence chain verified; 113 tests pass. Files reviewed: coerce.py, schemas.py, models.py, assemble.py, schema.sql, repository.py, validate.py, query/engine.py + tests.
- **Iteration 2** — code-reviewer (Stage-5), plan-blind over commit bac2f0f; 0 CRITICAL / 0 HIGH, 2 MEDIUM (seeded-`other` same-name residual collapse — was UNTESTED; `LOSSY_DROP_REASONS` trap) + 2 LOW, **SHIP** — folded: added `test_fallback_other_still_attaches_to_a_same_named_seeded_other` pinning the accepted residual. allow_snap guard correct; SP_020 snap preserved; `raw_verb` round-trips. 188 targeted tests pass. Files reviewed: commit bac2f0f (coerce.py, resolve.py, pipeline.py, schemas.py, ledger.py, query/engine.py + tests).

**Verification after folds:** full unit suite 660 passed / 1 skipped; mypy clean (72 files); migration applies the `raw_verb` column (28 statements) and the DB round-trip + 35/36 integration pass against pgvector pg16. The 1 failure (`test_org_subtree_as_of_filters_reporting_lines`) is **pre-existing and unrelated** — this sprint's diff contains no org/seed code. The HIGH first-verb-wins dedup is accepted + documented; keying `mentions` edges on `raw_verb` is a scoped follow-up.

## Documentation & Deploy

- CLAUDE.md gotcha (coercion fallbacks + raw_verb out-of-key + the allow_snap collapse guard)
  **deferred**: CLAUDE.md is over its 20,000-byte hard limit from concurrent SP_026–028 edits;
  the gotcha lands once that file is reconciled (left untouched here).
- Schema change ships with the fresh full-corpus extraction (migrate adds the column; the
  prod transfer is pg_dump→restore, which carries the new column). **Deploy held per operator
  (2026-06-11):** the additive `raw_verb` column + coercion code are committed on
  `sprint/SP_025-coercion-recovery`; no prod push (would entangle a concurrent agent's
  SP_026/027/028). The recovery's value materialises only on a fresh paid full-corpus
  re-extraction, which remains separately spend-gated.
