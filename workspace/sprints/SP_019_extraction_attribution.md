---
sprint_id: SP_019
tier: Standard
features: [metric-subject-repair, roster-snap-resolution, attribution-prompt-surgery, zero-cost-attribution-proof]
user_stories: []
schema_touched: false
structure_touched: false
status: In Progress
isolation: branch-only
branch: sprint/SP_019-extraction-attribution
worktree: ""
agent_owner: "Agent (extraction-attribution)"
dependencies: [SP_010, SP_014, SP_015]
dev_dependencies: []
touches_paths:
  - helixpay/ingest/repair.py
  - helixpay/ingest/pipeline.py
  - helixpay/ingest/resolve.py
  - prompts/extract_claims.md
  - helixpay/ingest/extract/extractor.py
  - test/unit/ingest/test_repair.py
  - test/unit/ingest/test_resolve.py
  - test/unit/ingest/test_pipeline.py
  - test/unit/ingest/test_prompts.py
  - workspace/acceptance/SP019_attribution_run.md
touches_checklist_items: [attribution-metric-repair, attribution-roster-snap, attribution-prompt-subject, attribution-zero-cost-proof, attribution-prompt-rerecord-gated]
---

# SP_019: Extraction attribution — fix the metric-as-subject defect and chart the path to ≥80%

## Sprint Goal

SP_015 proved extraction is **mechanically clean** (no silent loss on any archetype) but
golden recall plateaus at **4/11** on the smoke set. The deep research (three streams,
`RECALL_AND_ITERATION_REPORT.md`) pointed at **metric-as-subject** attribution; a direct
audit of the `.replay-cache/` (Stage-3 review) sharpened that into a precise, evidence-based
diagnosis that this sprint implements against.

**Two deterministic, $0 layers fix real attribution bugs in the codebase; one paid layer is
the actual lever to ≥80% recall and stays spend-gated.**

- **Layer 0 — metric→primary-entity repair (deterministic, $0).** A pure post-extraction
  transform: a claim typed `subject_type="metric"` whose subject is a *known company metric*
  is re-attributed to the document's primary entity (the company), with the metric moved to
  the predicate. Period-qualifier-aware so `"Q1 2026 Revenue"` is recognised, not just bare
  `"Revenue"`. The OAK+MEND domain-range pattern (a metric predicate's domain is an entity).
- **Layer 2 — seeded-roster snap before minting (deterministic, $0).** Before
  `resolve_mention` mints an open-class entity, it tries a **type-agnostic seeded match**; an
  exact seeded hit wins — killing the `metric|HelixPay` duplicate that a company name typed
  `metric` mints today (the iText2KG / ReLiK snap-to-known-roster pattern).
- **Layer 1 — attribution prompt surgery (paid re-record, GATED).** Rewrite
  `prompts/extract_claims.md` so the model fixes the defect *at the source*: attribute
  ownerless KPIs to the document's primary entity (or its named region), emit **canonical,
  period-stripped predicates**, and put the **value's own reporting period in `as_of`** (the
  quarter-end, not the dashboard's "as of" date). One negative few-shot pair incl. the
  regional case. Implemented here; its lift is measurable only by a **paid re-record** and is
  recorded as **pending operator-approved spend** with exact cost.

### The honest recall picture (Stage-3 cache audit — this is the load-bearing correction)

A claim-by-claim audit of the cached extractions against the smoke golden (`eval/run.py`
grader semantics) shows the **dominant blocker for the 7 failing golden facts is NOT
subject attribution** — it is **as_of / predicate / claim-shape baked into the cache**, which
**no $0 post-processing can repair**:

| golden fact | cache reality | $0 layers reach | needs re-record? |
|---|---|---|---|
| dashboard `revenue` 14.2M @ **2026-03-31** | `metric\|Q1 2026 Revenue`, as_of **2026-04-21** (doc date, not Q1-end) | MISSING→**MISMATCH** (L0 fixes subject; as_of still wrong) | **yes** (as_of) |
| dashboard `nps` 47 @ **2026-03-31** | `metric\|Aggregate NPS`, as_of **2026-04-21** | MISSING→**MISMATCH** | **yes** (as_of) |
| `Project Confluence` `ga_target` end-Q3 | buried in odd predicates on `HelixPay` | no clean claim to repair | **yes** (shape) |
| `helixpay/core` `top_contributor` Sara | `helixpay/core` / **`primary owner`** / Sara / 2026-04-08 | predicate+as_of off | **yes** (+ SP_010 vocab) |
| `HelixPay Brasil` `revenue` 4.8M | regional, distinct subject (correctly) | n/a | **yes** (attribution+as_of) |
| `CRM migration` `completion_target` end-Jun | chat | shape/predicate | **yes** |
| `Maria Santos` owns `Açaí Express SP` | email relations | link/resolution | **yes** |

The grader (`eval/run.py:145`) accepts as_of when **either** the claim's as_of **or any
source's** as_of equals golden; the dashboard document's as_of is itself `2026-04-21`, so the
dashboard facts cannot pass on as_of without a re-extraction that emits the Q1-end date.

**Conclusion the operator needs:** reaching ≥80% **requires the Layer-1 re-record** — Layers
0+2 are correctness fixes that make the system right (and make the re-record land cleanly),
but they do not move the golden number at $0. This sprint ships the deterministic fixes,
proves them in isolation, runs a $0 diagnostic that *confirms* the as_of-baking thesis, and
delivers an **evidenced, costed re-record proposal** as the validated path to ≥80%. No $0
recall lift is claimed.

## Current State

- SP_015 fix #1 (roster-first `resolve_entity`) + fix #2 (period-strip in
  `repository.canonical_predicate`) → recall **4/11 FOUND** (runway, headcount, both org
  links). Deterministic.
