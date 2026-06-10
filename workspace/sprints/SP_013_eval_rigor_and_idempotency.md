---
sprint_id: SP_013
tier: Standard
features: [golden-grow, match-function-spec, contradiction-scoring, ingest-idempotency]
user_stories: []
schema_touched: false
structure_touched: true
status: Complete
isolation: git-worktree
branch: sprint/SP_013-eval-idempotency
worktree: .claude/worktrees/SP_013
agent_owner: "Agent E (eval + ingest-idempotency)"
fix_type: ""
dependencies: []
dev_dependencies: []
touches_paths:
  - eval/run.py
  - eval/models.py
  - eval/questions.yaml
  - eval/README.md
  - test/golden/facts.yaml
  - test/golden/**
  - helixpay/cli.py
  - test/unit/api/test_cli.py
touches_checklist_items: [eval-grow-golden, eval-wilson-ci, eval-match-function-spec, eval-macro-recall, eval-contradiction-3class, eval-freshness-split, eval-entity-id-assert, ingest-known-hashes-wire, ingest-surface-skipped]
---

# SP_013: Eval Rigor + Ingest Compute-Idempotency

> **Partially depends on SP_009** (only `Repository.known_content_hashes` for the ingest
> idempotency item; the eval items are independent). Branch from the post-SP_009 commit.
> Does **not** edit contracts, schema, or `db/repository.py`.

## Sprint Goal

Make the eval trustworthy enough to certify the 85% claim, and make re-ingestion
near-free — from `research/evaluation-and-ground-truth-best-practices.md` (P0/P1) and
`research/ingest-append-and-task-fit.md` (the one HIGH item):

**Eval rigor**
1. **Grow the golden set to ≥30–50 bar facts** and **report Wilson confidence
   intervals** on precision/recall (not a bare 4/15 ratio), acknowledging clustered SE.
2. **Specify the match function** in `eval/run.py`: `source_uri` exact, `as_of` exact
   (or ±N days, documented), subject by resolved `entity_id`, value via shared
   `normalize_value`; **report macro recall per predicate**, not just micro.
3. **WikiContradict 3-class contradiction scoring** (Correct / Partial / Incorrect) and
   assert **both** claim ids appear in `AnswerBundle.contradictions`.
4. **Separate freshness from contradiction** — add a prefer-fresh-and-say-so question
   distinct from the surface-both case; report As-of Correctness.
5. **Assert resolved `entity_id` for name-collision facts** (two Marias / two Tans) and
   add **predicate-synonym golden pairs** (ARR ≡ "annual recurring revenue" → one key).

**Ingest compute-idempotency**
6. **Wire `already_ingested=known_content_hashes().__contains__`** as the default in the
   `helixpay ingest` entrypoint, turning a re-run from full Voyage+Anthropic spend into a
   near-free no-op; **surface `skipped_documents`** in the CLI summary so idempotency is
   observable.

## Current State

- `test/golden/facts.yaml` = 15 bar facts; `eval/run.py` reports a bare ratio; match
  logic is presence-based; contradiction check is binary; no per-predicate macro recall;
  no `entity_id` assertion; freshness and contradiction are entangled.
- `helixpay ingest` always runs the full pipeline; `already_ingested` is supported by
  `pipeline.run` but not wired; `skipped_documents` is computed but not surfaced.

## Desired End State

- Golden set ≥30–50 facts with per-predicate macro recall + Wilson CIs; 3-class
  contradiction scoring with both-id assertion; a distinct freshness question;
  `entity_id` + predicate-synonym assertions.
- `helixpay ingest` is a near-free no-op on unchanged data and prints
  `skipped N unchanged`.
- All offline except an optional paid confirmation; verified on the SP_010 replay DB.

## Scope

In: `eval/**`, `test/golden/**`, and the `helixpay ingest` CLI entrypoint. Out: the
`known_content_hashes` repository method (SP_009), answer-shape changes it scores
(SP_012), recall-fix data (SP_010).

## Technical Approach

- **Golden growth** — hand-label additional facts by eye from `data/` (same discipline as
  the existing oracle), ≥2 per format, including the name-collision and predicate-synonym
  cases; keep them out of any few-shot prompt (leakage discipline, DEV_RULES §12).
- **Match + reporting** — factor the match function explicitly; import shared
  `normalize_value`; compute macro-per-predicate recall + Wilson intervals in
  `eval/run.py`; extend `eval/models.py` report shape.
- **Contradiction scoring** — 3-class verdict + both-claim-id assertion in the answer
  check.
- **Idempotency** — in `helixpay/cli.py ingest`, build `known = repo.known_content_hashes()`
  and pass `already_ingested=known.__contains__` to `pipeline.run`; print the skipped count.

## Testing Strategy

- `test/golden/test_golden.py` — the grown set loads; every bar fact has the required
  fields; predicate-synonym pairs canonicalize to one key.
- `test/golden/test_harness.py` — macro-recall arithmetic; Wilson interval correctness;
  3-class contradiction verdicts; freshness check distinct from contradiction check;
  `entity_id` assertion for a name-collision fact.
- `test/unit/api/test_cli.py` — `ingest` passes `already_ingested` and prints the skipped
  count; a second run over unchanged data does zero extraction (mock asserts no extractor
  calls).

## Risks & Mitigations

- *`eval/run.py` overlap with SP_010 (recall measured by eval)* → SP_010 changes data/
  seed/normalize, not eval structure; this sprint owns eval structure. Merge order:
  SP_010 → SP_013; resolve the shared `normalize_value` import at integration. Declared.
- *Golden growth introduces a wrong fact* → two-pass eyeball + cite the exact source line
  in each fact's `note`, mirroring the existing oracle.
- *Idempotency hides a genuinely changed file* → key is `content_hash`; a changed file is
  a new hash and re-ingests (supersede path intact). Documented.

## Success Criteria

- Golden ≥30–50; macro-per-predicate recall + Wilson CIs reported; 3-class contradiction
  scoring with both-id assertion; distinct freshness question; `entity_id` + synonym
  assertions.
- `helixpay ingest` re-run on unchanged data does zero LLM calls and prints the skipped
  count.
- `uv run pytest test` green; `uv run mypy helixpay` clean.

### Pre-Implementation Review

> Standard tier — floor = 2.

- **Iteration 1** — architect-reviewer + code-reviewer, both **GO-WITH-CHANGES**
  (independent, plan-only). Converging findings + resolutions (folded into Technical
  Approach below):
  - *C1 — shared `normalize_value` swap breaks the test import surface.*
    `test_harness.py` imports `eval.run.normalize_value` (str) and asserts substring
    equality. The shared util returns `(text, numeric)`. **Resolution:** keep
    `eval.run.normalize_value` as the str helper (URI logic + back-compat); route
    *value* equality through shared `helixpay.ingest.normalize.values_equal`. No
    import-name collision; existing parametrized test keeps passing.
  - *H1 — oracle independence: `eval/` importing a build-slice util.* **Resolution:**
    `normalize.py` was *designed* as shared substrate — its own docstring names "the
    eval matcher (predicted-vs-gold equivalence — SP_013)" as a consumer. Accept +
    document the coupling in the eval module docstring, and keep an eval-OWNED
    golden-pair equality test so a normalizer regression is still caught by the
    oracle's own assertions. Do not relocate the module (out of scope / not in
    `touches_paths`).
  - *C2 — both-claim-id assertion.* `Contradiction` already carries
    `claim_a_id`/`claim_b_id` (ints). **Resolution:** assert the surfaced
    contradiction matching the golden `subject`+`predicate` has **both** ids
    non-null and distinct (neither side dropped) — no contract change, no
    golden-slug→DB-id mapping.
  - *H2 — CLI repo construction under-specified.* **Resolution:** build ONE repo
    lazily inside `_run_ingest` (import `PostgresRepository` inside the function,
    not at module level), thread it as `repo=` into `pipeline.run` AND use
    `repo.known_content_hashes().__contains__`; on DB-unavailable, degrade to
    `already_ingested=None` (full ingest) with a warning so the existing
    import-isolation property holds.
  - *H3 — existing CLI mock breaks.* `fake_run(path)` rejects new kwargs.
    **Resolution:** widen to `fake_run(path, **kwargs)` and add a dedicated
    zero-extractor-call re-ingest test.
  - *M1 — report-shape bloat.* **Resolution:** add `predicate` to `FactVerdict`;
    macro-per-predicate recall + Wilson interval as small named helpers/properties,
    not precomputed maps stuffed into `ExtractionReport`.
  - *M2 — `touches_paths` mislabel.* The real question file is `eval/questions.yaml`,
    not `test/golden/questions.yaml`. **Resolution:** path list corrected above.
  - *M3 (defn) — macro recall + freshness.* macro recall = mean over predicates with
    ≥1 bar fact of `found/total`; the freshness item reuses the existing
    `uses_freshest_as_of` gating check on a NEW prefer-fresh question and reports
    "As-of Correctness" (reported, not gated). 3-class scoring lives in a NEW typed
    record, not overloaded onto the boolean `CheckResult`/`KNOWN_CHECKS` contract.
  - *Wilson edges* (H2/code): guard `n==0 → (0.0, 0.0)`; test `p=0` and `p=1`.
- **Iteration 2** — re-review over the revised plan (architect-reviewer, code-verified):
  all four CRITICAL/HIGH findings **RESOLVED** with concrete mechanisms inside the
  declared `touches_paths`; no contract/schema change required; ≤50% path expansion.
  **Verdict: GO.** Two-iteration floor satisfied with no remaining CRITICAL/HIGH.

### Post-Implementation Review

- **Iteration 1** — two independent plan-blind reviewers (code-reviewer + adversarial
  general-purpose) over the staged code+tests diff; both **FIX-REQUIRED**, all findings
  resolved + covered by new tests:
  - *H1 (code-reviewer, HIGH) — numeric substring false-positive.* `_values_match`'s text
    fallback let `"41"` match `"241"` (and `"412"`/`"4120"`) — inflating recall on the
    commit-count collision probes. **Fixed:** block the substring fallback when BOTH sides
    parse as numbers (one-numeric-one-text still falls back, so the un-parseable
    `"−SGD 2.1M"` still matches `"-2.1M"`). New parametrized test.
  - *MEDIUM (adversarial) — subject-blind contradiction scoring.* `score_contradiction`
    matched on predicate only, so a spurious conflict on the WRONG subject scored CORRECT.
    **Fixed:** `score_contradictions` resolves the golden subject and `score_contradiction`
    requires the surfaced row's `subject_entity_id` to match (predicate-only fallback when
    unresolved). New `test_contradiction_is_subject_aware`.
  - *M1 — collision zip length mismatch* → guard added (malformed probe fails loudly).
  - *M2 — `interview-silva-role` format mislabel* → relabeled `silva-role` `format: md`
    (its true source org-chart.md); interview keeps 3 bar facts. collision_group (not
    format) pairs it with `santos`.
  - *L1 — misleading link "unresolved" message* → fixed (`fe.id is None` case).
  - CLEAN: Wilson math (incl. n=0/p=0/p=1 edges), macro recall, collision pass/fail, CLI
    single-repo idempotency wiring + DB-unavailable degrade, and all 39 grown golden facts
    verified true-to-source by the adversarial reviewer against raw `data/` (PDFs, HTML,
    code tables, org links).
- **Iteration 2** — re-verified after fixes: `uv run pytest test` → 329 passed, 33 skipped
  (DB-gated); `uv run mypy helixpay eval` clean. Macro-per-predicate recall + Wilson CI
  render in `eval.run` output; zero-extractor-call re-ingest is proven by the pipeline unit
  test `test_already_ingested_skips_embed_and_extract` (extractor calls == 0) plus the new
  CLI wiring test. Live recall on the SP_010 replay DB is the certification step (hand-off).
- **Iteration 3** — follow-up adversarial review of the contradiction scorer; 2 HIGH +
  3 MEDIUM, all resolved + tested (`uv run pytest test` → 332 passed, 33 skipped; mypy clean):
  - *H1 — over-credit on unannotated rows.* A surfaced contradiction with
    `subject_entity_id=None` was scored CORRECT even when the golden subject WAS resolved,
    so an engine that never annotates subjects inflated the score. **Fixed:** the subject
    and both-id axes are split — only a *subject-confirmed* row (or no resolved golden
    subject) earns CORRECT; an unannotated row caps at PARTIAL. New test.
  - *H2 — throwing model scored cleaner than a wrong one.* If `ask()` raised on a
    `contradiction_ref` question, the contradiction was silently skipped, not scored.
    **Fixed:** `score_contradictions` emits INCORRECT when the question has no bundle. New test.
  - *MEDIUM — dangling contradiction ref:* `load_golden` now asserts each
    `claim_a`/`claim_b` references a real fact id (new test). *`_worst` misnamed* → renamed
    `_best_verdict` (it returns the best-ranked verdict). *Phantom `""` predicate bucket:*
    benign by construction — `check_extraction` always sets `predicate`, and the oracle
    shape test (`test_every_fact_has_core_fields`) already rejects an empty golden predicate,
    so no `""` bucket can reach `macro_recall`; left as-is with this rationale.

## Hand-off

- The grown golden set + macro-per-predicate reporting is the certification surface for
  the 85% claim; the recall and provenance slices are graded against it on the replay tier.
