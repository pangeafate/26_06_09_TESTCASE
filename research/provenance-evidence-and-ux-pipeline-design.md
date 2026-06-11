# Provenance, Evidence & Answer-UX: Pipeline Design Report

> **Date:** 2026-06-10
> **Author:** Claude (codebase analysis + live-DB stress test)
> **Scope:** What metadata the ingest pipeline actually captures *after extraction*,
> stress-tested against the live database (1,604 claims / 256 links / 17
> contradictions from the first full run), evaluated from the **end-user / calling-agent
> experience**. Each gap is turned into a **forward pipeline-design change** — the
> system should *produce* this provenance natively, not have it backfilled into the DB
> by hand.

---

## TL;DR

Provenance **is** captured for value-claims, end to end: every `Claim` carries
`source_chunk_id` + `document_id`, so claim → chunk → document → `source_uri` /
`source_type` / `as_of` is fully reconstructable, and the recall harness verifies
`source_uri` + `as_of` on every found fact. That backbone is solid.

The gaps are all in the **user-facing provenance layer** — what a person or agent
actually gets back when they ask "where did this come from?" Five gaps, all observed
in live data, ranked by UX impact:

1. **The evidence span is extracted and then thrown away.** Citations show the first
   200 chars of the ~650-token chunk — which, demonstrably, usually does *not* contain
   the fact (it's the document's header/boilerplate). **Highest-value fix.**
2. **No character offset / span anchor** — provenance is chunk-level, so no
   highlight-to-verify or deep-link.
3. **Relationships have a thinner provenance path than claims, and seeded edges have
   none** — 47/77 `reports_to` and 49/77 `member_of` links carry zero source, and
   synthesis cites claims only.
4. **Graph contradictions are invisible** — contradiction detection runs over claims,
   not links; a wrong reporting edge already coexists silently with the correct one.
5. **N copies of one fact, no consensus view** — runway is 7 coexisting claims; the
   confidence signal to rank them is captured but never surfaced.

The design principle for all five: **make provenance a first-class output of the
pipeline, carried on the contract types and persisted on write — not a join you hope
to reconstruct later, and never a manual DB patch.** The frozen contracts
(`helixpay/contracts/`) are the right place to amend; these are proposed contract
changes, migrated forward, not local forks.

---

## How the stress test was run

Against the live, already-populated database (no LLM calls, $0):

- traced the full `claim → chunk → document` chain for the company metrics;
- reproduced exactly what `Repository.get_sources()` returns to the answer layer
  (`Citation` with `snippet = chunk.text[:200]`);
- measured whether the user-facing snippet actually contains the claimed value;
- measured link provenance coverage by `link_type`;
- confirmed the `claims` table has no `evidence` / offset column.

The findings below quote that live data.

---

## What IS captured (the backbone — keep it)

Per-claim, all persisted and queryable today:

```
Claim ── source_chunk_id ─▶ Chunk ── document_id ─▶ Document
  ├─ predicate (canonicalized)      ordinal, text          source_uri, source_type
  ├─ object_value                                          title, author, lang
  ├─ as_of            (fact's effective date)              as_of (document date)
  ├─ confidence       (0.0–1.0, per claim)                 content_hash, raw_text
  ├─ valid_from / valid_to / superseded_by  (temporal)
  └─ document_id      (denormalized for a direct join)
```

Live example — "HelixPay revenue" is not one cell but a provenance-carrying set:

| value | as_of | confidence | source_uri | source_type |
|---|---|---|---|---|
| SGD 14.2 million | 2026-03-31 | 0.99 | all-hands-2026-04-15.md | md |
| SGD 14.2M | 2026-03-31 | 0.99 | board-update-2026-04-22.md | md |
| SGD 14.2M | 2026-04-09 | 0.50 | interviews/leadership/Sofia_Almeida.md | md |
| SGD 14.2M | 2026-04-12 | 0.50 | interviews/finance/Aisha_Mahmud.md | md |

The recall harness asserts `source_uri` + `as_of` for every graded fact, so document
linkage is **proven** for found facts. This is the part to preserve while closing the
gaps below.

---

## Gap 1 — The evidence span is dropped (highest value)

**Observed.** The extractor already emits a verbatim grounding quote: `ClaimOut.evidence`
(`helixpay/ingest/extract/schemas.py`), deliberately ordered *before* `object_value` so
the model commits to a source span before asserting the value. But there is **no
`evidence` column on `claims`**, and `pipeline._ingest_document` never passes it to
`add_claim`. The span is used for the grounding check and then discarded.