- `.replay-cache/` audit (19 chunks, 9 docs): the **board-deck already attributes metrics to
  `subject="HelixPay"`** (defect there is the period-qualified predicate, already handled by
  fix #2); genuine **metric-as-subject** lives in the **dashboard** (`metric|Q1 2026 Revenue`,
  `metric|Aggregate NPS`, …) and the **chat** (`metric|April MTD revenue`, …). A company name
  typed `metric` would mint `metric|HelixPay` (the dupe Layer 2 kills).
- `prompts/extract_claims.md:19-25` licenses `subject` = *"a metric name like ARR"* and the
  JSON example hardcodes `"subject_type": "metric"` — the upstream root.
- `resolve_mention` (`resolve.py`) mints when a *typed* resolve misses; it has no
  type-agnostic seeded fallback. `DEFAULT_CREATABLE_TYPES = {customer, metric, product, other}`.
- The replay tier (`replay.py`, SP_010) re-runs resolve→canonicalize→persist→contradict from
  cache with a $0 constant embedder — the diagnostic vehicle (run, not edited, by this sprint).

## Scope

**In:**
- `helixpay/ingest/repair.py` (NEW) — pure `repair_metric_subject(claim_out, *, primary_entity, known_metric) -> ClaimOut`; owns `KNOWN_KEYS` + the period-qualifier-aware `known_metric` predicate; no I/O.
- `helixpay/ingest/pipeline.py` — wire repair into `_ingest_document` **before** `resolve_mention`; resolve+seed-validate the primary entity once per run (no hardcoded module constant).
- `helixpay/ingest/resolve.py` — type-agnostic **seeded-roster snap** before the mint branch; refactor the variant list to a named `variants = _dedup([name, folded])`.
- `prompts/extract_claims.md` — Layer-1 subject/predicate/as_of guidance + negative few-shot (incl. regional case) + fixed JSON example.
- `helixpay/ingest/extract/extractor.py` — minimal system-prompt nudge only if needed.
- Unit tests; the $0 diagnostic run record + costed re-record proposal in `workspace/acceptance/SP019_attribution_run.md`.

**Out (and who owns it):**
- `helixpay/seed/metric_vocab.py` / `roster.py` — **SP_010** (fresh active claims). We
  **import** the canonical-key set read-only. Surface-form alias expansion (Confluence/CRM)
  and any vocab change (e.g. `primary owner`→`top_contributor`) are **handed to SP_010**.
