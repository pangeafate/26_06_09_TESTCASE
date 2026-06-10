---
sprint_id: SP_010
tier: Standard
features: [replay-tier, recall-company-entity, recall-metric-vocab, recall-normalize, recall-target-contradiction]
user_stories: []
schema_touched: false
structure_touched: true
status: In Progress
isolation: branch-only
branch: sprint/SP_010-recall-replay
worktree: ""
agent_owner: "Agent B (recall)"
fix_type: "operator-observable: eval recall 27% < 85% bar + planted Confluence contradiction never surfaces"
dependencies: [SP_009]
dev_dependencies: []
touches_paths:
  - helixpay/seed/roster.py
  - helixpay/seed/metric_vocab.py
  - helixpay/ingest/replay.py
  - helixpay/ingest/contradict.py
  - Makefile
  - test/unit/seed/test_roster.py
  - test/unit/seed/test_metric_vocab.py
  - test/unit/ingest/test_replay.py
  - test/unit/ingest/test_contradict.py
touches_checklist_items: [replay-caching-extractor, replay-replay-extractor, replay-make-targets, recall-seed-helixpay-entity, recall-seed-project-entities, recall-seed-aliases, recall-metric-vocab-synonyms, recall-normalize-in-contradict, recall-target-window-bypass]
---

# SP_010: Recall to 85% + the $0 replay tier (the bar-clearer)

## Sprint Goal

Two coupled goals from `RECALL_AND_ITERATION_REPORT.md`, plus the detection fix that
the planted Confluence contradiction actually needs (folded in at Stage-3 review — see
**Pre-Implementation Review**):

1. **The $0 replay tier.** A `CachingExtractor` and `ReplayExtractor` wrapping the
   existing injectable `extractor=` seam on `pipeline.run`. Record the one expensive
   LLM extraction once (keyed on `source_uri` + chunk ordinal), then replay
   `resolve → canonicalize → persist → supersede → contradict` with **zero API calls**
   (then run `eval` against the resulting DB). This is the loop that makes the recall
   fixes — and all future post-LLM tuning — free to iterate.
2. **The diagnosed recall + contradiction fixes — all post-LLM, all testable on replay:**
   - **Seed the `HelixPay` company entity** (a *distinct* `other` entity, **not** an
     alias of `HelixPay Brasil`) so ~6 company-metric facts (revenue, runway, headcount,
     NPS, net-new-merchants) resolve. Recall 27% → ~67%.
   - **Seed the `Project Confluence` and `CRM migration` entities** (+ aliases) so the
     `ga_target` / `completion_target` facts resolve to a subject at all (they are not
     in the roster; without them the cached claims have nowhere to attach). 3 more facts.
   - **Extend `metric_vocab`** with `ga_target` and `completion_target` + synonyms
     (launch / GA / go-live; cutover / migration completion) so those predicates
     canonicalize together — the precondition for the planted contradiction to pair up.
   - **Delegate value normalization in `contradict` to the committed
     `helixpay.ingest.normalize`** (SP_009's shared util — already handles
     `'18 months' ≡ 'eighteen months'` and `'14.2M' ≡ '14.2 million'`) so the runway /
     revenue false contradictions stop firing (`no_false_contradiction`).
   - **Surface the Confluence temporal slip.** `contradict.detect` currently skips the
     two `ga_target` claims because `windows_overlap` collapses a `valid_to=None` claim
     to its `as_of` point, so two claims dated 2026-04-15 and 2026-05-12 never overlap
     and the `temporal` branch in `classify` is unreachable for them. Bypass the
     window gate for a small set of **target/deadline predicates** (`ga_target`,
     `completion_target`) where `as_of` is the assertion date, not a validity period —
     scoped so time-series metrics (revenue Q1 vs Q2) are untouched.

Target: **eval recall 27% → ≥85%**, golden-precision 100%, the Confluence
contradiction surfaced, no false revenue/runway contradiction — **proven on the replay
tier** (DB up, $0 after one record) before any paid full run.

## Current State

- `pipeline.run(..., extractor=…)` is an injectable seam (`pipeline.py`); production
  default is `ChunkExtractor(AnthropicClient(), glean_passes=1)`. No record/replay
  wrapper exists.
- The three fixes are diagnosed in `SOLUTION.md §3` and `RECALL_AND_ITERATION_REPORT.md`.
- `helixpay/seed/roster.py` seeds 63 people/teams + `HelixPay Brasil` + products, but
  **not** `HelixPay`, `Project Confluence`, or `CRM migration`.
