---
sprint_id: SP_014
tier: Standard
features: [extraction-loss-ledger, extraction-truncation, extraction-coerce-then-validate, prompt-as-of-clarify]
user_stories: []
schema_touched: false
structure_touched: false
status: Complete
isolation: branch-only
branch: sprint/SP_014-extraction-recall
worktree: ""
agent_owner: "Agent B (recall)"
fix_type: "operator-observable: ~24% of extracted items silently dropped + fact-dense chunks return empty (recall ceiling below the 85% bar even after SP_010 resolution fixes)"
dependencies: [SP_010]
dev_dependencies: []
touches_paths:
  - helixpay/ingest/extract/llm.py
  - helixpay/ingest/extract/extractor.py
  - helixpay/ingest/extract/coerce.py
  - helixpay/ingest/extract/ledger.py
  - helixpay/ingest/pipeline.py
  - prompts/extract_claims.md
  - test/unit/ingest/test_coerce.py
  - test/unit/ingest/test_ledger.py
  - test/unit/ingest/test_llm.py
  - test/unit/ingest/test_extractor.py
touches_checklist_items: [ledger-loss-counters, llm-stop-reason-seam, llm-max-tokens-bump, extract-truncation-handling, extract-silent-empty-surface, coerce-as-of-quarter, coerce-enum-synonyms, coerce-link-verbs, coerce-then-validate-wire, prompt-as-of-clarify]
---

# SP_014: Stop the silent extraction loss (the recall-ceiling lifter)

## Sprint Goal

SP_010 fixed recall at the **resolution** layer (seed `HelixPay` / `Project Confluence`,
canonicalize predicates, surface the Confluence contradiction). This sprint fixes the two
defects **upstream of that**, in the extraction layer, where facts are lost *before they
ever reach resolution* — so even a perfect resolver cannot recover them:

1. **Defect A — empty-on-dense.** The extraction call is capped at `_MAX_TOKENS = 4096`
   (`llm.py:26`) and the response handler reads only text blocks (`llm.py:60-61`) — it
   **never inspects `stop_reason`** (grep: zero hits across `helixpay/`). A fact-dense
   chunk overflows 4096, the JSON truncates, the single repair turn also overflows, and
   `extract()` returns an **empty `ExtractionOut()`** for the whole chunk
   (`extractor.py:82-84`). The loss is invisible — there is no counter, only a `WARNING`
   one layer down (`llm.py:131-135`). Hits the dense HTML dashboards and the org-chart.

2. **Defect B — validate-without-repair.** `_validate_items` strict-validates each item and
   **drops on `ValidationError` with no coercion** (`extractor.py:208-220`) — ~24% of
   emitted items (≈20% of claims, ≈37% of relations). The schema rejects the model's
   *natural* emissions: a non-ISO `as_of` like `"Q1 2026"` (which the prompt itself invites
   at `extract_claims.md:29-31`) fails `date.fromisoformat` (`schemas.py:28-32, 69-74,
   108-113`) and drops the **entire** claim; link verbs and entity nouns outside the frozen
   enums (`models.py:35-41`, `:44-50`) drop their items.

3. **Defect 0 — the loss is unmeasured.** Add an end-of-run **loss ledger** so every
   subsequent change has a before/after, converting today's silent loss into a number.

Target: lift the *extraction* recall ceiling (raw items emitted per chunk) so that, with
SP_010's resolution fixes in place, the end-to-end eval clears **≥85%** — golden-precision
held at **100%**, both planted contradictions still surfaced, the two-Marias / two-Tans
traps intact — **measured on one paid sample re-record, then frozen on one full re-record.**

This sprint is **extraction-only**. The resolution/seeding fixes (the "Workstream C"
company-entity de-pollution) are **SP_010's** and are explicitly out of scope here (see
**Scope** and the SP_010 coordination note in **Risks**).

## Current State

- `_MAX_TOKENS = 4096` (`llm.py:26`), forwarded at `llm.py:105,111,125`; the Anthropic
  response is reduced to joined text at `llm.py:60-61`; `stop_reason` is discarded and the
  `LLMClient` Protocol returns `-> str` (`llm.py:34`). **Truncation is undetectable.**