- `helixpay/ingest/replay.py` / `contradict.py` / `Makefile` — **SP_010** (run, not edit).
- `eval/smoke/*` / `scripts/full_run.py` / `scripts/run_smoke.py` — **SP_015** harness (run, not edit).
- The **paid re-record** measuring Layer 1 — operator spend-gated.
- `EntityType` enum (frozen) — `metric` stays valid; we fix behavior, never fork the contract.

## Technical Approach

### Layer 0 — `helixpay/ingest/repair.py` (deterministic, pure)
```
repair_metric_subject(claim_out, *, primary_entity, known_metric) -> ClaimOut
```
- No-op unless `claim_out.subject_type == "metric"`.
- `KNOWN_KEYS = {k for k,_,_ in metric_vocab.METRIC_VOCAB}` (imported read-only; the in-memory
  vocab is the seed source of truth).
- `known_metric(s)`: `canonical_key(_strip_period(s)) in KNOWN_KEYS` — **period-aware** so
  `"Q1 2026 Revenue"`→`"Revenue"`→`"revenue"` ∈ keys (HIGH-1). `_strip_period` is a tiny pure
  helper mirroring `repository._strip_period_qualifier` (leading `Q[1-4]/H[12]/FY/20\d\d`
  token); kept local to `repair.py` (no SP_010 file touched).
- When `known_metric(subject)` fires:
  - `predicate := existing predicate` if `known_metric(existing predicate)` (it already names a
    metric, e.g. `"Q1 2026 Revenue (SGD)"` → downstream `canonical_predicate` strips it), else
    `:= subject` (the metric moves out of the subject slot);
  - `subject := primary_entity` (the seed-validated company canonical name);
  - `subject_type := "other"` (must equal `EntityType.other.value` — asserted by a unit test, L-1).
- Otherwise return `claim_out` **unchanged** — a regional/unknown metric (`"HelixPay Brasil
  revenue"` → unknown key), a non-company metric, or any non-metric subject is never touched.
  This is what keeps the planted Brasil-vs-company values on **distinct** subjects (no false
  contradiction).
- as_of is **not** rewritten here (the value's-own-period correction is a Layer-1 prompt fix;
  doing it deterministically only helps facts whose label embeds an explicit quarter and is
  noted as a deferred extension, not core).

### Layer 0 wiring — `pipeline.py`
- In `run()`: resolve `"HelixPay"` once via `repo.resolve_entity("HelixPay", "other", None)`,
  **assert it is seeded** (loud failure on a roster rename, never silent re-mint — HIGH-3), and
  pass its `canonical_name` as `primary_entity` down into `_ingest_document`. No
  `DEFAULT_PRIMARY_ENTITY` module constant.
- In `_ingest_document`: pass each `claim_out` through `repair_metric_subject(...)` **before**
  `resolve_mention`. Ordering is sound — repair changes *what entity the claim is about* before
  resolution; the moved predicate is still canonicalized downstream by `repo.canonical_predicate`.

### Layer 2 — `resolve.py:resolve_mention` seeded-roster snap
- Refactor: `variants = _dedup([name, folded])` as a named local before the existing typed loop
  (H-2). After the typed attempts and **before** the `allow_create_types` mint:
```
for variant in variants:
    ent = repo.resolve_entity(variant, None, context)   # type-agnostic
    if ent is not None and ent.id is not None and ent.seeded:
        return ent.id                                    # snap to seeded, never mint
```
- Snaps only to a **seeded** entity and only when type-agnostic resolve is unambiguous
  (`resolve_entity` already returns `None` for the two-Marias/two-Tans bare-name trap — preserved
  verbatim).
- **Distinct from Layer 0** (not dead code): L0 handles *metric-name-as-subject*; L2 handles a
  *company/entity name mis-typed `metric`* (e.g. `subject="HelixPay", subject_type="metric"`),
  which L0 leaves alone because `"HelixPay"` is not a known metric key.

### Layer 1 — `prompts/extract_claims.md` (paid; gated measurement)
- Rewrite `subject` / `subject_type` / `predicate` / `as_of` guidance:
  - subject is an **entity** (person/team/customer/product/company/region) — **never a bare
    metric name**; an ownerless KPI's subject is the document's primary entity (HelixPay, or the
    **named region/subsidiary** if explicitly scoped, e.g. "HelixPay Brasil");
  - the metric is the **predicate**, canonical and **period-stripped** (`revenue`, not
    "Q1 revenue"); the period goes in `as_of`;
  - **as_of = the value's own reporting period end** (Q1 2026 → 2026-03-31), preferred over the
    document's "as of" date (the dashboard-as_of bug);
  - fix the JSON example (no `"subject_type": "metric"` exemplar).
