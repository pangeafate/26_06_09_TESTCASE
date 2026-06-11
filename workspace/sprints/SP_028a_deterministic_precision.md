---
sprint_id: SP_028a
tier: Foundational
features: []
user_stories:
  - "As the operator, the contradiction set drops from 266 mostly-spurious rows to a real number — WITHOUT any LLM spend and WITHOUT losing a single genuine conflict — because three deterministic levers run in a single-writer post-ingest sweep: a sign/currency-position normalize fix, a data-driven predicate-cardinality pre-filter that skips genuinely multi-valued predicates, and a value-pair dedup that collapses pairwise inflation to one representative per distinct conflict."
schema_touched: false
structure_touched: false
status: Complete
isolation: shared-tree
branch: sprint/SP_023-graph-temporal-tools
worktree: ""
agent_owner: "main (operator-directed)"
dependencies: [SP_009, SP_026, SP_027]
dev_dependencies: []
touches_paths:
  - helixpay/ingest/normalize.py
  - helixpay/ingest/predicate_cardinality.py
  - scripts/recompute_contradictions.py
  - test/unit/ingest/test_normalize.py
  - test/unit/ingest/test_predicate_cardinality.py
  - test/unit/ingest/test_sweep_dedup.py
  - CLAUDE.md
  - workspace/sprints/SP_028a_deterministic_precision.md
touches_checklist_items: [norm-sign-position-fix, predicate-cardinality-table, sweep-skip-setvalued, sweep-valuepair-dedup, sweep-single-writer, oracle-measure, claude-md-gotcha]
---

# SP_028a: Deterministic contradiction precision — $0, no real conflict lost

## Sprint Goal

Collapse the 266 mostly-spurious contradiction rows toward the ~30-40 genuine distinct conflicts,
**deterministically and at $0**, with **zero real conflicts lost**, via a single-writer
clear-then-rewrite sweep applying three levers. This is the cheap, low-risk half of the split
(SP_028 Stage-3 review): the LLM adjudication (semantic recall, cross-predicate, the residual
format-text spurious like `VP Eng`/`VP Engineering`) is SP_028b; entity-merge is SP_029.

## Grounded leak data (live `helixpay_full`, 266 rows)

| predicate | rows | class | lever |
|---|---|---|---|
| ga_target | 86 | functional, **pairwise-inflated** (one real June-vs-Q3 story) | **value-pair dedup** |
| completion_target | 37 | functional, inflated | value-pair dedup |
| reports_to | 36 | link, inflated | value-pair dedup (by to-entity pair) |
| ebitda | 16 | functional, **format-equivalent** (`SGD -2.1M` vs `-SGD 2.1M`) | **normalize sign-fix** |
| net_revenue/refunds/gross_revenue | 10/10/9 | **sub-entity breakdown** (Açaí per product) | **deferred** (entity-specific → SP_028b/029) |
| cross_pr_reviews | 10 | breakdown (per reviewer-pair) | deferred |
| weekly_activity, pain_point, q1_miss_driver, desired_feature, tool_used_for, weekly_recurring_meeting, responsibilities, data_quality_weakness, attendee | 6,3,3,2,1,1,1,1,1 | **SET-VALUED** (multiplicity is legitimate) | **cardinality drop** |
| revenue, nps, revenue_vs_plan, title, board_meeting_date, role, … | 9,5,4,3,3,2,… | functional; some are text-format-equivalent (`VP Eng`/`VP Engineering`) | **deferred to SP_028b** (text normalization is unsafe in shared normalizer — see Risk) |

## The three levers (all deterministic, $0)

### 1. `normalize.py` — sign/currency-position fix ONLY
`-SGD 2.1M` today: currency-strip leaves `- 2.1m` (space after minus) → `_parse_number` fullmatch
fails → returns `None` (text) while `SGD -2.1M` → `-2.1e6` (numeric) → unequal → **spurious
conflict** (16 ebitda rows). Fix: after currency stripping, collapse the space between a leading
sign and the digits before `_parse_number`. **Scope-limited to sign/currency position.** NO
date-format normalization (review C1: `2026-05-12 ≡ May 12` drops the year → cross-year
false-equality → suppresses real conflicts + corrupts the oracle scorer). NO rounding tolerance
(review H1: any tol risks dropping the planted 14.2M-vs-13.9M / 7-vs-8 conflicts). `values_equal`
stays exact.

### 2. `predicate_cardinality.py` — data-driven cardinality table
`cardinality(predicate) -> "functional" | "set_valued" | "breakdown" | "unknown"`. The sweep
**drops a cluster ONLY when its predicate is explicitly `set_valued`** (multiplicity is legitimate;
listing two pain_points is not a conflict). `functional`, `breakdown`, and **`unknown` are KEPT**
(the safe default — an unclassified predicate is never silently dropped, so no real conflict is
lost). The `set_valued` set is **grounded in the live data above**, each entry cited. `breakdown`
is NOT acted on in SP_028a (it is entity-specific — `gross_revenue` is a real company metric *and*
an Açaí per-product breakdown; dropping by predicate would lose the real one — deferred).
Subsumes the scattered `_SINGLE_VALUED_LINK_TYPES`/`_TARGET_PREDICATES` knowledge over time
(Rule 18; v1 references them, does not duplicate).