- Undecodable output → `return ExtractionOut()` silently at `extractor.py:82-84` (logged
  only at `llm.py:131-135`; **no aggregate counter**).
- `_validate_items` (`extractor.py:208-220`) drops invalid items per-`ValidationError`,
  emits a per-item `WARNING`, aggregates nothing.
- `as_of` is strict ISO via `parse_as_of` → `date.fromisoformat` (`schemas.py:28-32`),
  enforced on `ClaimOut.as_of` (`schemas.py:69-74`) and `RelationOut.as_of`
  (`schemas.py:108-113`); a single bad date drops the whole item.
- `prompts/extract_claims.md:29-31` tells the model `YYYY-MM-DD` but cites `"Q1 2026"` as a
  value's own date in the same sentence — internally inconsistent (the JSON example at
  line 67 correctly shows `YYYY-MM-DD`).
- The eval grades **link direction** (`Verdict.mismatch` "present but reversed",
  `eval/run.py:167-169`) and matches **`as_of` by exact equality** (`eval/run.py:145-147`);
  the golden oracle stamps quarter facts at quarter-**end** (`facts.yaml`: revenue / NPS /
  net-new-merchants / Brasil-revenue all `2026-03-31`).
- SP_010's `record`/`replay` cache stores the **post-validation** `ExtractionOut`
  (`replay.py:91`). The ~24% Defect-B losses are discarded **before** the cache write, so
  **replay can never resurrect them** — every change in this sprint requires a paid
  re-record to validate (see **Cost & Sequencing**).

## Desired End State

- The extraction call surfaces `stop_reason`; a truncated chunk is **counted, logged, and
  (optionally) recovered** instead of silently zeroed. `_MAX_TOKENS` raised to `8192`.
- A `coerce` step normalizes the model's natural emissions to the **frozen** contracts
  *before* strict validation, dropping only what is genuinely unmappable — so precision is
  preserved by dropping-on-ambiguity, never by guessing.
- The end-of-run **loss ledger** reports per-doc and total `{chunks, empty_extractions,
  truncated_calls, items_emitted, items_dropped_by_reason, items_coerced_by_kind}`.
- On one paid sample re-record + SP_010's resolution: **recall ≥85%**, golden-precision
  **100%**, both contradictions surfaced, name-traps intact. Frozen via one full re-record
  + `pg_dump`.

## Scope

**In:** the `_MAX_TOKENS` bump; widening the `LLMClient` seam to surface `stop_reason`
(additive); truncation counting + a recursion-on-loader-boundary recovery path (phased,
off by default until measured); replacing the silent empty-`ExtractionOut` with a
counted/logged failure; the `coerce` module (quarter→ISO `as_of`, enum synonym map, link
verb mapping with audited direction) wired *before* `_validate_items`; the prompt `as_of`
clarification; the loss ledger; their unit tests.

**Out (and who owns it):** the frozen contracts in `helixpay/contracts/` — **never edited**
(coercion maps *to* them, not them to the data); **all resolution / seeding** (company
entity de-pollution, `resolve_entity` prefer-seeded-across-type) — **SP_010**; `replay.py`
and the make targets — **SP_010**; `eval/run.py`, `DEFAULT_RECALL_BAR`, the eval-harness
structure and any new fixtures under `eval/sample/` — **SP_013**; provenance / link sweep —
**SP_011/012**; the production `pg_dump` mechanics — operator step (memory:
`helixpay-replay-vs-prod-seed`).

## Technical Approach

### Defect 0 — loss ledger (`helixpay/ingest/extract/ledger.py`, new)
A small dataclass accumulated by `ChunkExtractor` and threaded through extraction:
counters for `chunks`, `empty_extractions`, `truncated_calls`, `items_emitted`,
`items_dropped_by_reason` (`validation_error`, `unmappable_enum`, `unparseable_as_of`,
`hypothetical`, `ungrounded`), and `items_coerced_by_kind`. `pipeline.run` logs a single
structured summary at end-of-run (the **only** touch to `pipeline.py`; SP_010 did not edit
it, so no overlap). Pure dev-tooling alongside production code — no behavior change on its
own.