- Add **one negative few-shot pair**, including the regional case: bad `subject:"Revenue"` /
  `subject_type:"metric"` → good `subject:"HelixPay"` / `predicate:"revenue"` /
  `as_of:"2026-03-31"`; and a Brasil line → `subject:"HelixPay Brasil"` (never collapsed to
  HelixPay — HIGH-2).
- Keep every existing rule (no-collapse, capture as-of, name-trap discipline, skip chrome).

### Measurement
- **Automated, $0, in-scope (the deterministic proof):** `test/unit/ingest/test_pipeline.py`
  drives the **real cached** dashboard/chat `ClaimOut`s through `_ingest_document`
  (repair+snap) against a stub repo and asserts the metric claims now resolve to the seeded
  company id with a canonical predicate, and that **no `metric|HelixPay` is minted**. No DB,
  deterministic — this is the sprint's hard evidence for Layers 0+2.
- **Operational, $0 diagnostic (confirms the thesis):** on the existing `helixpay_smoke` DB
  (chunks+embeddings+seeded intact), reset derived rows (claims/links/non-seeded entities) via a
  one-off operational `psql` on the throwaway DB — **not** shipped code, **no** `Repository`
  delete method added, **no** raw SQL in the codebase — then `python -m helixpay.ingest.replay
  replay` ($0) + `check_smoke`. Expected result: dashboard revenue/NPS move MISSING→**MISMATCH**
  (subject fixed, as_of still off) and the `metric|HelixPay` dupe is gone — *evidence that the
  residual is as_of/shape, i.e. the re-record case*. Recorded in the run finding.
- **Paid re-record (Layer 1) — GATED:** exact-cost 9-doc re-record on `helixpay_smoke`
  (Sonnet extract + Voyage embed, no Opus — minutes and cents), recorded as **pending operator
  approval**. This is the measured path to ≥80%; not run without explicit go.

## Testing Strategy

- `test/unit/ingest/test_repair.py` (NEW): `repair_metric_subject` re-attributes
  `subject="Q1 2026 Revenue"`/`metric` and `subject="Aggregate NPS"`/`metric` to the primary
  entity with the metric as predicate (period-aware gate); **no-op** for (a) non-metric
  `subject_type`, (b) unknown/regional key (`"HelixPay Brasil revenue"`), (c) a real entity
  mis-typed metric that is not a known metric (`"HelixPay"`); keeps an existing predicate that
  is a known metric **alias** (`"annual recurring revenue"`→arr) vs replacing a non-metric
  predicate (`"Q1 2026"`) with the subject (M-1); `known_metric("")` is `False` (L-3); pure
  (no repo calls); the hardcoded `"other"` equals `EntityType.other.value` (L-1).
- `test/unit/ingest/test_resolve.py` (edit): give `FakeRepo.resolve_entity` the **seeded-first
  filter** the real repo has (H-1); a mention typed `metric` whose name matches a **seeded**
  `other` entity snaps to the seeded id with **no mint**, including when a `metric|HelixPay`
  (seeded=False) dupe already exists at snap time (H-1); an ambiguous bare name still returns
  `None` (two-Marias trap intact); a genuinely new open-class mention still mints.
- `test/unit/ingest/test_pipeline.py` (edit): the real cached dashboard/chat metric claims flow
  through `_ingest_document` and land on the seeded company id, not a minted metric row (the $0
  automated proof above).
- `test/unit/ingest/test_prompts.py` (edit): the rendered `extract_claims` prompt asserts the
  exact removed strings are gone — `"metric name like" not in out` and `'"subject_type":
  "metric"' not in out` (L-2) — guarding the Layer-1 intent against regression.
