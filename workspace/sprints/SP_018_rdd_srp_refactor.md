---
sprint_id: SP_018
tier: Standard
features: [rdd-citations-extract, rdd-extractor-decompose, rdd-pipeline-assemble, rdd-validator-scope]
user_stories: []
schema_touched: false
structure_touched: false
status: Complete
isolation: branch-only
branch: sprint/SP_018-rdd-srp-refactor
worktree: ""
agent_owner: "Claude (rdd-srp-refactor)"
fix_type: ""
dependencies: []
dev_dependencies: []
touches_paths:
  - helixpay/query/synthesis.py
  - helixpay/query/citations.py
  - helixpay/ingest/extract/extractor.py
  - helixpay/ingest/extract/validate.py
  - helixpay/ingest/extract/glean.py
  - helixpay/ingest/extract/grounding.py
  - helixpay/ingest/pipeline.py
  - helixpay/ingest/assemble.py
  - .validators.yml
  - test/unit/query/*
  - test/unit/ingest/*
touches_checklist_items: [rdd-citations-extract, rdd-extractor-decompose, rdd-pipeline-assemble, rdd-validator-scope]
---

# SP_018: RDD/SRP Refactor — separate domain logic from I/O at the three hot spots

> Behavior-preserving refactor. **No** contract, schema, or DB-repository change. Driven by
> the `/my-rdd-review` audit (4 parallel Explore passes) against `practices/GL-RDD.md`. The
> mechanical size gate already PASSES (largest module `repository.py` = 622 lines, < 800
> warn). These are the genuine **SRP / "Domain Logic + I/O + Utilities mixed"** violations
> GL-RDD says to ALWAYS split — filtered down from the audit's full list to the three with
> real test-leverage value, plus the validator-scope fix that gives the size gate teeth.

## Sprint Goal

Pull pure, deterministic domain logic out of three functions where it is currently
interleaved with Repository / LLM / embedding I/O, so each pure rule is unit-testable
without a DB or API keys, and each caller becomes thin orchestration. Restore the GL-RDD
module-size sensor's scope so it actually scans `helixpay/`.

**Non-goals:** no behavior change (every existing `test_*.py` stays green unedited except
where a test reaches into a moved private helper), no `repository.py` split (cohesive
Repository pattern per GL-RDD; embedded logic is small + schema-locked), no touching the
in-flight SP_013/014/015/016 working-tree changes beyond the files listed above.

## Scope

### F-1 (`rdd-citations-extract`) — CRITICAL: `synthesis.enforce_citations`
The 100-line function mixes pure citation resolution (marker validation, ref-id bucketing,
verbatim-evidence override, sentence filtering, dedup, confidence clamp) with **3 Repository
reads** (`get_sources` / `get_chunk_sources` / `get_link_sources`).

- [ ] New `helixpay/query/citations.py` — pure, no `Repository`:
  - `collect_ref_ids(raw_sentences, facts) -> tuple[list[int], list[int], list[int]]`
    (claim / chunk / link ids, in first-seen order, deduped).
  - `resolve_cited_sentences(raw_sentences, facts, claim_cites, chunk_cites, link_cites, raw_confidence) -> tuple[str, list[Citation], list[int], float]`
    — sentence keep/dedup + confidence computation, incl. the `FALLBACK_ANSWER`
    short-circuit and the post-dedup confidence math (`min(0.9, 0.3 + 0.15*len(citations))`
    fallback, NaN/inf clamp) lifted verbatim from `synthesis.py:318-331`.
- [ ] **Verbatim-evidence override stays in `synthesis.py`** (per Stage-3 review): it needs
  the resolved `Citation` objects, so after the 3 repo reads the caller applies
  `claim_cites[cid] = claim_cites[cid].model_copy(update={"snippet": ev})` and passes the
  **already-overridden** maps into `resolve_cited_sentences`. The pure function never
  re-derives evidence.
- [ ] `enforce_citations` in `synthesis.py` becomes: `collect_ref_ids` → 3 repo reads →
  build cite maps + apply evidence override → `resolve_cited_sentences`. The only I/O left
  is the three `repo.*` calls.

### F-2 (`rdd-extractor-decompose`) — CRITICAL: `ChunkExtractor` (CC ~31)
One class bundles gleaning-loop orchestration + LLM call + coerce/validate/loss-accounting +
gleaning dedup utilities.

- [ ] New `helixpay/ingest/extract/validate.py` — `validate_items(raw_items, schema, kind, ctx, ledger) -> list`
  (the current `_coerce_and_validate` body, ledger + ctx passed explicitly). Separates the
  per-item coerce→validate→record-loss concern from extraction orchestration. This is the
  bulk of the CC reduction. Must NOT import `extractor.py` (imports only `coerce`, `ledger`,
  `schemas`, `Chunk`/`ChunkContext` types).
- [ ] New `helixpay/ingest/extract/glean.py` — pure gleaning utilities, no LLM/ledger:
  `claim_key`, `rel_key`, `dump_already`, `estimate_tokens`, and
  `merge_new(claims, relations, extra, seen, seen_rel) -> bool`.
  **Invariant (behavior-preserving):** append *new* claims first (in `extra.claims` order),
  then *new* relations (in `extra.relations` order); mutate `seen`/`seen_rel` **in place** so
  they carry across passes; return the **OR** of "added a claim" / "added a relation" in this
  call. Identical to the current in-place loop at `extractor.py:154-168`.
- [ ] **Grounding stays put.** `_apply_grounding` (which already delegates the pure `grade`
  to `grounding.py`) keeps its `ctx`-bearing `source_uri` log line in the extractor — moving
  it would drop that log field for marginal CC gain. (Revised per Stage-3 review.)
- [ ] `ChunkExtractor` keeps only `extract` (orchestrate), `_glean` (loop calling glean.py +
  `_run_pass`), `_run_pass` (render + `call_structured` + `validate_items`), and the thin
  `_apply_grounding`. CC drops well under the trigger.

### F-3 (`rdd-pipeline-assemble`) — HIGH: `pipeline._ingest_document` / `_maybe_supersede` (CC ~27)
Pure domain rules (claim/link assembly from extraction output, self-loop drop, same-source
supersession decision) are inlined into DB-orchestration loops.

- [ ] New `helixpay/ingest/assemble.py` — pure, no `Repository`:
  - `build_claim(claim_out, *, subject_id, predicate, chunk_id, document_id, doc_as_of: Optional[date]) -> Claim`.
    **`doc_as_of` is `doc.as_of` (a `date`), NOT the `ChunkContext` isoformat string** (per
    Stage-3 review): `Claim.as_of` is a `date` field; fallback reproduces `claim_out.as_of_date() or doc.as_of`.
  - `build_link(rel, *, from_id, to_id, chunk_id, doc_as_of: Optional[date]) -> Optional[Link]`
    — returns `None` on self-loop (`from_id == to_id`). The caller logs the self-loop
    **and keeps it log-only — no `dropped_mentions` increment** (matches current
    `pipeline.py:204-208`). Unresolved-mention counting stays in the caller, before `build_link`.
  - `should_supersede(existing, new_claim, *, prior_uri, source_uri) -> bool`
    (the `_maybe_supersede` decision in order: concrete `as_of`, skip self/already-superseded,
    strictly-older, value conflict via `values_conflict`, same source). I/O —
    `get_claims`/`get_sources`/`supersede_claim` — stays in pipeline.
- [ ] `_ingest_document` / `_maybe_supersede` delegate to the pure helpers; behavior identical.

### F-4 (`rdd-validator-scope`) — tooling: GL-RDD size sensor has no teeth
`.validators.yml` `module_size.source_roots: [src, scripts, skills]` — there is no `src/` or
`skills/` dir, so the sensor scans nothing real (all code is in `helixpay/`).

- [ ] Set `module_size.source_roots` to `[helixpay, scripts]`. Confirm
  `validators/validate_module_size.py` runs clean (no file > 2000 fail; largest is 622 so
  expect WARNs only, not FAIL — visible debt). Self-improvement scope (rule #15).
- [ ] **Deliberate deferral:** `doc_freshness.source_roots` carries the same dead
  `[src, scripts, skills]`. Left untouched this sprint — repointing it at `helixpay` would
  surface a flood of unrelated doc-freshness warnings outside this refactor's blast radius.
  Noted here for a future tooling sprint.

## Deferred RDD-audit findings (below the ALWAYS-SPLIT bar — for Stage-5 traceability)
The `/my-rdd-review` audit flagged more than these four. Explicitly **not** in scope because
each is acceptable per GL-RDD (cohesive pattern, or a single advisory trigger, not the
domain+I/O+utilities ALWAYS-SPLIT trigger):
- `db/repository.py` (622 lines) — cohesive Repository pattern; embedded logic (disambiguation,
  contradiction ordering, `canonical_predicate`) is small + schema-locked. Monitor only.
- `query/engine.py` `_gather_*` budget heuristics, `api/app.py` `wire_engine()` — MEDIUM, real
  but lower-leverage; candidates for a follow-up sprint.
- `ingest/replay.py`, `ingest/llm.py`, `ingest/contradict.py`, `ingest/resolve.py`,
  `ingest/embed.py`, `audit/invariants.py`, `loaders/base.py` — cohesive single-seam modules
  exceeding at most one advisory CC trigger. No split.

## Technical Approach

Each F-item, in TDD order:
1. Write the new pure-module test file first (RED — module/function does not exist yet).
2. Create the pure module to make it pass (GREEN).
3. Refactor the caller to delegate; run the **existing** behavioral suite for that area
   (`test_synthesis.py` / `test_extractor.py` / `test_pipeline.py`) as the regression net.
4. Adjust only those existing tests that reached into a now-moved private helper (none
   expected for F-1/F-3 since they hit public APIs; F-2 may touch tests that patched private
   methods — migrate them to the new module rather than deleting coverage).

## Testing Strategy (per GL-TDD.md)
- **New** tests: `test/unit/query/test_citations.py`, `test/unit/ingest/test_validate.py`,
  `test/unit/ingest/test_glean.py`, `test/unit/ingest/test_assemble.py` — pure-function
  coverage incl. edge cases (empty/adversarial input, self-loop, non-finite confidence,
  cross-source non-supersession, temporal-distinct dedup).
- **Preserved** nets: existing `test_synthesis.py`, `test_extractor.py`, `test_pipeline.py`
  must stay green and assert the public behavior is unchanged.
- **Obsolete tests:** removed only if a test asserted an implementation detail that the
  refactor legitimately eliminates; behavioral assertions are migrated, never dropped.
- Gate: `uv run pytest test`, `uv run mypy helixpay`, then `dev-gateway.py --stage manual`.

## Success Criteria
- [ ] F-1..F-4 implemented; four new pure modules with no `Repository`/LLM import.
- [ ] All new + existing unit tests pass; mypy clean; module-size validator clean against `helixpay`.
- [ ] `ChunkExtractor`, `enforce_citations`, `pipeline._ingest_document` each reduced to
  orchestration; no behavior change observable through public APIs.
- [ ] Stage 5 plan-blind review run; blocking findings fixed; docs reconciled.