What the user gets instead is `Citation.snippet = chunk.text[:200]`
(`repository.py:487–506`). Tested against live revenue claims:

| claim | source | value in first-200 snippet? | value anywhere in chunk? |
|---|---|---|---|
| revenue 14.2M | all-hands.md | ❌ (Zoom/Otter transcript header) | ✅ |
| revenue 14.2M | board-update.md | ❌ (email From/To/Cc header) | ✅ |
| revenue 14.2M | Aisha interview | ❌ (`## Meta` block) | ❌ (surface form differs) |

So the citation a user sees to "verify" the claim is, in practice, the document's
opening boilerplate — it does not show the fact. The model already isolated the exact
sentence; the pipeline throws it away.

**Pipeline-design change (forward, not backfill):**

1. **Contract** — add `evidence: Optional[str]` to `contracts.models.Claim` (and a
   matching `char_start`/`char_end` — see Gap 2).
2. **Schema** — `ALTER TABLE claims ADD COLUMN evidence TEXT` (+ offset columns). New
   migration statement; idempotent `IF NOT EXISTS` pattern like the rest of
   `schema.sql`. Forward-only: existing rows get `NULL`, new extractions populate it.
3. **Persistence** — `pipeline._ingest_document` already has `claim_out.evidence` in
   hand; pass it into the `Claim(...)` it builds, and `repository.add_claim` writes it.
   ~3 lines, no new LLM cost.
4. **Citation** — `get_sources` returns `snippet = claim.evidence` when present, falling
   back to the chunk prefix only when it's null. The `Citation.snippet` field already
   exists — this just feeds it the right text.

**Why it's a pipeline change, not a DB patch:** the value is produced on every
extraction and must be carried on the contract so *all four surfaces* (REST, MCP, CLI,
eval) get it for free. Backfilling the DB would fix today's rows and silently lose the
span again on the next ingest.

> Note: this is the persisted twin of the **evidence-span grounding gate** already
> recommended in `extraction-design-and-best-practices.md`. That report proposes
> *verifying* the span at extraction; this one proposes *keeping* it for the answer
> layer. Do them together — the span you verify is the span you cite.

---

## Gap 2 — No character offset / span anchor

**Observed.** Provenance granularity stops at the chunk (~650 tokens). There is no
offset into `document.raw_text`, so no "highlight the exact words" or deep-link.

**Pipeline-design change.** Carry `char_start` / `char_end` (offsets into the chunk, or
into `raw_text`) on `Claim` and `Link`. The grounding step already locates the evidence
substring (`grounding.py:_value_in_span`); capture its offset there and thread it
through persistence. With offsets, the answer layer can render an exact highlight and a
stable anchor — table-stakes for a "click to verify" UX. Forward-only column; no LLM
cost beyond what grounding already computes.

---

## Gap 3 — Relationship provenance is second-class

**Observed (live coverage by link type):**

```
link_type        total  with_source  NO provenance
reports_to          77        30           47   ← seeded roster edges
member_of           77        28           49   ← seeded roster edges
owns                33        33            0
mentions            63        63            0
dotted_line_to       6         3            3
```

Two structural issues:

- **`Link` carries only `source_chunk_id`, not `document_id`** (unlike `Claim`, which
  carries both). And `Repository.get_sources` is **claims-only** — `synthesis.py:15`
  states "only claims have a Protocol path to provenance." So an answer built from a
  *relationship* ("who does Daniel report to?") has no first-class citation path; the
  two golden `owns` email facts cite cleanly only because we route them through claims.
- **Seeded org edges have no source at all.** The golden `reports_to` facts
  (Daniel→Arjun, Sara→Daniel) come from the seed roster, so `source_chunk_id` is NULL —
  the user gets the right answer with **zero citation**, on exactly the org-hierarchy
  questions the eval grades.

**Pipeline-design change:**

1. **Contract/schema** — add `document_id` to `Link` (mirror `Claim`); add a
   `get_link_sources(link_ids) -> list[Citation]` method to the `Repository` Protocol
   and `QueryEngine` so relationship answers cite through the same path as values.
2. **Synthesis** — when an answer rests on links, attach link citations, not just claim
   citations. Removes the claims-only provenance asymmetry.