### 3. value-pair dedup — collapse pairwise inflation
86 `ga_target` rows = one "June vs Q3" story exploded across (many June claims) × (many Q3 claims).
After detection, within a `(subject, predicate)` group keep **one representative contradiction per
distinct normalized value-pair** `{normalize_value(a), normalize_value(b)}`; do not write the
redundant pairs. The representative still cites two real claims with provenance, so the conflict +
its sources are preserved — we drop only redundant source-combinations. (Ontology check: "first-
class contradiction rows" is satisfied by one row per distinct *conflict*, not per source-pair;
documented.)

## Single-writer sweep (review C1 fix)

`recompute_contradictions.py` becomes the one writer: `clear_contradictions()` → for each
`distinct_claim_groups()`/`distinct_link_groups()` **skip set_valued predicates** → run the
existing `detect()`/`detect_link_conflicts()` (now benefiting from the normalize sign-fix) →
**value-pair dedup** the resulting rows → write. Deterministic `detect()` is Stage-1 *inside* the
sweep, never a concurrent writer, so the `UNIQUE(claim_a_id,claim_b_id)` collision (review C1) can't
arise. No `add_contradiction`/schema change.

## TDD (Rule 1 — failing test first)

1. `test_normalize.py`: `values_conflict("-SGD 2.1M","SGD -2.1M") is False` (format-equal) AND
   `values_conflict("-SGD 2.1M","SGD 2.1M") is True` (sign flip = real) → RED → implement sign-fix.
   Plus regression pins: existing equality/conflict cases unchanged (the 7 normalize callers).
2. `test_predicate_cardinality.py`: `cardinality("pain_point")=="set_valued"`,
   `cardinality("ga_target")=="functional"`, `cardinality("revenue")!="set_valued"`,
   `cardinality("totally_unknown_pred")=="unknown"` → RED → implement grounded table.
3. `test_contradict.py`: a set-valued group yields 0 contradictions via the sweep; a `(subject,
   predicate)` group with 3 June + 2 Q3 claims yields **1** deduped row not 6 → RED → implement
   skip + dedup in the sweep.
4. **Measurement (reported, not asserted, $0):** run the sweep over `helixpay_full`; print the new
   total + `eval.contradiction_recall` scorecard. Acceptance: total drops materially (target the
   ebitda-16 + set-valued ~19 + ga/completion/reports dedup ~140 → ~40-ish), and the oracle
   **baseline `confluence-ga-target` stays caught** (dedup keeps one representative ga_target row).

## Acceptance

- 266 → a materially smaller, defensible number; **zero genuine conflicts lost** (oracle baseline
  preserved; sign-fix is format-only; set_valued predicates are genuinely multi-valued).
- Reproducible/idempotent: re-running the sweep is a no-op (clear-then-rewrite is deterministic).
- `uv run pytest test` + `uv run mypy helixpay` green; no regression in the eval golden matcher.
- `eval/contradiction_recall.py` only gains an optional CLI/measurement helper — stays import-blind
  to `helixpay/` (its no-leakage guard intact).

## Risk

- **`normalize.py` is shared substrate (7 callers: contradiction detect, eval matcher, consensus
  rollup, grounding, audit).** The sign-fix is additive and narrow, but Stage-3/5 reviews must
  confirm no existing `values_equal`/`normalize_value` behavior changes. Comprehensive regression
  pins included. (This is why the sprint is **Foundational** despite being small.)
- **value-pair dedup is a semantic change** (one row per distinct conflict, not per source-pair).
  Flagged for review as the key design decision; ontology-justified above.
- Text-format-equivalent spurious (`VP Eng`/`VP Engineering`, `2026-05-12`/`May 12` dates,
  `11% under plan`/`-11%`) are **deliberately NOT** killed here — safe text/date normalization is
  unsafe in the shared normalizer; they go to SP_028b's LLM pass. `log()` the residual honestly.

## Stage 3 / Stage 5 review

Foundational → ≥2 plan + ≥2 post-impl iterations, plan-blind at Stage 5.

## Stage-3 review (2 independent contexts) + resolved decisions

Architect + code reviewers, 2026-06-11. **0 CRITICAL — approach sound.** Resolved:

