# HelixPay — Extraction Metrics, Contradiction-Detection Delta vs. a Human Baseline, and Improvement Plan

**Scope:** The full-corpus (44-doc) extraction is recorded and live-queryable in
`helixpay_full`. This report answers the open mandate questions: (Req 3) how the
extraction validates against the ground-truth Q&A set, (Req 4) whether the ground truth
is representative of how an MCP agent explores the data, and (Req 5) the metrics plus
concrete, **non-hardcoding** improvements. It centers on the most important finding: a
direct comparison of the system's contradiction detection against a human's manual read
of the same corpus.

**Surfaced from:** the SP_024/SP_025 full record run (44 docs, 2,217 claims, 451 links),
a `$0` contradiction recompute after the SP_026 comparator fix, a paid two-level eval, and
a fact-by-fact audit of 8 human-found contradictions. Date: 2026-06-11.

**Companion to:** `extraction-silent-drop-recall-loss.md` (the SP_010 "empty-on-dense"
defect — the sales-pipeline dashboard documented here is its residual tail) and
`evaluation-and-ground-truth-best-practices.md`.

---

## TL;DR

1. **Extraction recall is healthy: 85% (35/41 golden bar-facts), precision 92%.** Above
   the 80% `/goal` bar. Unchanged by the SP_026 fix.
2. **Contradiction *detection* recall is the weak point: the system catches ~1 of 8
   contradictions a human finds by reading the corpus.** It detected the one designed,
   clean-keyed conflict (Project Confluence GA date) and missed the other seven.
3. The misses are **not** random — they cluster into four mechanical causes:
   **(A) predicate fragmentation, (B) entity fragmentation, (C) unmodeled contradiction
   classes, (D) one hard extraction bug** (`sales-pipeline-2026-04-21.html` → 0 claims).
4. The detector simultaneously **over-counts** (one Confluence conflict = 86 pairwise rows)
   and **under-detects** (misses cross-document narrative conflicts). 266 rows ≈ ~20–25
   distinct "stories," combinatorially inflated.
5. Root architectural cause: **contradiction detection is deterministic** — it compares
   only claims sharing an *exact* `(resolved subject, canonical predicate)` key. That buys
   grounding, determinism, `$0` re-runs, and testability, but cannot see the cross-entity /
   cross-predicate / semantic conflicts that dominate a human's read.
6. **Highest-leverage fix:** move contradiction *discovery* (not the whole pipeline) to a
   **grounded LLM cluster-pass** that must cite the two claim ids it pairs — keeping the
   project's "every contradiction names two real claims" guarantee while lifting recall.

---

## Part 1 — Extraction metrics (Req 3)

Two-level eval (`eval/run.py`) over the master oracle `test/golden/facts.yaml` (50 facts,
41 counting toward the recall bar), run against `helixpay_full`:

### Level 1 — golden recall over the raw data
- **recall = 85% (35/41)**, 95% Wilson CI **[72%, 93%]** (facts are clustered by source, so
  true SE is wider than i.i.d.).
- **golden-precision = 92%**; macro per-predicate recall = 79%.
- Per-predicate: revenue 7/7, ebitda 2/2, net_new_merchants 3/3, reports_to 4/4,
  top_contributor 3/3, role 2/2, owns 2/2, nps/runway/gross_margin/headcount/burn all 1/1.
- **The 6 misses** (all explainable, none from the SP_026 change):

  | verdict | fact | predicate | cause |
  |---|---|---|---|
  | MISMATCH | md-boardupdate-churn | churn | right value, wrong/absent source attribution |
  | MISMATCH | md-weekly-q2-target | revenue_target | as_of 2026-06-30 vs 2026-04-21 (target-date vs report-date) |
  | MISMATCH | interview-daniel-confluence-ga | ga_target | right value, wrong/absent source |
  | MISSING | slack-april-mtd-revenue | april_mtd_revenue | not extracted as a claim |
  | MISSING | code-tan-wei-ming-commits | q1_commits | per-person commit count not extracted under that subject |
  | MISSING | code-daniel-tan-commits | q1_commits | same |

