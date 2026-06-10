---
sprint_id: SP_010
tier: Standard
features: [replay-tier, recall-company-entity, recall-metric-vocab, recall-normalize, recall-target-contradiction]
user_stories: []
schema_touched: false
structure_touched: false
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

- **Iteration 1** — architect-reviewer, plan-blind. 2 CRITICAL + 1 HIGH (all resolved below). Files reviewed: SP_010 plan, pipeline.py, extractor.py, contradict.py, normalize.py, roster.py, metric_vocab.py, facts.yaml, eval/run.py.
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
- **Iteration 2** — code-reviewer, plan-blind adversarial. 3 CRITICAL traps (all folded into scope below). Files reviewed: contradict.py, resolve.py, roster.py, run_seed.py, metric_vocab.py, fixtures.py, facts.yaml, eval/run.py, test_contradict.py.
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

- **Iteration 1** — code-reviewer, plan-blind over changed code + tests. 3 HIGH operational findings fixed pre-commit (below), 1 MEDIUM accepted, 0 blocking. Files reviewed: replay.py, contradict.py, normalize.py, roster.py, metric_vocab.py, repository.py, Makefile, test_replay.py, test_contradict.py.
  - HIGH: replay on a fresh/empty DB would feed zero-vector embeddings into `add_chunks`
    (no prior chunk rows to protect via `ON CONFLICT DO NOTHING`), silently breaking
    retrieval. **Fixed:** replay refuses to run when `repo.known_content_hashes()` is empty.
  - HIGH: `CachingExtractor` always called the paid inner extractor, so re-running
    `ingest-record` re-billed every chunk. **Fixed:** a pre-existing cache file is a hit
    (paid call skipped); `--force` overrides for an intentional re-record.
  - HIGH: `_slug` was not collision-free as documented (two paths can slugify alike).
    **Fixed:** the cache filename now carries a `source_uri` sha256 digest; docstring
    corrected. New tests cover all three.
  - MEDIUM (accepted, not a code bug): delegating to the shared `normalize_value` removes
    pre-existing false positives (`~18`≡`18`, `3,424`≡`3424`, word-magnitudes). Any
    contradiction rows written under the *old* contradict-local normalize for those exact
    pairs are not auto-deleted on re-run — a clean replay starts from the record run's DB,
    so this only matters to a long-lived DB and is noted for operator awareness.
- **Iteration 2** — pending runtime verification (DB-gated): 0 CRITICAL expected; re-verify recall ≥85% + Confluence surfaced on the replay tier as runtime evidence. Files reviewed: pending operator smoke (no DB in the build environment — see Hand-off).

## Hand-off

- The replay tier is the default dev loop for all subsequent post-LLM tuning (SP_011/
  012/013 grade their changes on it).
- Records the canonical replay cache location for the team; one paid record run seeds it.
- **Pending operator smoke (Rule 21):** `make up` → `export DATABASE_URL=…` →
  `make ingest-record` (one paid run) → `make replay` → `make demo` (or
  `python -m eval.run --recall-bar 0.85`); confirm recall ≥85% and the Confluence
  contradiction in the answer bundle. No DB was available in the build environment.

---

## Increment 2 — final mile to the recall bar (2026-06-10)

