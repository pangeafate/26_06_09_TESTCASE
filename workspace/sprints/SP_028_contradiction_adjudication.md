---
sprint_id: SP_028
tier: Foundational
features: []
user_stories:
  - "As the operator, the system DETECTS genuine cross-document contradictions it currently misses (1/8 of the human-found set) and STOPS emitting the ~85% spurious rows (266 → a real number), because a post-ingest LLM adjudication pass judges clusters of related claims — surfacing both sides with cited claim ids, never resolving to one value — while a deterministic pre-filter kills format/multi-valued noise before any paid call."
  - "As the operator, the adjudication is reproducible and $0 on replay, because every verdict is cached on a content hash of (model, prompt_version, normalization_version, sorted claim_ids); re-running an unchanged store calls no LLM."
schema_touched: false
structure_touched: false
status: Planned
isolation: shared-tree
branch: sprint/SP_023-graph-temporal-tools
worktree: ""
agent_owner: "main (operator-directed)"
dependencies: [SP_009, SP_026, SP_027]
dev_dependencies: []
touches_paths:
  - prompts/adjudicate_contradictions.md
  - helixpay/ingest/adjudicate.py
  - helixpay/ingest/predicate_cardinality.py
  - helixpay/ingest/normalize.py
  - scripts/adjudicate_contradictions.py
  - test/unit/ingest/test_adjudicate.py
  - test/unit/ingest/test_predicate_cardinality.py
  - test/unit/ingest/test_normalize.py
  - test/integration/db/test_adjudicate_integration.py
  - eval/contradiction_recall.py
  - CLAUDE.md
  - workspace/sprints/SP_028_contradiction_adjudication.md
touches_checklist_items: [norm-sign-date-currency, predicate-cardinality-table, candidate-gen-cluster, candidate-gen-cross-predicate, adjudicate-prompt, adjudicate-schema, adjudicate-llm-seam, adjudicate-cache, adjudicate-write-rows, adjudicate-cli, oracle-score-wiring, claude-md-adjudication-gotcha]
---

# SP_028: LLM contradiction adjudication — detect real conflicts, kill the spurious

## Sprint Goal

Add a **post-ingest contradiction-adjudication pass** that turns the contradiction layer from a
lexical same-predicate comparator (1/8 recall, ~85% spurious of 266 rows) into a two-stage
**candidate-generation → LLM-adjudication** pipeline that materializes the genuine,
deduplicated, typed contradiction set with cited claim ids — and **never resolves to one value**
(both claims coexist; CLAUDE.md ontology rule). Measured blind against `test/golden/
contradictions.yaml` (the SP_027-era oracle) via the existing `eval/contradiction_recall.py`
scorer.

This implements the architecture agreed with the operator: **global detection of record at
ingest time, materialized + always-surfaced; the consumer agent is additive only.**

## Where it runs (placement)

A **separate sweep AFTER full ingest**, over the whole store — NOT inline per-document
(contradictions are cross-document; a per-doc pass sees incomplete clusters). Logically this is
where `scripts/recompute_contradictions.py` already runs (clear + re-detect over distinct groups);
SP_028 evolves that into the staged sweep. Caching keeps it cheap on incremental re-runs
(unchanged cluster → cache hit → skip), so the "post-ingest sweep" keeps today's `touched_groups`
efficiency via the cache key, not via inline coupling.

## The pipeline (four stages)

```
Stage 1  CANDIDATE GENERATION (deterministic, LOOSE, high-recall)
   cluster live claims by subject_entity_id; WITHIN a subject also group across predicates
   (so the cross-predicate Maria reports_to+dotted_line case can form a candidate).
   [Entity-fragment MERGING is the highest-risk lever — see Risk; v1 is conservative.]
Stage 2  DETERMINISTIC PRE-FILTER (cheap, $0, kills the spurious BEFORE any LLM call)
   (a) normalize.py upgrades: sign/currency-position (SGD -2.1M ≡ -SGD 2.1M), date-format
       (2026-05-12 ≡ "May 12"), rounding tolerance → format-equivalents are NOT conflicts.
   (b) predicate_cardinality.py: a data-driven table marking predicates functional
       (one true value → candidate) vs SET-valued (pain_point, weekly_activity, attendee,
       responsibilities → multiplicity is NEVER a conflict) vs sub-entity-breakdown
       (Açaí gross_revenue by product line → not a total conflict). Drops these clusters.
Stage 3  LLM ADJUDICATION (Opus; only on surviving clusters)
   one structured call per cluster → emits genuine contradictions: {claim_a_id, claim_b_id,
   kind, rationale}, each id MUST exist in the cluster (validate-and-drop; zero uncited).
   Cached on hash(model, prompt_version, norm_version, sorted(claim_ids)) → $0 replay.
Stage 4  WRITE ROWS  reuse Repository.add_contradiction (idempotent). Provenance recorded in
   the existing Contradiction.note/kind (NO schema/contract change — avoids models.py).
```