- `contradict.normalize_value`/`values_conflict` **already exist and are robust**, but
  do not cover word-form numbers (`'eighteen'`, `'million'`). **SP_009 already shipped
  `helixpay.ingest.normalize` (committed on this branch's base)** which does — so this
  sprint *imports* it; there is no stub. `contradict.detect` gates every pair on
  `windows_overlap`, which is correct for period-stamped metrics but wrong for
  forward-looking targets (the Confluence gap above).

## Desired End State

- `make ingest-record` runs a real extraction and writes a replay cache; `make replay`
  re-runs the post-LLM pipeline from cache with **zero API calls**, then `make demo`
  grades it; both documented.
- `HelixPay`, `Project Confluence`, `CRM migration` (+ alias forms) resolve;
  `metric_vocab` covers `ga_target`/`completion_target`; `contradict` uses the shared
  normalize util and surfaces the Confluence temporal slip.
- On the replay tier (DB up): **recall ≥85%**, Confluence contradiction present,
  `no_false_contradiction` passes. One paid confirmation run is a separate, explicit step.

## Scope

In: the replay wrappers + make targets; the seed company/project/alias additions; the
`metric_vocab` synonyms; the normalize delegation **and** the target-predicate window
bypass in `contradict.py`. Out: the shared normalize util itself (SP_009, **landed**);
any contract/schema change; the eval `DEFAULT_RECALL_BAR` constant and eval-harness
structure (SP_013); provenance persistence/link sweep (SP_011).

## Technical Approach

- **Replay** — `CachingExtractor(inner, cache_dir)` implements the `_Extractor` Protocol:
  on `extract(chunk, ctx)`, call `inner.extract`, serialize the `ExtractionOut` to
  `cache_dir/<slug(source_uri)>.<ordinal>.json`, return it. `ReplayExtractor(cache_dir)`
  reads the cache and reconstructs the `ExtractionOut` (full pydantic round-trip so
  `evidence`/`confidence`/`hypothetical` survive), raising on a cache miss. Wire both via
  the existing `extractor=` param — **no pipeline/extractor seam edit needed**. The cache
  key is `(source_uri, ordinal)`: `source_uri` is unique per document and `ordinal` is
  unique within it, so it is collision-free across the corpus (a content change at the
  same path is a re-record, the same class as a prompt/chunking change). A thin
  `python -m helixpay.ingest.replay` CLI wires the repo + chosen wrapper and calls
  `pipeline.run(..., extractor=…, already_ingested=lambda _: False)` so replay re-runs the
  post-LLM path on every document. Make targets pass the chosen mode through it.
- **Company / project entities / aliases / vocab** — additive rows in
  `helixpay/seed/roster.py` (`parse_overview`) + `helixpay/seed/metric_vocab.py`.
  `HelixPay` is a **separate** `other` entity from `HelixPay Brasil` (distinct
  `(canonical_name, entity_type)` keys; no alias collision). Resolution already prefers
  seeded entities, so seeding makes a bare `"HelixPay"` mention resolve even when the
  cached claim carried no `subject_type` (today it is dropped). Idempotent on natural keys.
- **normalize + window in contradict** — replace `contradict`'s local `normalize_value`
  with `from helixpay.ingest.normalize import normalize_value, values_conflict`
  (re-export so `grounding.py`'s `from helixpay.ingest.contradict import normalize_value`
  keeps working). Add `_TARGET_PREDICATES = {"ga_target", "completion_target"}`; in
  `detect`, skip the `windows_overlap` gate for those (still gated on `values_conflict`),
  so a changed target value across two assertion dates surfaces as `temporal`.

## Testing Strategy

- `test/unit/ingest/test_replay.py` — round-trip: `CachingExtractor` writes the cache and
  returns the inner result; `ReplayExtractor` returns a **field-equal** `ExtractionOut`
  with the inner extractor asserted **not called**; cache-miss raises.
- `test/unit/seed/test_roster.py` — `HelixPay`, `Project Confluence`, `CRM migration`
  present and distinct from `HelixPay Brasil`; aliases map; re-parse stable.
- `test/unit/seed/test_metric_vocab.py` — `launch`/`general availability`/`go-live`
  canonicalize to `ga_target`; `cutover`/`migration completion` to `completion_target`;
  unknown predicates still pass through.
- `test/unit/ingest/test_contradict.py` — `'18 months'` vs `'eighteen months'` and
  `'14.2M'` vs `'14.2 million'` do **not** conflict; a genuine conflict still does; a
  `detect` over two `ga_target` claims with differing `as_of` (`valid_to=None`) now
  writes one `temporal` row, while two `revenue` claims with differing `as_of` still
  write **zero** (time-series untouched).
- Replay-tier acceptance (manual, DB-gated — see Behavioral Closure): `make up` +
  `DATABASE_URL` + one paid `make ingest-record`, then `make replay && make demo` →
  recall ≥85%, Confluence contradiction surfaced, `no_false_contradiction` passes.

## Risks & Mitigations

- *SP_009 dependency* → SP_009 (`helixpay.ingest.normalize` + contracts v2) is **committed
  on this branch's base**. SP_010 imports the util; no stub, no duplicate. Declared
  `dependencies: [SP_009]`.
- *Overlap on `contradict.py` with SP_011 (link sweep)* → different functions in the same
  file (SP_010 touches `normalize`/`values_conflict`/`detect`/`_TARGET_PREDICATES`;
  SP_011's link sweep is distinct). Merge order **SP_010 → SP_011**; SP_011 rebases.
  Declared.
- *Window bypass over-fires* → scoped to two target predicates only; both sides still
  pass through the shared `values_conflict`, so identical target phrasings agree and only
  a genuine slip surfaces. A date-phrase normalizer (`'end of Q2' ≡ 'end of June'`) is
  **out of scope** (a later sprint) and noted as a known limitation.
- *Replay cache staleness if the prompt/chunking/source content changes* → the key is
  `(source_uri, ordinal)`; any such change is a Tier-1 re-record, not a replay.
  Documented in the make-target help and the report.
- *DB-gated acceptance* → unit tests are db-marked-skip and pass without a DB, but the
  headline recall/contradiction numbers require `make up`. Recorded as pending operator
  smoke with exact steps (Rule 21).

## Success Criteria

- `make ingest-record` + `make replay` work; replay does zero API calls (asserted in the
  unit round-trip; no `AnthropicClient` constructed on the replay path).
- Replay-tier **recall ≥85%** over the `recall_bar:true` golden facts, golden-precision
  100%, Confluence contradiction surfaced, `no_false_contradiction` green. (Note: the eval
  gate constant is `DEFAULT_RECALL_BAR = 0.80` and is **owned by SP_013** — the 85% target
  is measured, not enforced by a constant change here; pass `--recall-bar 0.85` to the
  harness for the SP_010 acceptance read-out.)
- `uv run pytest test` green; `uv run mypy helixpay` clean.
- One paid full-corpus confirmation run reproduces the replay result (separate, logged
  step before any submission).

### Pre-Implementation Review

> Standard tier — review-iteration floor = 2. `fix_type` is set (operator-observable
> recall miss + non-surfacing contradiction) → Behavioral Closure (Rule 21) applies: the
> 27%→85% symptom and the Confluence contradiction must be replayed against the system at
> close-out, not just asserted.

- **Iteration 1 — architect-reviewer (plan-blind over the plan + real code). Verdict: NOT
  implementable as written; 2 CRITICAL.**
  - CRITICAL: cache key on `content_hash` is unreachable from `extract(chunk, ctx)` —
    neither `Chunk` nor `ChunkContext` carries it; `hash(chunk.text)` cross-contaminates
    identical chunk text across documents. **Resolved:** key on `(source_uri, ordinal)`
    (unique per chunk, no seam edit).
  - CRITICAL: the "missing shared normalize / ship a stub" premise is stale —
    `contradict.normalize_value` already exists and `helixpay.ingest.normalize` (SP_009)
    is already committed; a second copy would split-brain with `grounding.py`'s import.
    **Resolved:** import + re-export the committed util; no stub.
  - HIGH: recall figures are modeled; `DEFAULT_RECALL_BAR=0.80` vs the plan's 85% target
    with eval out of scope. **Resolved:** 85% is a measured read-out (`--recall-bar 0.85`),
    not a constant change; SP_013 owns the gate.
- **Iteration 2 — code-reviewer (plan-blind, adversarial). Verdict: 3 CRITICAL traps,
  all folded into scope.**
  - CRITICAL: `windows_overlap` point-window trap means vocab alone never materializes the
    Confluence contradiction. **Resolved:** target-predicate window bypass added to scope
    (operator-approved fold-in).
  - CRITICAL: `Project Confluence` / `CRM migration` are not seeded; the `ga_target` /
    `completion_target` facts have no subject to attach to. **Resolved:** seed both as
    `other` entities.
  - CRITICAL: `HelixPay` must be a distinct entity, not a `HelixPay Brasil` alias, or the
    14.2M company vs 4.8M subsidiary revenue collide into a false contradiction.
    **Resolved:** distinct `other` entity, no shared alias.
  - Decisions on the two genuine forks (absorb the detection fix here; commit SP_009 then
    branch SP_010 off it) were taken by the operator before implementation.

### Post-Implementation Review

- Iteration 1 — (pending; plan-blind over replay wrappers + seed/vocab/normalize/window)
- Iteration 2 — (pending; re-verify recall ≥85% + Confluence surfaced on the replay tier
  as runtime evidence — DB-gated, recorded as operator smoke if no DB at close-out)

## Hand-off

- The replay tier is the default dev loop for all subsequent post-LLM tuning (SP_011/
  012/013 grade their changes on it).
- Records the canonical replay cache location for the team; one paid record run seeds it.
- **Pending operator smoke (Rule 21):** `make up` → `export DATABASE_URL=…` →
  `make ingest-record` (one paid run) → `make replay` → `make demo` (or
  `python -m eval.run --recall-bar 0.85`); confirm recall ≥85% and the Confluence
  contradiction in the answer bundle. No DB was available in the build environment.