### Level 2 — answer check (deep questions through `ask()`)
- **5/7 pass.** The 2 fails are both `no_false_contradiction`:
  - `q-revenue-agreement` and `q-latest-revenue-freshness` surface two *false* revenue
    contradictions that are not value disagreements at all:
    - **HelixPay Brasil:** `SGD 4.8M` vs `R$22.0M` — same revenue, different **currency**
      (no FX rate to equate 4.8M SGD ≈ 22M BRL).
    - **HelixPay SEA:** `SGD 9.4M` vs `9.4 (against plan of 10)` — same value, but the second
      **lost its "M" magnitude** at extraction (9.4 vs 9,400,000).
  - Neither is fixable without **introducing data** (an FX rate; or asserting a bare number
    is millions), which the project philosophy explicitly forbids ("an honest fidelity
    signal, never re-rig"). Documented as known limitations, not normalizer bugs.
- `/goal` verdict: **RED**, solely because of those 2 answer checks. Recall and contradiction
  presence both pass.

---

## Part 2 — Contradiction detection vs. a human baseline (the headline)

A human read the corpus and recorded **8 contradictions** across severity tiers. Auditing
each against the detected set:

| # | Sev | Human-found contradiction | Detected? | Mechanism of the miss |
|---|-----|---|---|---|
| 1 | 🔴 | Project Confluence GA: public "June" vs internal "Sept 30" | ✅ **yes** (86 pairwise rows) | clean: same subject + canonical predicate `ga_target` |
| 2 | 🔴 | HX-LOY-487 impact: "harmless" vs "R$2,140 delta" | ❌ no | entity + predicate fragmentation |
| 3 | 🔴 | HX-LOY-487 fix ETA: "end of Q2" vs "late Aug/Sep" | ❌ no | entity + predicate fragmentation |
| 4 | 🟠 | Açaí Express: live merchant vs net-new prospect | ❌ no | extraction gap + unmodeled class |
| 5 | 🟠 | Northwind close date: May 12 (dashboard) vs May 26 (chat) | ❌ no | extraction gap + predicate fragmentation |
| 6 | 🟠 | Maria Santos: `reports_to` AND `dotted_line_to` both → Marco | ❌ no | unmodeled class (cross-link-type) |
| 7 | 🟡 | Sara Wijaya's team: 7 vs 8 engineers | ❌ no | predicate fragmentation |
| 8 | 🟡 | Cosmos Hotels: 47 across "2" vs "3" countries | ❌ no | one side never extracted |

**Score: 1/8 (12.5%) of human-found contradictions detected.** Every missed conflict's data
is present in the ontology (except half of #8) — the detector cannot cross the gaps.

### Evidence per miss (verified against the DB)
- **#2/#3 HX-LOY-487:** the bug fragments into **~12 entity rows** (`tap-loyalty bug`,
  `reconciliation bug`, `Tap reconciliation bug`, `HX-LOY-487`, …). "Harmless" sits on
  `Ahmad Rashid / schema_migration_impact_level = medium`; "R$2,140" on
  `Açaí Express SP / reconciliation_delta_net`. No shared `(subject, predicate)` → never
  compared.
- **#5 Northwind:** `Northwind / original_close_date = May 12` and `expected_close_date =
  May 26` are **two predicates** (both from the chat), and the dashboard's `2026-05-12`
  side was **never extracted** (see #4/§Part 3). No pair forms.
- **#7 Sara:** `Sara Wijaya / team_size = 7` (org-chart) vs `headcount_managed = ~8`
  (interview) — **same subject**, different free-text predicate.
- **#8 Cosmos:** `country_count = 3` exists; the "2 countries" side is implicit prose
  ("Malaysia and Thailand") and was never extracted as a comparable claim.
- **#6 Maria Santos:** both `reports_to` and `dotted_line_to` edges to Marco Bianchi exist;
  the detector only sweeps `reports_to` vs `reports_to` (single-valued). Cross-link-type
  incoherence is not a detection rule. (She correctly resolved distinct from Maria Silva —
  the two-Marias trap held.)
- **#4 Açaí:** resolved to a **single** `customer` entity (SP_020 dedup worked); the
  proposal-stage "prospect" side was never extracted (pipeline dashboard, §Part 3), and a
  classification conflict isn't modeled as a contradiction anyway.

### The precision side
266 detected rows are **pairwise-inflated**: Confluence GA alone = 86 rows; org-chart
`reports_to`, financial line-items, and EBITDA-across-sources multiply similarly. Distinct
"contradiction stories" number ~20–25. So the system over-counts mechanical same-key diffs
while under-detecting the cross-document narrative conflicts a human flags as material.

---

## Part 3 — The extraction bug: `sales-pipeline-2026-04-21.html` → 0 claims

- The doc has **1 chunk, 2,270 chars** of clean text — including the full deal table
  (`Northwind Logistics | Negotiation | Marcus Lee | 620K | 2026-05-12 | on track`, Açaí
  proposal stage, etc.). **The loader is fine.**
- The replay cache entry is **28 bytes: `{"claims":[],"relations":[]}`** — the LLM
  extraction returned **empty**.
- This is the **residual tail of the SP_010 "empty-on-dense" defect**
  (`extraction-silent-drop-recall-loss.md`): the other two dashboards (38/52 claims) and the
  org chart (119) were fixed, but the *pipeline/forecast* dashboard still emits nothing —
  the prompt appears to treat a forward-looking pipeline table as out-of-scope.
- It went unnoticed because the pipeline dashboard is **not in the 9-doc smoke set**, so its
  empty extraction was never gated (the SP_024 `empty_extractions` ledger gate only runs
  over smoke docs).
- **Fix cost:** prompt adjustment (`$0` code) + **single-document re-record** (~cents, one
  Sonnet call). **No full run.** The other 43 docs' cache is untouched.
- Recovering this one doc directly restores the missing side of **#4 and #5**.

---

## Part 4 — Why detection is deterministic, and the LLM alternative

**Today:** extraction is LLM (Sonnet, per-doc, schema-validated). Contradiction *detection*
is deterministic (`helixpay/ingest/contradict.py`): per `(subject, canonical predicate)`
group, `normalize.values_conflict()` + a validity-window gate + a 3-class `classify()`,
writing a row that names **two specific claim ids**. The LLM (Opus) only writes the answer
narrative; it does not decide what a contradiction *is*.

**Why deterministic was the right default:**
1. **Grounding / no hallucination** — every row points at two real claims; satisfies the
   "contradictions are first-class rows with both claim ids" + "zero uncited claims"
   contract. An LLM can assert disagreement without anchoring it.
2. **Determinism + idempotency + `$0` re-runs** — we recomputed all 266 over existing claims
   for `$0`, reproducibly. An LLM pass is non-deterministic and paid every run.
3. **Cost/scale** — O(claims²) within groups (2,217 claims); LLM-judging every pair is
   expensive.
4. **Auditability/testability** — the rules are unit-tested and gateable; an LLM judge is not.

**The cost of that default** is exactly the 1/8 recall above: the comparator only fires on
an exact same-key match, so it misses the cross-entity / cross-predicate / semantic conflicts
that are the *interesting* ones (public-vs-internal, promise-vs-truth, stale-CRM).

**Recommended architecture — grounded LLM cluster-pass (hybrid):**
- Keep the deterministic detector for cheap exact same-key cases.
- Add a one-time (snapshot-baked, not per-query) LLM pass over **candidate claim clusters**
  (grouped by subject / topic / document co-occurrence) where the LLM **must return the two
  claim ids it believes contradict + a reason**, then **validate the ids exist**
  (validate-and-repair-or-drop — the same discipline already used for extraction).
- This keeps every LLM-found contradiction **grounded and auditable**, lets it span entities
  and predicates the comparator can't, and bounds cost (judge clusters, not all pairs).

---

## Part 5 — Prioritized, non-hardcoding remediations

| Pri | Fix | Recovers | Cost / risk |
|----|---|---|---|
| 1 | **Pipeline-dashboard extraction** (prompt) + single-doc re-record | #4, #5 (missing side) | ~cents, low risk; concrete bug |
| 2 | **Predicate synonym layer** — extend `metric_vocab` canonicalization to free-text predicates (`team_size`≈`headcount_managed`, `*_close_date`→`close_date`) | #3, #5, #7 | `$0` code; risk: over-merging — needs TDD + review |
| 3 | **Entity canonicalization on strong IDs** — collapse the ~12 bug entities via the `HX-LOY-487` ticket id | #2, #3 | `$0`–cents; medium |
| 4 | **Grounded LLM cluster-pass** for contradiction discovery (Part 4) | #2, #3, #6, #8 + future | paid one-time; highest leverage, biggest design change |
| 5 | **New deterministic classes** — cross-link-type coherence (`reports_to` vs `dotted_line_to` same target); account-classification conflict | #6, #4 | `$0`; targeted |
| 6 | **Extract implicit comparables** — e.g. country count from "Malaysia and Thailand" | #8 | prompt; needs re-record |

**Hard constraint observed throughout:** none of these introduce data not in the corpus. The
Brasil-currency and SEA-magnitude false contradictions (Part 1, Level 2) are deliberately
*not* "fixed," because doing so would require fabricating an FX rate or a magnitude.

---

## Part 6 — Work already completed this session

- **Excised 2 fixture-stub documents** that had leaked into `helixpay_full` (`fixture:`-hashed
  board-deck + april-dashboard rows; 2 metric-as-subject revenue claims; 1 ghost
  `value_conflict` on a synthetic `13.9M` that exists nowhere in the corpus). DB is now an
  exact 44-doc match to the repo.
- **SP_026 comparator fix** (`normalize.py`): annotation parentheticals (`(per app)`,
  `(BRL 22M)`, `(against plan of 10)`) are dropped in the **numeric** path only; digit-only
  parens (accounting negatives like `(840.00)`) are preserved. Retracted **6** false-positive
  contradictions (e.g. `192,660 (per app)` vs `192,660 (per bank statement)`), **0** real
  ones lost, **0** spurious added; recall held at 85%.
- **`$0` contradiction recompute** tooling (`scripts/recompute_contradictions.py` +
  `PostgresRepository.{clear_contradictions, distinct_claim_groups, distinct_link_groups}`),
  since `detect()` is additive and never retracts a stale pair.
- **Durable backup** of the extraction: `.replay-cache/` (98 canonical JSON, committed) +
  a clean `pg_dump` snapshot (committed). Not yet deployed to production.
