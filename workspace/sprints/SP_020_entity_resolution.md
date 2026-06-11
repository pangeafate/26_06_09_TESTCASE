---
sprint_id: SP_020
tier: Standard
features: [mint-time-dedup, remove-acai-hardcode]
user_stories: []
schema_touched: false
structure_touched: false
status: Complete
isolation: branch-only
branch: sprint/SP_019-extraction-attribution
worktree: ""
agent_owner: "Claude (Opus 4.8)"
fix_type: "operator-observable: a named account split across two subject_types becomes unresolvable; fix the class, not the account"
dependencies: [SP_010, SP_019]
dev_dependencies: []
touches_paths:
  - helixpay/ingest/resolve.py
  - helixpay/seed/roster.py
  - test/unit/ingest/test_resolve.py
  - test/unit/seed/test_roster.py
touches_checklist_items: [er-mint-dedup, er-remove-acai]
---

# SP_020: Mint-time dedup (kill the dual-type duplicate at the source) + remove the Açaí hardcode

## Sprint Goal

Replace the hardcoded `Açaí Express SP` seed (SP_010 final-mile) with a **general**
fix to the *class* of bug, chosen after Stage-3 review (both reviewers recommended this
layer over a heavier post-ingest merge — see the review record below).

The bug class: an open-class entity (customer/account/product) mentioned with
**inconsistent `subject_type`** mints **two rows** with the same `canonical_name` (unique key
`(canonical_name, entity_type)`). Its bare name then resolves ambiguously → `None` → claims
split and, critically, an `owns`-style **link is dropped at ingest** because the endpoint
won't resolve (the graded `email-acai-owner` link is `Maria Santos --owns--> Açaí Express SP`;
`Maria Santos` resolves on the full surname, `Açaí Express SP` is the `None` side).