### Defect A — truncation (`llm.py`, `extractor.py`)
- **Raise `_MAX_TOKENS` 4096 → 8192** first. Contract-free, risk-free; against ~650-token
  target chunks (`base.py:127`), 8192 covers all but pathological density and removes most
  truncation with **zero split risk**.
- **Surface `stop_reason`.** Widen the `LLMClient` seam minimally — `generate(...)` returns
  a small `GenerationResult{text, stop_reason}` (or an additive sibling method) so
  `call_structured` can see truncation. This is the **one new runtime seam** in the sprint;
  it is additive (the Protocol gains a field, no caller semantics change).
- **Count, don't silently empty.** Replace `return ExtractionOut()` (`extractor.py:82-84`)
  with a path that increments `empty_extractions` / `truncated_calls` and logs at the
  extractor level (today's only signal is one layer down).
- **Recovery (phased, default-off).** A `stop_reason=="max_tokens"` chunk *may*
  split-and-recurse — but **only on loader-made `"\n\n"` unit boundaries**
  (`splittable=False`-derived dashboard/table units, which already co-locate each value
  with its inline `(as of …)` tag — `html.py:52-65`), **never mid-prose** (prose splitting
  can sever a value/role from its subject and re-introduce the name-trap ambiguity). Re-run
  grounding (`extractor.py:198`) after any split. Ship this behind a flag and enable it only
  if the ledger shows the 8192 bump leaves residual truncation.

### Defect B — coerce-then-validate (`helixpay/ingest/extract/coerce.py`, new)
A deterministic normalizer applied to each raw item **before** `_validate_items`. Drops on
ambiguity rather than guessing — precision is held at 100% by never inventing.
- **`as_of` → ISO, quarter-END convention** (to match the oracle's exact-equality grading):
  `"Q1 2026"→2026-03-31`, `"Q2 2026"→2026-06-30`, `"Q3 2026"→2026-09-30`,
  `"Q4 2026"→2026-12-31`, bare `"2026"→2026-12-31`. **Never** substitute a document's
  export / page "As of" header for a value that names its own period. Already-ISO values
  pass through untouched.
- **Entity-noun synonyms → `EntityType`:** `company`/`organization`/`org` → `other`
  (a company is `other`, **not** `team`); leave `person`/`team`/`customer`/`product`/
  `metric`/`other` as-is. `role` and other unmappable nouns → **drop** (ambiguous).
- **Link verbs → `LinkType`, direction-audited:**
  - `manages` / `is managed by` → `reports_to` **with from/to inversion** (gated on the
    verb, audited per-pair).
  - `reports to` → `reports_to` **as-is**.
  - `leads` / `functional lead` / `dotted-line` → **`dotted_line_to`** — **never** an
    inverted `reports_to` ("leads" is functional in this org — `org-chart.md:123`).
  - `part_of` / `member of` → `member_of`; `owns` → `owns`; `mentions` → `mentions`.
  - Anything else → **drop** (preserve precision).
- Wire: `extractor.py` calls `coerce_item(raw, kind)` and feeds the result to
  `_validate_items`; a `None` return is a counted drop (`unmappable_enum` /
  `unparseable_as_of`).

### Prompt (`prompts/extract_claims.md`)
Tighten line 29 so the model is told to emit quarter dates as `YYYY-MM-DD` quarter-**end**
directly (the deterministic `coerce` remains the safety net). A prompt change is a Tier-1
re-record regardless, so it costs nothing extra to land in the same record.

## Testing Strategy

- `test/unit/ingest/test_coerce.py` — table-driven: `"Q1 2026"→2026-03-31`,
  `"Q2 2026"→2026-06-30`, `"2026"→2026-12-31`, already-ISO passthrough; `company→other`;
  `manages` inverts from/to → `reports_to`; **`leads`→`dotted_line_to` (asserted NOT an
  inverted `reports_to`)**; `part_of→member_of`; unmappable verb / noun → `None` (drop).
  Property: a coerced item always validates against the frozen schema **or** is dropped —
  never produces an invalid item.
- `test/unit/ingest/test_ledger.py` — counters increment correctly; a forced empty
  extraction bumps `empty_extractions`; a dropped item bumps the right `dropped_by_reason`
  bucket; summary serializes.
- `test/unit/ingest/test_llm.py` — `GenerationResult` carries `stop_reason`; a stubbed
  `max_tokens` stop is detectable by `call_structured`; existing `-> str` callers keep
  working (back-compat assertion).
- `test/unit/ingest/test_extractor.py` — coerce runs before validate; a `"Q1 2026"` claim
  that **drops today is retained**; an unmappable item is still dropped and counted; the
  silent-empty path now increments the ledger.
- **Acceptance (paid, DB-gated — see Behavioral Closure):** micro-fixture record (2–3 docs)
  → sample re-record (11 docs) → full re-record (44 docs); each runs `eval.run
  --recall-bar 0.85` and the regression diff below.

## Cost & Sequencing

**There is no $0 iteration loop for extraction** — replay caches post-drop output
(`replay.py:91`), so every extraction-code change is a paid re-record. The only free check
is re-confirming SP_010's resolution on the *post-re-record* cache.

1. **Land 0 + A(token bump) + B(coerce) together** — one code drop, one re-record cost.
2. **Micro-fixture validate A/B (cents):** `--force`-record a 2–3 doc subset that includes
   `april-2026-kpi-dashboard.html` (the one golden-scored dense-HTML doc) + one dense
   markdown doc; eyeball the ledger + per-fact verdicts. `record` is idempotent per
   `(source_uri, ordinal)` so this is seconds and cents.
3. **One sample re-record (~5–6 min, paid, isolated `helixpay_sample` DB)** → full sample
   eval. Iterate here — **budget ~2–3 paid records, not "free unlimited."**
4. **Re-validate SP_010's resolution on the new cache** — the re-record changes which
   mentions exist, so C is *not* proven by the old cache; confirm it post-B+A.
5. **One full 44-doc re-record (~1 h, paid)** → full Tier-2 eval → `pg_dump`. Gate on the
   regression diff: **block any FOUND→{MISSING,MISMATCH} flip even if aggregate recall
   rose**, plus a coarse per-doc claim-count sentinel (golden-precision is blind to
   over-extraction of *non-golden* junk).

Minimum paid spend to a frozen seed: **micro (cents) + sample (~6 min ×~3) + full (~1 h
×1)**.

## Risks & Mitigations

- **B link inversion corrupts the org graph / breaks 100% precision.** The eval grades
  direction (`eval/run.py:167`). Mitigation: `leads`→`dotted_line_to` (never inverted
  `reports_to`); only `manages` inverts, gated on the verb; ambiguous → drop. Regression:
  org subtree under Arjun/Daniel byte-identical pre/post; no pair carries `reports_to` in
  both directions.
- **B `as_of` mapping drops a passing fact or fabricates/masks a contradiction.** Eval
  matches `as_of` by exact equality (`eval/run.py:145`). Mitigation: pin quarter-**END** to
  the oracle; unit-assert every quarter; never use the doc export date. (The headline
  Confluence contradiction is a text-valued `ga_target` predicate that bypasses the date
  window in `contradict.py` — immune to this mapping; the exposure is purely recall on
  revenue/NPS/merchants.)
- **A split-and-recurse severs a fact from its as_of/subject.** Mitigation: split only on
  loader `"\n\n"` unit boundaries (dashboard/table units carry inline as_of), never
  mid-prose; re-run grounding; ship default-off and enable only if the 8192 bump leaves
  residual truncation in the ledger.
- **Re-extraction nondeterminism regresses a currently-passing fact.** A paid record changes
  *other* facts too. Mitigation: every paid record runs the **full Tier-2 gate** and diffs
  the per-fact verdict vector; the 11-doc sample is a fast filter, **not** the acceptance
  gate (it sees only 1 of 3 dashboards and can't score the other two — they back no golden
  fact).
- **Path overlap with active SP_010.** SP_010's `touches_paths` are `roster.py`,
  `metric_vocab.py`, `replay.py`, `contradict.py`, `Makefile`, seed/ingest tests — **no
  overlap** with this sprint's `extract/**`, `pipeline.py`, `prompts/`. Merge order
  **SP_010 → SP_014** (SP_014 needs SP_010's resolution baseline + replay tier to validate).
  `branch-only` isolation is sufficient; declared `dependencies: [SP_010]`.
- **Frozen-contract pressure.** The temptation is to loosen `EntityType`/`LinkType`/`as_of`.
  **Forbidden** (CLAUDE.md: contracts frozen). Coercion lives *outside* the contract, in a
  new `coerce` module, mapping data → frozen types.

## Success Criteria

- `uv run pytest test` green; `uv run mypy helixpay` clean.
- Ledger reports non-trivial `items_coerced_by_kind` and a `truncated_calls` count that is
  **0** after the 8192 bump on the sample corpus (or, if non-zero, recovery enabled and the
  count driven to 0).
- On the sample re-record + SP_010 resolution: **recall ≥85%** over the `recall_bar:true`
  golden facts (`eval.run --recall-bar 0.85`), **golden-precision 100%**, both planted
  contradictions surfaced, `resolve_entity("Maria")` / `("Tan")` still `None` and the four
  full-name people still resolve to four distinct ids (name-traps intact).
- Per-fact verdict diff vs the prior run shows **no FOUND→{MISSING,MISMATCH} flip**.
- One full-corpus re-record reproduces the sample result; `pg_dump` taken as the production
  seed (operator step).

### Pre-Implementation Review

> Standard tier — review-iteration floor = 2 (`practices/GL-SELF-CRITIQUE.md`). `fix_type`
> is set (operator-observable silent loss) → **Behavioral Closure (Rule 21)** applies: the
> ~24%-drop / empty-on-dense symptom must be replayed against the system at close-out
> (recall ≥85% on the re-record), not merely asserted. The two iterations below are the
> author-independent adversarial challenge run on this plan before implementation; all
> CRITICAL/HIGH findings are folded into scope above.

- **Iteration 1** — adversarial architecture critic, plan-as-written. 3 reframes folded in
  (above). Files reviewed: CLAUDE.md, HELIXPAY_BUILD_SPEC.md, prompts/extract_claims.md,
  contracts/models.py, ingest/extract/*, db/repository.py (resolver), contradict.py,
  test/golden/facts.yaml, eval/run.py, eval/sample/*, data/org-chart.md, the dashboards.
  - CRITICAL: blanket `leads`/`manages` → `reports_to` inversion can plant false hierarchy
    edges and break 100% precision (eval grades direction). **Resolved:** split the mapping
    — `leads`→`dotted_line_to`, only `manages` inverts; ambiguous → drop.
  - CRITICAL: `"Q1 2026"`→quarter-start or the doc export date drops the revenue/NPS/
    merchants facts (eval matches `as_of` exactly; oracle uses quarter-end). **Resolved:**
    pin quarter-**END**; unit-assert; never use export date.
  - HIGH: "merge HelixPay dupes" risks collapsing distinct entities near the two-Marias /
    two-Tans trap. **Resolved:** de-pollution is **SP_010's** ("don't mint dupes" via
    seeding `other`), explicitly **out of scope** here; this sprint adds the name-trap
    regression assertions as a guard.
  - MEDIUM: A's split-and-recurse risks severing prose facts. **Resolved:** boundary-gated,
    grounding re-run, default-off.
- **Iteration 2** — cost / sequencing / feedback-loop critic, plan-as-written. Files
  reviewed: ingest/replay.py, ingest/pipeline.py, eval/run.py, eval/sample/{README,
  build_sample}.py, the Makefile(s), memory `helixpay-replay-vs-prod-seed`.
  - CRITICAL: the plan's "B is $0-replayable" premise is **false** — the cache stores
    post-drop `ExtractionOut` (`replay.py:91`); dropped items were never cached.
    **Resolved:** B reclassified as paid-re-record-only; **Cost & Sequencing** rewritten;
    the only $0 step is re-confirming SP_010's resolution on the new cache.
  - HIGH: "C done after step 2" is wasteful — A re-keys the cache by `(source_uri,
    ordinal)`, so resolution must be re-validated on the post-re-record cache.
    **Resolved:** step 4 added.
  - HIGH: the 11-doc sample sees only 1 of 3 dashboards and can't score Defect A beyond
    `april`'s 2 facts; over-extraction of non-golden junk is invisible to precision.
    **Resolved:** micro-fixture for A, full Tier-2 gate + per-fact verdict diff + claim-count
    sentinel as the acceptance gate.
- **Supporting evidence** — a code ground-truth pass verified every file:line claim above
  (`_MAX_TOKENS=4096` `llm.py:26`; `stop_reason` never inspected; `_validate_items` drop
  `extractor.py:208-220`; silent empty `extractor.py:82-84`; strict ISO `schemas.py:28-32`;
  cache stores post-drop `replay.py:91`; resolver lexical + seeded-ordered
  `repository.py:182-220`). CONFIRMED except: Defect-A empty path **is** logged one layer
  down (no counter) — folded into the ledger rationale.

### Post-Implementation Review

> Plan-blind, over changed code + tests, after `pytest`/`mypy` pass and before the paid
> records (Rule 9). Floor = 2 for Standard. Implemented by a parallel build agent; reviewed
> by an independent plan-blind `code-reviewer` (Rule 5 — reviewer saw code+tests only).

- **Iteration 1** — independent plan-blind `code-reviewer`. Verdict **SHIP-WITH-FIXES**
  (0 CRITICAL). All findings verified against `uv run pytest test/unit/ingest` evidence and
  resolved:
  - **HIGH H1 — `leads`/`functional lead` direction.** The reviewer found that a superiority
    verb ("Alice leads Bob" → Alice is the functional superior) must invert from/to exactly
    like `manages`, or it plants a **backwards `dotted_line_to` edge** — the precise
    false-hierarchy class this sprint exists to prevent. **This overrides the plan's
    "only `manages` inverts" Stage-3 wording**, which was internally inconsistent with its
    own no-reversed-edges principle. **Resolved:** `leads`/`lead`/`functional lead` now map
    to `dotted_line_to` *with* inversion; subordinate-phrasing (`dotted line to`, …) stays
    no-invert. The invariant the plan actually cared about — `leads` is **never** a
    `reports_to` — is preserved and unit-asserted (`test_leads_is_never_reports_to`). This is
    a deliberate, recorded plan deviation (governance: implementation/review revealed the
    plan wrong → fix + document).
  - **MEDIUM M1 — coercions lost on drop.** `coerce_item` now threads accumulated coercions
    through every drop return, so an `as_of` coercion that precedes a `subject_type`/`link`
    drop is still ledger-counted (the extractor's drop-path loop is no longer dead).
  - **MEDIUM M2 — `probe()` lists chunk-only URIs with zeros.** Kept (NOT filtered) — it is
    load-bearing for the SP_015 seam (present-with-zeros = cleanly extracted = PASS-eligible;
    absent = never extracted = INCOMPLETE). Documented in `probe()`.
  - **LOW L1 — ambiguous multi-quarter `as_of`** now drops (`unparseable_as_of`) instead of
    silently taking the first match (`test_ambiguous_multi_quarter_as_of_drops`).
  - **LOW L2 —** `pipeline.IngestReport.ledger` forward-ref simplified to `Optional[LossLedger]`.
  - Confirmed SOUND by the reviewer: `as_of` coercion paths, `generate`-only back-compat,
    truncation-flag accumulation across the repair turn, ledger accounting, `probe()`/`summary()`
    shapes, no secrets logged, layer boundaries. Post-fix: **230 ingest tests pass; mypy clean.**
- **Iteration 2** — **pending runtime verification (DB-gated, paid, Rule 21 behavioral
  closure):** recall ≥85% + both contradictions + name-traps on the sample re-record, as
  runtime evidence. Held at the operator boundary — no DB/paid calls in the build environment.
  See **Hand-off**. Sprint stays **In Progress** until this replay lands.

## Hand-off

- **Pending operator smoke (Rule 21):** after merge — micro-fixture `--force` record →
  sample `--force` record on `helixpay_sample` → `eval.run --recall-bar 0.85`; confirm
  recall ≥85%, both contradictions, name-traps; then one full 44-doc `--force` record →
  full eval → `pg_dump` as the production seed. No DB in the build environment.
- Merge order **SP_010 → SP_014**. SP_014 consumes SP_010's resolution baseline + replay
  tier; the full re-record here is the corpus's intended **single** paid extraction (memory:
  `helixpay-replay-vs-prod-seed`).
- The loss ledger becomes the standing instrument for all future extraction tuning — any
  later recall change reports its before/after through it.