- `uv run pytest test` green; `uv run mypy helixpay` clean; dev gateway passes.
- **Acceptance ($0 diagnostic, DB-gated):** the operational replay re-measure, written into
  `SP019_attribution_run.md` with the per-fact before/after table and the costed re-record plan.
  Paid Layer-1 re-record recorded as pending operator smoke (Rule 21).

## Success Criteria

- `repair.py` + `resolve.py` snap + pipeline wiring land with unit tests; `metric` stays a valid
  `EntityType` (no contract fork); the primary entity is **seed-validated** at run start (loud
  failure on a roster rename), with **no** hardcoded company constant at module scope.
- The **automated $0 proof** is green: the real cached dashboard/chat metric claims resolve to
  the seeded `other|HelixPay` (canonical predicate) through the pipeline, and **no
  `metric|HelixPay` is minted**; the two-Marias/two-Tans traps still return `None`; an
  unknown/regional metric (`"HelixPay Brasil revenue"`) is **untouched** (no false merge).
- `prompts/extract_claims.md` no longer licenses metric-as-subject; the prompt-intent test guards it.
- `workspace/acceptance/SP019_attribution_run.md` records: (a) the $0 diagnostic before/after
  (expected dashboard MISSING→MISMATCH, dupe gone), (b) the explicit statement that the golden
  lift to ≥80% requires the gated re-record, with exact cost. **No $0 recall number is claimed
  as the headline.**
- `uv run pytest test` green; `uv run mypy helixpay` clean.

## Risks & Mitigations

- **Over-claiming a $0 recall lift.** The cache audit shows the failing golden facts are blocked
  on as_of/predicate/shape baked into the cache. Mitigation: the sprint claims only the
  deterministic **correctness** fix (subject attribution, dupe elimination), proven by
  unit/integration tests; the recall lift is explicitly gated behind the re-record.
- **Repair merging distinct facts → false contradiction.** Mitigation: fires only for a known
  *company* metric key; regional/unknown metrics (Brasil) are never touched, so the planted
  Brasil-vs-company values stay distinct (verified: `canonical_key("HelixPay Brasil revenue")`
  is unknown). Success criterion asserts no false merge.
- **Repair re-attributes a metric that belongs to a customer/product.** In the smoke set the
  known-metric cards are company-level. Mitigation: the conservative known-metric gate; a real
  customer metric usually carries an explicit owner. The durable fix is Layer 1 (explicit owner
  in the prompt). Residual surfaced in the finding.
- **Seeded-snap mis-collapses two entities** (e.g. parent vs subsidiary). Mitigation: snap only
  to a **seeded** entity and only on an unambiguous type-agnostic resolve; the two-Marias guard
  (`resolve_entity`→`None` on shared bare names) is preserved. A resolve test pins that
  "Helix Brasil" / "Helix" never cross (guards a future SP_010 alias collision).
- **Layer 1 lift unmeasured until a paid re-record.** Accepted and explicit: implemented now,
  measured under the spend gate.
- **Cross-sprint coordination.** Alias expansion + `metric_vocab` changes are **SP_010**'s
  (handed off via the finding); no SP_010/SP_015-claimed path is edited; the $0 reset is an
  operational `psql` on a throwaway DB, not shipped code (no `Repository` delete added).
- **Secret handling (CLAUDE.md §7).** The run record names the DB (`helixpay_smoke`) only —
  never `DATABASE_URL`/any DSN; no secret or connection string logged.

### Pre-Implementation Review

> Standard tier — review-iteration floor = 2 (`practices/GL-SELF-CRITIQUE.md`). Two independent
> reviewers ran plan-as-written at Stage 3; both returned **GO-WITH-CHANGES**; every required
> change is folded into the design above, and the cache audit they prompted produced the
> load-bearing diagnosis correction (the recall blocker is as_of/shape, not just subject).