3. **Ingest the org chart, don't only seed it.** `data/org-chart.md` is a real source
   document — extract its reporting lines as links *with* `source_chunk_id`, so they
   carry provenance. Keep the seed roster as the resolution backbone, but let extraction
   supply (or corroborate) the *edges* so every shown edge has a citation. This also
   resolves Gap 4's silent conflict.

All post-LLM plumbing except the org-chart re-extract (one document, cheap).

---

## Gap 4 — Graph contradictions are invisible

**Observed.** Contradiction detection (`ingest/contradict.py`) runs over **claims**
only. Links get none. The live graph already contains a silent conflict:
`Daniel Tan → Wei Chen` (extracted from all-hands, chunk 3) coexists with
`Daniel Tan → Arjun Kapoor` (seeded). Org truth is Daniel→Arjun→Wei, so one edge is
wrong — and nothing surfaces it. A system whose headline promise is "contradictions
surfaced, never hidden" is keeping that promise for *values* but not *relationships*.

**Pipeline-design change.** Extend the contradiction sweep to links: after the claim
sweep, run a per-`(from_entity, link_type)` pass that flags incompatible edges
(e.g. two distinct solid-line managers `reports_to` at overlapping validity) as
`Contradiction` rows (`kind = source_disagreement` / a new `relation_conflict`). The
`contradictions` table already references `claim_a_id`/`claim_b_id`; generalize to
reference links, or add `link_a_id`/`link_b_id`. Then `AnswerBundle.contradictions`
surfaces relationship conflicts the same way it surfaces value conflicts. Post-LLM, $0
to iterate via the replay tier.

---

## Gap 5 — N copies of a fact, no consensus view

**Observed.** Runway = 7 coexisting claims: `18 months` / `eighteen months` /
`~18 months` / `18 months` across 7 sources, confidences 0.50–1.0. This is the data
model working as intended (claims coexist), but a naive answer dumps all seven. The
ranking signal is captured (`confidence`, `as_of`, source count) — it's just never
presented.

**Pipeline-design change (query layer, no schema change).** Add a **consensus/dissent
rollup** to synthesis: group claims by canonical predicate + normalized value, present
the consensus value with its corroborating-source count and freshest `as_of`, and list
genuine dissent separately (which is where real contradictions live). This depends on a
robust `normalize_value` (`eighteen months` ≡ `18 months`) — the same fix the recall
work needs — so the two efforts share a dependency. Pure query-layer; $0.

---

## Build order (folds into the existing iteration plan)

These slot into the three-tier loop from
`RECALL_AND_ITERATION_REPORT.md` — most are post-LLM and testable on the **$0 replay
tier**; only span backfill and the org-chart re-extract need a Tier-1 run.

| # | Change | Layers touched | Cost to test | UX payoff |
|---|--------|----------------|--------------|-----------|
| 1 | Persist + cite `evidence` span | contract, schema, pipeline, repository | Tier 1 (re-extract to populate) | Citations quote the fact, not boilerplate |
| 2 | `char_start/end` offsets | contract, schema, grounding, pipeline | Tier 1 | Highlight-to-verify, deep-link |
| 3 | Link provenance + `get_link_sources` + ingest org chart | contract, schema, repository, synthesis, pipeline | $0 replay (+1 doc re-extract) | Relationship answers cite their source |
| 4 | Contradiction sweep over links | contract (contradiction refs), contradict, pipeline | $0 replay | Graph conflicts surfaced, not hidden |
| 5 | Consensus/dissent rollup | query/synthesis (+ `normalize_value`) | $0 query-only | One clean answer instead of 7 raw claims |

**Sequencing:** 1 and 2 ship together (same write path, same migration). 4 and 5 share
the `normalize_value` dependency with the recall work — land that once and three things
improve. 3's org-chart re-extract piggybacks on the next Tier-1 subset run.

**Governance note (contracts are frozen):** items 1–4 amend `helixpay/contracts/`
(`Claim`, `Link`, `Contradiction`, the `Repository`/`QueryEngine` Protocols). Per
CLAUDE.md these are *proposed contract changes*, migrated forward across all slices in
one Foundational-tier sprint — not per-module forks. The schema changes are additive
(`ADD COLUMN ... `, new nullable fields), so they're backward-compatible and existing
rows degrade gracefully to today's behavior until re-ingested.