- **Dedup mechanism (code H1):** a sweep-level `DeduplicatingRepoWrapper` intercepts
  `add_contradiction` per group; **`detect()` / `detect_link_conflicts()` are NOT modified**
  (zero break to the 27 existing contradict tests). Claim dedup key =
  `frozenset{normalize_value(a_value), normalize_value(b_value)}` per `(subject_id, predicate)`;
  the surviving representative's `note` carries both values (protects the unresolved-subject
  oracle path — architect M3). Link dedup key = `frozenset{to_entity_id_a, to_entity_id_b}` per
  `(from_entity_id, link_type)` — NO `normalize_value` on links (architect M4).
- **Cardinality filter scope (code H2):** applied to the **claim-group loop ONLY**; the link loop
  keeps its `_SINGLE_VALUED_LINK_TYPES` gate inside `detect_link_conflicts`. A test pins
  `cardinality(<link_type>)=="unknown"` so a link predicate is never mistakenly skipped.
  `should_skip_predicate(p) := PREDICATE_CARDINALITY.get(p)=="set_valued"` (unknown/functional/
  breakdown all KEEP). Test pins `should_skip_predicate("gross_revenue") is False` (breakdown
  deferred, not skipped).
- **Double-path (architect M5):** the **sweep is the canonical post-ingest contradiction step**
  (choice (a)) — inline ingest-time `detect()` still writes raw rows, the clear-then-rewrite sweep
  is the source of truth and must run after ingest. v1 does NOT push skip/dedup into `detect()`
  (defer to the Rule-18 end-state) and does NOT move predicates out of the existing frozensets.
- **Sign-fix (both):** insert `cleaned = re.sub(r"(?<=-)\s+(?=\d)", "", cleaned)` between the
  whitespace-collapse and `_parse_number` in step 6 (lookbehind narrowed to `-` to match
  `_PURE_NUM_RE`'s `-?\d` capability; `+` stays text). Regression pins added:
  `values_conflict("-SGD 2.1M","-SGD 3.0M") is True`, `normalize_value("SGD -2.1M")[1]≈-2.1e6`.
  Note only `…("-SGD 2.1M","SGD -2.1M") is False` is genuinely RED-first; the sign-flip case is a
  regression anchor.
- **Misc:** normalize has **8** callers (not 7) — regression pins cover the audit/consensus paths;
  refresh the `recompute_contradictions.py` docstring (SP_026→SP_028a); the sweep-dedup failing
  test lives at `test/unit/ingest/test_sweep_dedup.py` (sweep-level, FakeRepo, no DB), NOT a
  `detect()` test; `eval/contradiction_recall.py` gains only a measurement helper, stays
  import-blind to `helixpay/`.

## Progress

- **Stage 2/3** 2026-06-11 — plan + 2-context review (above). 0 CRITICAL; H/M folded in.
- **Stage 4 (TDD)** 2026-06-11 — three levers, RED→GREEN each:
  1. normalize sign-fix (step 6b `(?<=-)\s+(?=\d)`); RED on `-SGD 2.1M ≡ SGD -2.1M`.
  2. `predicate_cardinality.py` grounded table (set_valued/breakdown/functional/unknown).
  3. `_DedupWriter` sweep (cardinality skip on claim loop + value-pair/to-entity dedup),
     `detect()`/`detect_link_conflicts()` UNCHANGED. New `test_sweep_dedup.py` (FakeRepo, no DB).
- **Stage 5 (post-impl, plan-blind)** — code-reviewer over the implementation: 0 CRITICAL/HIGH-
  blocking. Applied: H1 (drop the loop-closure — pass keymap dict directly to the wrapper),
  H2 (document bare `- 5` parse with a test), M1 (link-dedup test), M3 (disjoint-set import
  assert in predicate_cardinality). Re-verified green.
- **Live $0 measurement** (sweep over `helixpay_full`): **266 → 115** contradictions
  (claim 100 + link 15; 19 set_valued groups skipped). Oracle baseline **preserved**
  (`confluence-ga-target` still caught — 1/8, as expected: this layer raises PRECISION; recall is
  SP_028b/029). Idempotent (clear-then-rewrite, deterministic).
- **Stage 6 (docs)** — CLAUDE.md gotcha added; `recompute_contradictions.py` docstring refreshed
  (SP_026→SP_028a); `touches_paths` reconciled (contradict.py/eval scorer NOT touched — the
  wrapper avoided them; added `test_sweep_dedup.py`).
- **Verification:** `uv run pytest test/unit test/golden` → **742 passed, 4 skipped**;
  `uv run mypy helixpay scripts/recompute_contradictions.py` → clean.
- **Residual (honest):** the 115 are mostly distinct *phrasings* of the same semantic conflict
  (e.g. "end of Q3" vs "September 30"), which conservative text-dedup correctly keeps distinct;
  semantic collapse + the 7 missed oracle items are SP_028b (LLM) / SP_029 (entity-merge).
- **Note:** the sweep mutated the live `helixpay_full` contradictions (266→115) — that IS the
  deploy action for this layer; idempotent and re-runnable.