- **Iteration 1** — architect-reviewer, plan-as-written. Files reviewed: SP_019 plan,
  pipeline.py, resolve.py, extract/schemas.py, seed/metric_vocab.py, db/repository.py
  (resolve_entity/canonical_predicate), ingest/contradict.py, contracts/models.py,
  scripts/run_smoke.py, seed/roster.py. **0 CRITICAL after folding; 2 raised then resolved.**
  - **CRITICAL (measurement unbuildable in-scope):** the planned "$0 replay that clears
    claims/minted entities" needs a delete path that does not exist (`Repository` has no delete;
    `replay.py` is SP_010's; no raw SQL allowed outside `helixpay/db/`). **Resolved:** drop the
    shipped-clear approach; the $0 diagnostic uses an **operational** `psql` reset on the
    throwaway `helixpay_smoke` DB + the existing `replay` CLI (run, not edited), and the hard
    automated proof becomes a **no-DB** pipeline test over the real cache. No destructive code shipped.
  - **CRITICAL (L2 not independently measurable):** with L0 in place, the `metric|HelixPay` case
    is intercepted before L2. **Resolved:** L2 reframed as the distinct *company-name-mis-typed-
    metric* fix (not the same path as L0) + a dedicated test; no isolated L2 recall delta claimed.
  - **HIGH (gate misses period-qualified subjects):** `canonical_key("Q1 2026 Revenue")` is
    unknown, so the bare gate would not fire on the actual dashboard surface form. **Resolved:**
    the `known_metric` gate strips a leading period qualifier before lookup.
  - **HIGH (DEFAULT_PRIMARY_ENTITY module constant is a landmine):** a roster rename would
    silently re-mint. **Resolved:** resolve+seed-validate the primary entity at run start, pass
    it in; no module constant.
  - **HIGH/MEDIUM (contradiction assertions both directions):** **Resolved:** acceptance asserts
    no *false* `revenue` contradiction on HelixPay from a Brasil source, and (post-re-record) the
    *true* planted same-period contradiction is surfaced.
- **Iteration 2** — code-reviewer, plan-as-written, adversarial. Files reviewed: SP_019 plan,
  resolve.py, pipeline.py, extract/schemas.py, seed/metric_vocab.py, db/repository.py,
  prompts/extract_claims.md, extract/extractor.py, extract/prompts.py, test/unit/ingest/
  test_resolve.py, test/unit/ingest/test_pipeline.py. **0 CRITICAL; 2 HIGH + 3 MEDIUM/LOW, all
  folded.**
  - **HIGH (FakeRepo lacks seeded-first filter):** the snap test would pass for the wrong reason.
    **Resolved:** test plan adds the seeded-first filter to `FakeRepo.resolve_entity` + a
    "minted dupe present at snap time" case.
  - **HIGH (`variants` undefined in pseudocode):** **Resolved:** refactor to a named
    `variants = _dedup([name, folded])` before both loops.
  - **MEDIUM (missing predicate-selection test cases):** **Resolved:** added the
    period-qualified-predicate and known-alias-predicate cases to `test_repair.py`.
  - **MEDIUM (`known_metric`/`KNOWN_KEYS` location):** **Resolved:** owned by `repair.py`.
  - **MEDIUM/LOW (L0/L2 interaction unstated; `model_copy` skips validators; thin prompt
    assertions; empty-string contract):** **Resolved:** L0/L2 framing stated, `"other"`==
    `EntityType.other.value` asserted, exact prompt strings asserted, `known_metric("")` tested.

### Post-Implementation Review

> Plan-blind review over changed code + tests after `pytest` passes (Rule 9). Floor = 2.

- _(to be completed after implementation)_

## Hand-off

- **To SP_010 (resolution/seeding substrate):** (1) surface-form alias expansion so
  "Confluence platform"/"Confluence GA"/"CRM migration" snap to their seeded canonical entities;
  (2) a `top_contributor`/`primary owner` predicate mapping (or a roster decision) for
  `helixpay/core`; (3) optionally mirror the period-strip into `metric_vocab.canonical_key` (the
  pure-path mirror deferred in SP_015 717c4ec). All are SP_010-file edits.
- **To the operator (paid gate):** the Layer-1 prompt is implemented; reaching ≥80% requires one
  paid 9-doc re-record on `helixpay_smoke` (Sonnet + Voyage, no Opus — minutes and cents). Exact
  cost recorded in `SP019_attribution_run.md`. **This is the measured path; the deterministic
  layers do not move the golden number at $0.**
- **The one line for the runbook:** Layers 0+2 make attribution *correct* (proven at $0); the
  recall lift to ≥80% is the gated re-record — do not quote a recall number until it runs.