After SP_019 lifted measured smoke recall to **7/11 (64%)**, a claim-by-claim audit of the
`.replay-cache/` against `eval/smoke/facts.yaml` under the real grader (`eval/run.py`)
pinned the exact remaining gap for each of the 4 missing facts. The conclusion is sharper
than the original SP_010 hand-off ("roster aliases + predicate vocab"): only **one** of the
four is a clean $0 deterministic win; the rest are baked-cache defects that require the
operator-gated paid re-record (SP_019's prompt, Increment 2 below).

### What is $0-fixable here (SP_010 side)

- **`email-acai-owner` (the one $0 recall win → 7/11 ⇒ 8/11).** The cache already holds the
  correct relation `Maria Santos --owns--> Açaí Express SP`. It failed only because
  `Açaí Express SP` is mentioned with **two** subject_types (`customer` and `other`), minting
  two unseeded rows → the bare name is ambiguous → the link endpoint resolves to `None` (link
  dropped at ingest) and the grader's bare-name `resolve_entity` returns `None`. **Fix:** seed
  `Açaí Express SP` as a `customer` in `roster.py` `parse_overview` (with accent-folded
  aliases). The SP_019 seeded-snap then collapses the `other`-typed mention onto the one
  seeded row; nothing is minted; the link persists and resolves. This is the **same
  seed-it-or-it-cannot-resolve pattern** already used for `Project Confluence` / `CRM
  migration` (a named cross-document entity the golden set hangs off), applied to a customer —
  principled, not oracle-shaping.
- **`top_contributor` vocab key** added to `metric_vocab` (aliases: top/lead/primary
  contributor, top/lead committer). Harmless substrate that lets a contributors-analysis
  ranking land on one predicate the grader can match — only effective **after** the re-record
  emits such a claim (see Increment 2 of SP_019).

### What is NOT $0-fixable (re-record-gated — SP_019 Increment 2)

- `pdf-boarddeck-confluence-q3` — cache value `end-Q3 (2026-09-30)` does not substring-match
  golden `end of Q3 2026` under the grader normalize, **and** the cache predicate
  `ga target date (revised)` does not canonicalize. **Two** defects; both need re-extraction.
- `slack-crm-cutover-june` — the claim is attached to `HelixPay`, not `CRM migration`
  (predicate `pipedrive decommission date`). Value/as_of already match; only the **subject**
  is wrong. Needs the re-record to re-subject it to the initiative. We deliberately do **not**
  add a `pipedrive→CRM-migration` re-attribution rule (it would be answer-shaped oracle
  gaming; Stage-3 Finding 4).
- `code-core-top-contributor` — no `top_contributor` claim exists in the cache at all; needs
  the re-record to emit it.

### Scope (Increment 2, SP_010 side)

In: `roster.py` (seed `Açaí Express SP` customer + aliases; `_ACCOUNTS` list + `CUSTOMER`
const), `metric_vocab.py` (`top_contributor` key), and their unit tests. Out: the prompt
surgery + the customer-collapse resolve proof (SP_019 Increment 2, which owns
`prompts/extract_claims.md` + `test_resolve.py`); any contract/schema change; the grader's
value normalization (SP_013 — see Limitation).

### Ordering dependency (Stage-3 Finding 7)

SP_010 Increment 2 must land **and the smoke DB be re-seeded** *before* the paid re-record
runs, or the re-record's `top_contributor` / milestone predicates will not canonicalize
against the new vocab. Disjoint paths from SP_019 but **sequentially** dependent — not a
parallel-safe pair.

### Success criteria (Increment 2)

- **$0 deterministic:** replay (no API) → `email-acai-owner` FOUND; recall **7/11 ⇒ 8/11
  (73%)**, golden-precision 100%, mismatch unchanged. Proven on the replay tier.
- **Paid (gated, SP_019):** anchor the bar-clearing target at **9/11 (82%)** = Açaí + the CRM
  wrong-subject re-record; treat `pdf-boarddeck-confluence-q3` and `code-core-top-contributor`
  as **stretch** (Stage-3 Findings 5/6: Confluence has a value *and* predicate defect, and
  top_contributor requires the extractor to assert a named lead — least reliable).
- `uv run pytest test` green; `uv run mypy helixpay` clean.

### Limitation (recorded, not gamed)

`pdf-boarddeck-confluence-q3` may stay MISMATCH even after a perfect re-record because the
golden phrasing "end of Q3 2026" carries the filler word "of" that the source ("end-Q3")
does not. The principled fix is hardening the grader's `normalize_value` for date/milestone
values (token-aware), which is **SP_013's** (the eval oracle) — out of scope here. We do not
loosen the oracle to pass a test.

### Pre-Implementation Review (Increment 2)

- **Iteration 1** — architect-reviewer, plan-blind on the design. 1 HIGH (goal-certainty) + 3 MEDIUM + LOW confirmations; all resolved below. Files reviewed: roster.py, run_seed.py, resolve.py, pipeline.py, repository.py, metric_vocab.py, eval/run.py, eval/smoke/facts.yaml, test_roster.py, .replay-cache audit.
  - MEDIUM (Finding 4): the proposed `pipedrive decommission` → `completion_target` alias is answer-shaped, buys **zero** $0 recall (subject is still `HelixPay`), and risks a silent contradiction-merge. **Resolved:** dropped; only the generic `cutover`/`migration completion` aliases remain for a clean re-record.
  - HIGH (Finding 5): `pdf-boarddeck-confluence-q3` has **two** defects (predicate + value), not one. **Resolved:** success bar anchored at 9/11 without it; Confluence is stretch; oracle normalization deferred to SP_013.
  - MEDIUM (Finding 2): the parse-layer test does not prove the link resolves with a coexisting mint. **Resolved:** added `test_seeded_account_wins_even_if_a_minted_other_row_coexists` (SP_019 side) asserting seeded-first bare-name resolution.
  - MEDIUM (Finding 6): `top_contributor` needs the extractor to assert a named lead. **Resolved:** prompt emits it only when the span explicitly names the leader; flagged stretch.
  - LOW confirmations: Açaí seeding is principled (Confluence/CRM precedent); no false-contradiction / two-Marias / link-reversal regression; the SP_010/SP_019 split respects path claims and layer boundaries.
- **Iteration 2** — code-reviewer, plan-blind adversarial; 1 CRITICAL + 1 HIGH + 3 MEDIUM/LOW, all resolved before implementation closed. Files reviewed: repair.py, metric_vocab.py, roster.py, resolve.py, run_seed.py, eval/run.py, .replay-cache (exhaustive grep), test_repair.py, test_roster.py.
  - **CRITICAL-1:** adding `top_contributor` to `METRIC_VOCAB` silently widens `repair.py`'s `KNOWN_KEYS` (built as all vocab keys minus `_NON_COMPANY_KEYS`), so a `subject_type=="metric"` claim canonicalizing to `top_contributor` would be mis-attributed to `HelixPay` on a re-record. **Resolved:** added `"top_contributor"` to `repair._NON_COMPANY_KEYS` + a lock-step comment + `test_repair` assertions (`is_known_metric("top contributor") is False`).
  - HIGH-1: the vocab additions add **0** $0 recall (no matching cache claim exists) and could mislead an implementer. **Resolved:** explicit "requires the re-record" note in `metric_vocab.py` and the sprint scope.
  - MEDIUM-1: the Açaí fix needs seed-before-ingest; a DB carrying the old dual-minted rows needs them deleted first. **Resolved:** the $0 replay reset deletes `seeded=false` entities before re-seed; noted for the live-deploy hand-off.
  - MEDIUM-2: a no-"SP" Açaí alias's folded form would not match the asserted alias. **Resolved:** dropped the no-SP aliases; only `("Açaí Express SP", "Acai Express SP")` remains (matches the test).
  - LOW-2: never add bare `"decommission"` (the cache has a `decommission` predicate on a `Pipedrive` product). **Resolved:** no decommission alias added at all (Finding 4 already dropped them).

### Post-Implementation Review (Increment 2)

- **Iteration 1** — code-reviewer, plan-blind, 0 CRITICAL + 0 HIGH + 2 hardening (MEDIUM/LOW), APPROVE — both applied. Files reviewed: roster.py, metric_vocab.py, repair.py, prompts/extract_claims.md, test_roster.py, test_metric_vocab.py, test_resolve.py, test_repair.py, test_prompts.py.
  - Verified independently: `canonical_key` never raises and passes unknowns through; **no alias maps to two keys**; `top_contributor` in `_NON_COMPANY_KEYS` fully neutralizes the repair-gate widening (a metric-typed claim canonicalizing to it is NOT re-attributed to HelixPay); the `_ACCOUNTS` seed mirrors the `_PROJECTS` pattern and populates `parse.entities` (not `parse.people`, so the org-chart smoke count is unaffected); tests are not tautologies; no secret/DSN log, no raw SQL, no layer-boundary violation.
  - M-1 (coverage): `"leading contributor"` alias was unexercised. **Applied:** added to `test_metric_vocab` + `test_repair` assertions.
  - L-1 (coverage): the accent-fold alias path wasn't exercised through `resolve_mention`. **Applied:** added `resolve_mention("Acai Express SP", "customer") == acai` to the collapse test.
- **Iteration 2** — runtime verification (DB-gated, **$0 replay — DONE 2026-06-10**): MEDIUM-1 (seed-before-ingest / wipe old dual-mints) executed via the derived-row reset; replayed the 9 smoke docs with the `_ConstantEmbedder` (no API) and graded with `check_extraction` (no Opus). **Result: `email-acai-owner` FOUND; recall 7/11 → 8/11 (73%), precision 100%, mismatch=0** — exactly the predicted $0 ceiling (the other 3 stay MISSING, re-record-gated). Recorded in `workspace/acceptance/SP010_finalmile_run.md`. Files reviewed: replay run + grader output.