## Cost discipline (operator is cost-sensitive)

- **All code + unit tests run at $0** with an injected stub adjudicator (mirrors the extraction
  `LLMClient` stub pattern). No test calls a real model.
- The **paid** run is a single explicit CLI step (`scripts/adjudicate_contradictions.py`),
  operator-invoked — same gating as the re-record. Stage 2 runs $0 and is measured first, so we
  see how far the deterministic layer alone moves precision/recall before spending on the LLM.
- Caching makes re-runs $0; a `--dry-run` prints cluster counts + estimated calls before paying.

## Contracts / boundaries

- **No frozen-contract change.** Reuse `Contradiction`, `Repository.{get_claims,
  get_contradictions, add_contradiction, resolve_entity, canonical_predicate}`. Adjudication
  provenance lives in `note` (prefix `[llm]` / `[deterministic]`) and `kind`.
- New code respects layer boundaries: `adjudicate.py` is ingest-shared-logic; the LLM seam reuses
  `helixpay/ingest/extract/llm.py` `call_structured` (named prompt + schema + validate-or-drop).
- Prompt `prompts/adjudicate_contradictions.md` + a Pydantic output schema (NOT in the SP_025
  `extract/schemas.py` — a new local schema to avoid path overlap).
- `normalize.py` is shared substrate (SP_009); changes are additive and covered by existing +
  new tests. (Note: it is NOT in any active In-Progress sprint's `touches_paths` — overlap-clean.)

## TDD plan (Rule 1 — failing test first for each unit)

1. `test_normalize.py`: sign/currency-position + date-format equivalence cases → RED → implement.
2. `test_predicate_cardinality.py`: functional vs set-valued vs breakdown classification, and that
   `canonical_predicate` keys map correctly → RED → implement the data table.
3. `test_adjudicate.py` (stub LLM):
   - candidate generation clusters by subject + cross-predicate;
   - Stage-2 pre-filter drops a set-valued cluster and a format-equivalent pair;
   - a scripted stub adjudicator returns a verdict citing two cluster claim ids → a row is written;
   - a verdict citing a NON-cluster id is dropped (zero-uncited guard);
   - cache: second run with same cluster hash makes NO stub call (assert call count).
4. `test_adjudicate_integration.py` (db-marked, $0 stub): end-to-end over a seeded mini-store;
   asserts the planted same-period conflict surfaces and a multi-valued predicate does not.
5. **Oracle measurement** (not a unit assert — a reported metric): run the $0 deterministic layer
   then the stubbed adjudicator over `helixpay_full`; print `eval.contradiction_recall` scorecard.
   The real catch-rate lift is confirmed only by the **paid** run (gated).

## Acceptance

- Deterministic Stage 2 alone: 266 spurious collapses materially (target: the
  format/multi-valued/breakdown classes from the audit gone) with **zero** real contradictions
  lost (the oracle baseline `confluence-ga-target` still caught).
- With the paid LLM pass: oracle catch-rate rises from 1/8 toward the cross-predicate/semantic
  items (#2/#4/#6/#8) and the entity-merge items (#3/#5) as candidate-gen widens.
- Reproducible: a second sweep on the unchanged store issues **0** LLM calls (cache hit).
- `ask()` / MCP still surface contradictions present-and-empty; both sides always cited.

## Risk

- **Entity-fragment merging is the highest-risk lever** (it gated 3 oracle items). Merging too
  loosely re-creates the two-Marias/two-Tans false merge. **v1 is conservative**: cluster only by
  existing `subject_entity_id` + cross-predicate; a *separate, guarded* fragment-bridge (exact
  normalized name + same type + a shared external id like a ticket/deal id) is a clearly-fenced
  sub-item that may be **split to SP_029** if Stage-3 review flags it as too broad for one sprint.
- **LLM nondeterminism / hallucinated citations** → temperature 0, structured output, every cited
  id validated against the cluster (drop on miss), cached. Same discipline as extraction.
- **Cache staleness on vocab/prompt change** → the key includes `norm_version` + `prompt_version`;
  bump them when normalization or the prompt changes (documented gotcha).
- **module size**: `repository.py` is already 852 lines (>800 warn) — SP_028 adds NO repository
  method (reuses existing reads), so it does not worsen the God-file.

## Stage 3 / Stage 5 review

Foundational → ≥2 plan-review and ≥2 post-impl iterations, plan-blind at Stage 5. Reviewers
named in Progress.

## Progress

- **Stage 2 (plan)** 2026-06-11 — written.
- **Stage 3 (plan review, 2 independent contexts)** 2026-06-11 — architect + code reviewers.
  **Verdict: do NOT implement as written.** Both independently recommend a SPLIT. Findings:
  - **C1 (architect, CRITICAL)** — `contradictions` has `UNIQUE (claim_a_id, claim_b_id)` +
    `ON CONFLICT DO NOTHING`, so deterministic and LLM rows for the same pair collide silently
    (kind/note not in key). The sweep must be **single-writer: clear-then-rewrite** (the
    `recompute_contradictions.py` model); deterministic `detect()` becomes Stage-1 *inside* the
    sweep, never a concurrent writer.
  - **C2 (architect, CRITICAL) / M1 (code)** — cache key on `sorted(claim_ids)` (BIGSERIAL) is
    NOT stable across re-seed/re-ingest → cache misses 100% after any rebuild → "$0 replay"
    fails. Key on **semantic content** `(subject, canonical_predicate, normalize_value, as_of,
    source_uri)`, not surrogate ids.
  - **C1 (code, CRITICAL)** — "date-format `2026-05-12 ≡ May 12`" in the SHARED `normalize.py`
    drops the year → cross-year false-equality → suppresses real contradictions AND corrupts the
    oracle scorer (which calls `normalize_value`). Keep date logic OUT of the shared normalizer;
    if needed, only inside the adjudicator pre-filter.
  - **H1 (code, HIGH)** — "rounding tolerance" unspecified; any tolerance risks dropping the
    planted 14.2M-vs-13.9M (2.1%) and 7-vs-8 (12.5%) conflicts. Drop it or name an exact tol with
    a proof test.
  - **H2 (code, HIGH)** — the set-valued predicate list (`pain_point`…) is invented, not grounded
    in real claim groups. Ground it in `distinct_claim_groups()`; default unknown predicate to
    **set_valued** (fail toward surfacing, not toward spurious).
  - **H1/H2/M4 (architect/code, HIGH/MED)** — no cluster-size bound; cross-predicate "all
    predicates" is undefined; **link clusters** (Maria #6 spans LINKS, not claims) aren't modeled
    and the output schema has no link-pair fields. Define cluster boundaries + `MAX_CLUSTER_CLAIMS`
    + a discriminated claim-pair/link-pair output.
  - **H3/M3 (HIGH/MED)** — `call_structured` has no cache, no temperature, defaults to Sonnet;
    `adjudicate.py` must own the cache, inject an Opus client, and the seam needs a `temperature`
    pass-through (additive, no Protocol change).
  - **M1 (both, MEDIUM — the headline)** — SPLIT. The deterministic Stage-2 (normalize fixes +
    predicate-cardinality pre-filter) is **independently shippable, $0, and high-value** (it
    collapses most of the 266 spurious with zero real lost, before any LLM spend). Bundling it
    with the paid LLM pass lets a normalize regression block the cheap win.
  - Sound as-is: placement (post-ingest sweep), the "never resolve" guarantee (schema has no
    winner field), cost discipline, no frozen-contract change, no new Repository method.

## Decision: SPLIT (pending operator confirm)

Per the convergent Stage-3 recommendation, restructure into:
- **SP_028a — Deterministic precision layer ($0, Standard).** `normalize.py` sign/currency-position
  fix (the safe one: `-SGD 2.1M ≡ -SGD 2.1M` parse) + `predicate_cardinality.py` grounded in real
  claim groups + the Stage-2 pre-filter in a clear-then-rewrite sweep. Drops the
  format/multi-valued/breakdown spurious classes; measured against the oracle. **No LLM, no
  date/rounding normalizer change.** Ships the 266→real-number win cheaply and safely.
- **SP_028b — LLM adjudication (Foundational, paid).** Stages 3–4 with the C1/C2/H1-3 fixes:
  single-writer clear-then-rewrite, content-hash cache, bounded heterogeneous (claim+link)
  clusters, Opus+temperature-0 seam, discriminated-pair output. Gated paid CLI.
- **SP_029 — Conservative entity-fragment merge** (already fenced here as highest-risk).

This file is superseded by that split once the operator confirms.