**Fix — at mint time, in `resolve.resolve_mention`:** before minting a new open-class entity,
extend the existing SP_019 seeded-snap to ALSO snap to an existing **unseeded** same-name row
when **one side is the catch-all `other`** (the extractor's "type unknown" bucket). The second
mention then reuses the first row instead of minting a duplicate; the bare name stays
unambiguous; the link resolves and persists **at ingest** — no post-ingest pass, no schema
change, no merge SQL. Then **remove** `_ACCOUNTS`/Açaí from `roster.py` and confirm the general
mechanism recovers the fact with no hardcode.

## Why mint-time, not a post-ingest ER merge (Stage-3 decision)

Both Stage-3 reviewers (Foundational floor = 2) returned **GO-WITH-CHANGES** and independently
recommended this layer:
- The post-ingest merge cannot resurrect a link that was **already dropped at ingest** without
  a "pending-relation retry" smell, and its `merge_entities` SQL carried **3 CRITICAL + 5 HIGH**
  traps (superseded_by self-FK, link natural-key collision ordering, contradiction link-pairs,
  natural-key direction) plus an **ontology-invariant risk** (hard-deleting a colliding claim
  that differs on as_of/confidence *is* the "never collapse facts" violation).
- Mint-time dedup prevents the duplicate from ever existing, so the link never drops — none of
  the above applies. Operator chose this approach.

Out of scope (documented follow-up): cleaning **pre-existing** cross-run duplicates already in a
long-lived DB (that is the only case a post-ingest merge would add value); fuzzy/pgvector name
matching. The proving loop re-ingests fresh, so mint-time fully covers it.

## Current State

- `resolve.resolve_mention` (`resolve.py:108-125`): on a typed-resolve miss for a creatable
  type, the SP_019 seeded-snap does a type-agnostic resolve and snaps **only if the hit is
  seeded**; otherwise it mints `seeded=False`. So two unseeded same-name rows of different types
  coexist → bare-name ambiguity → `None` → link dropped (`pipeline.py:247-249`).
- `roster._ACCOUNTS` hardcodes `Açaí Express SP` (being removed).

## Desired End State

- A same-name dual-type open-class mention snaps to the one existing row at mint time; no
  duplicate; the `owns` link resolves and persists — **without** seeding the account.
- Two seeded same-name entities (Maria Santos/Silva, Daniel Tan/Tan Wei Ming) are **never**
  bridged (they are `person`, non-creatable, and never reach the snap).
- Two genuinely-distinct **specific** types sharing a name are **not** merged (the snap fires
  only when one side is `other`, and `resolve_entity` returns `None` on a 2+-row ambiguity so the
  snap never bridges an existing dup).

## Scope

In: the `resolve.py` snap extension (`_other_compatible` guard); removing `_ACCOUNTS` from
`roster.py`; their unit tests. Out: any schema/Repository/pipeline change; post-ingest merge;
fuzzy matching; pre-existing-duplicate cleanup.

## Technical Approach

- In `resolve_mention`, the creatable-type branch: replace the seeded-only snap with — for each
  name variant, do a type-agnostic `repo.resolve_entity(variant, None, context)`; snap to the
  hit when `ent.seeded` **OR** `_other_compatible(entity_type, ent.entity_type)`, where
  `_other_compatible(a, b) = "other" in (a, b)`. `resolve_entity` already returns exactly one
  row only when unambiguous (seeded-first + context), and `None` on a 2+-row tie — so the snap
  can never fire across an existing duplicate or bridge two seeded entities. Then mint as today.
- Remove `_ACCOUNTS` (and its loop) from `roster.parse_overview`; keep the `CUSTOMER` constant
  (harmless, may be reused). The seed test for Açaí is deleted.

## Testing Strategy

- `test/unit/ingest/test_resolve.py` —
  - dual-type mint dedup: mint `customer|Açaí` then resolve `other|Açaí` snaps to the same id
    (and the reverse order), zero duplicates;
  - **does NOT bridge two specific types**: `customer|X` then `product|X` (no `other`) mints two
    rows (conservative);
  - existing guards still hold: two Marias → `None` (persons non-creatable, never snap); a
    genuinely-new open-class mention with no same-name row still mints; the seeded-snap
    (`metric|HelixPay` → seeded `other|HelixPay`) still works.
- `test/unit/seed/test_roster.py` — the Açaí seed assertion is removed; `parse_overview` no
  longer emits the customer.
- Replay-tier acceptance ($0) + paid re-record (operator-approved): `email-acai-owner` FOUND with
  no hardcode; two Marias still distinct; recall not regressed.

## Risks & Mitigations

- *Over-merge bridging two real entities* → snap only when one side is `other`; `resolve_entity`
  returns `None` on ambiguity so the snap never fires across an existing dup; two seeded entities
  (persons) never reach the snap. Regression tests gate all three.
- *Surviving row keeps the first-minted (possibly less-specific) type* → acceptable; resolution
  is by name, the grader does not key on type. Type "upgrade" on snap is a documented non-goal
  (would touch the `(name, type)` unique key).
- *Removing the Açaí seed on a long-lived DB* → a previously-seeded `customer|Açaí` row persists
  (seed never deletes); on the fresh replay/smoke DB there is no such row, so the mint-time snap
  governs. Noted for any persistent DB.

## Success Criteria

- Mint-time snap dedups a same-name dual-type open-class mention; **Açaí seed removed**.
- Replay-tier ($0): `email-acai-owner` FOUND with no hardcode; recall not regressed; two Marias
  distinct.
- Paid re-record (operator-approved): confirms end-to-end.
- `uv run pytest test` green; `uv run mypy helixpay` clean; all validators pass.

### Pre-Implementation Review

- **Iteration 1** — architect-reviewer, plan-blind on the original (post-ingest) design; **GO-WITH-CHANGES**, recommended this mint-time layer (HIGH-1). Files reviewed: schema.sql, repository.py, pipeline.py, resolve.py, roster.py, assemble.py, contradict.py, eval/smoke/facts.yaml.
  - CRITICAL-1 (falsified by cache): the graded link is `from:"Maria Santos"` (resolves) `to:"Açaí Express SP"` (the `None` side) — the customer side is the fixable half. **Resolved.**
  - CRITICAL-2/3 (applied only to the rejected merge path): superseded_by self-FK + never-delete invariant. **Avoided** by the mint-time approach (no merge, no delete).
  - **HIGH-1 → adopted:** dedup at mint time; removes the post-ingest pass, merge_entities, pending-retry, and the schema change.
- **Iteration 2** — code-reviewer, plan-blind adversarial on the original design; **GO-WITH-CHANGES**, 3 CRITICAL + 5 HIGH all inside the merge SQL; **independently corroborated** that the simpler in-layer fix avoids all of them. Files reviewed: schema.sql, repository.py, pipeline.py, resolve.py, assemble.py, test_pipeline.py.

> The chosen mint-time design is the reviewers' own recommendation, so it carries their Stage-3
> endorsement; the rejected post-ingest merge is recorded above for the audit trail.

### Post-Implementation Review

- **Iteration 1** — code-reviewer, plan-blind; **APPROVE**, 0 CRITICAL + 0 HIGH + 2 MEDIUM + 2 LOW (all cleanup, applied). Files reviewed: resolve.py, roster.py, test_resolve.py, test_roster.py. 635 tests pass, mypy clean.
  - Verified the two-Marias guard holds three ways: persons/teams non-creatable (never reach the snap); the type-agnostic snap resolve returns `None` on any 2-row tie (never silently picks); seeded-first disambiguation returns the seeded row when seeded+unseeded coexist. `_other_compatible` is a narrow relaxation only for the `other` catch-all.
  - MEDIUM-1: `CUSTOMER` constant became dead code after removing `_ACCOUNTS`. **Applied:** removed it + its `__all__` entry.
  - MEDIUM-2: the SP_010 CLAUDE.md gotcha was stale (prescribed `_ACCOUNTS`). **Applied:** rewritten to describe the SP_020 mint-time dedup (done pre-review).
  - LOW: stale "snap only fires on a seeded hit" comment updated; added the 3-way pre-existing-ambiguity coverage test (`test_mint_time_dedup_does_not_snap_across_a_preexisting_ambiguous_pair`).
- **Iteration 2** — runtime verification (DB-gated **$0 replay — DONE 2026-06-11**): 0 CRITICAL. Removed the seeded Açaí row, re-seeded (66 entities, 0 `Express SP`), replayed the 9 cached docs through the **live** `resolve.py` (`PYTHONPATH=/app` — see the harness gotcha) and graded with `check_extraction`. **Result: `email-acai-owner` FOUND with NO hardcode (one Açaí row, id 582 customer, not two); recall 11/11 (100%), precision 100%, mismatch=0; two Marias still distinct (id 35 Santos / id 28 Silva).** Behavioral closure (Rule 21): the operator-observable "unresolvable split account" symptom is fixed for the class. Recorded in `workspace/acceptance/SP020_mint_dedup_run.md`. Files reviewed: replay run + grader output + entity-row query.

> Paid re-record: NOT run. SP_020 changed only resolution (`resolve.py`), not extraction (no
> prompt change), so the $0 replay against the real cached extractions is the authoritative test.
> A paid re-record would re-run unchanged extraction at cost and only add LLM variance.
