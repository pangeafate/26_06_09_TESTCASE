# Report — Reaching 85% recall without the $6 / 1-hour loop

Three questions, answered in order:

1. Can we iterate on a **~10% representative subset** instead of the full corpus?
2. What does **SGR (Schema-Guided Reasoning)** and the wider literature actually
   offer for raising extraction recall 27% → 85%?
3. The concrete plan.

**TL;DR.** These are two separable problems with two separate solutions:

- **The slow loop is the real enemy, and it's beatable without a smaller corpus.**
  The honest "representative subset" lands at **~30% of files, not 10%** (because
  the 15 graded facts already span 11 of the 44 files — you can't drop below that
  without dropping a graded fact). But the *real* 10×+ cost cut is a **$0 replay
  tier**: all three diagnosed recall fixes run *after* the LLM call, so we cache
  the one expensive extraction and re-run resolve→canonicalize→contradict→eval for
  free, in seconds.
- **The 85% number is clearable on this eval with post-LLM fixes** (the three
  already diagnosed), which the replay tier tests for $0. SGR / gleaning / schema
  work is for *generalization and robustness* — validate it on the ~30% subset
  (~$2) before paying for a full run.

---

## Part 1 — The "10% subset" idea

### Why a *random* 10% fails

The eval recall denominator is **15 specific golden facts** (`test/golden/facts.yaml`),
each pinned to an exact `source_uri`. Recall is not a statistical estimate over the
corpus — it is a checklist against named files. A random 4–5 file sample would:

- almost certainly **drop graded facts** (recall measured against a denominator
  the sample can't satisfy → meaningless number);
- **break the planted contradictions**, which need *both sides present* (the
  Confluence GA conflict lives across `all-hands` + `board-deck` + 3 corroborators);
- **lose the name-trap distractors** (two Marias, two Tans) that stress entity
  resolution — the very thing we're trying to fix.

### What "representative" actually means here — the golden-anchored subset

Because the grader reads from fixed files, the only faithful subset is **the union
of every file the golden set touches**. Mapping the 15 `recall_bar:true` facts +
the two planted contradictions to their sources:

| # | File | Format | Graded facts / role |
|---|------|--------|--------------------|
| 1 | `data/overview.md` | md | runway 18 months |
| 2 | `data/all-hands-2026-04-15.md` | md | Confluence GA = June **(contradiction side A)**; NPS-62 framing |
| 3 | `data/q1-2026-results.pdf` | pdf | revenue 14.2M; net-new-merchants 412 |
| 4 | `data/board-deck-q1-2026.pdf` | pdf | Confluence GA = Q3 **(contradiction side B)** |
| 5 | `data/dashboards/april-2026-kpi-dashboard.html` | html | revenue 14.2M; NPS 47 |
| 6 | `data/chat/sales-floor-april.md` | slack | CRM cutover = end June |
| 7 | `data/email/cosmos-hotels-debrief.md` | email | Marcus Lee owns Cosmos |
| 8 | `data/email/customer-acai-express-thread.md` | email | Maria Santos owns Açaí |
| 9 | `data/code/contributors-analysis-q1-2026.md` | code | Sara Wijaya top contributor (+ Tan Wei Ming trap) |
| 10 | `data/interviews/sales/maria-silva.md` | interview | Brasil revenue 4.8M (+ Maria trap) |
| 11 | `data/org-chart.md` | md | Daniel→Arjun; Sara→Daniel; headcount 274 |
| 12 | `data/weekly-review-2026-04-21.md` | md | Confluence-Q3 corroborator; NPS-framing corroborator |
| 13 | `data/board-update-2026-04-22.md` | md | Confluence-Q3 corroborator; NPS-framing corroborator |
| 14 | `data/interviews/leadership/Daniel_Tan.md` | interview | Confluence "~Sep 30" corroborator (+ Daniel Tan trap) |
| (15) | `data/interviews/customer_success/Maria_Santos.md` | interview | *optional* — the other Maria, to stress resolution |

**14 files (15 with both Marias) ≈ 30–34% of the 44.** This is not an approximation
of full-corpus recall — for the graded facts it is **identical**, minus the noise
from the 30 omitted files. In one sense it's *more* faithful for tuning the three
root causes, because every one of them (company-entity resolution, predicate
canonicalization, value normalization) is exercised inside these 14 files.

**Why you can't hit 10%:** the graded facts span 11 files = 25% of the corpus
before you even add contradiction corroborators. 10%-by-file is only reachable by
deleting graded coverage, which defeats the purpose. **~30% is the floor; treat
that as the answer to "small representative set."**

- **Cost of the subset run:** the omitted 30 files are mostly the claim-dense
  interview transcripts, so by extraction cost the subset is roughly one third:
  **≈ $1.5–2.5 and ≈ 15–20 min** (vs $6 / ~60 min full). Useful, but still not
  something you want to pay on every prompt tweak.

### The real 10×+ win: a $0 replay tier

The $6 is **LLM extraction output tokens**. But look at where the three diagnosed
misses are fixed in the pipeline (`helixpay/ingest/pipeline.py`):

```
load → chunk → embed → [LLM extract] → resolve → canonicalize → persist → contradict
                        └─ the $6 ──┘   └──────── all three fixes live here ────────┘
```

1. **Seed the "HelixPay" company entity** → changes `resolve` (post-LLM).
2. **Extend `metric_vocab` predicate canon** → changes `canonicalize` (post-LLM).
3. **Robust `normalize_value`** → changes `contradict` / value-match (post-LLM).

None of the three requires re-asking the model anything. And the pipeline already
makes this trivial to exploit: `pipeline.run(..., extractor=...)` takes an
**injectable extractor seam**. So:

- **Record once:** wrap the real `ChunkExtractor` in a caching extractor that
  writes each chunk's raw extracted claims to disk, keyed on `content_hash`
  (which every loader already computes) + chunk index. Pay the $6 (or $2 subset)
  exactly once.
- **Replay free:** a `ReplayExtractor` reads those cached claims and feeds them
  back, so `resolve → canonicalize → persist → contradict → eval` run with **zero
  API calls, in seconds**. Iterate on all three fixes (and on the metric vocab,
  the roster, contradiction thresholds) at **$0**.

This is the answer to "I don't want to spend an hour and $6 every time." Most
iterations should cost nothing.

### The three-tier protocol

| Tier | When | Cost | Time |
|------|------|------|------|
| **0 — Replay** | Tuning anything *after* the LLM call: roster/company entity, `metric_vocab`, `normalize_value`, contradiction logic, resolution | **$0** | seconds |
| **1 — Subset re-extract** (14 files) | You changed the **prompt**, chunking, schema, or added a gleaning pass — i.e. what the LLM *emits* changes | **~$2** | ~20 min |
| **2 — Full corpus** | Final gate before submission; catches regressions/over-extraction on the 30 omitted files | **~$6** | ~60 min |

One caveat to state plainly: the subset will **not** catch precision regressions
on the omitted interviews (e.g. a looser prompt that over-extracts garbage). So
Tier 1 is for *development*, Tier 2 is a *mandatory single gate* before you trust a
number for submission. Never report a subset recall as the final figure.

---

## Part 2 — Raising recall to 85%

### First, reconcile what "27% recall" is actually measuring

The baseline misses are **mostly not extraction failures** — they're downstream.
Diagnosis from the live run: ~6 of 11 misses are the **company entity not
resolving** (the claim *was* extracted, it just didn't attach to "HelixPay"); the
Confluence contradiction didn't materialize because the GA dates landed under
**non-canonical predicates**; and `no_false_contradiction` fails because
**`normalize_value` over-fires** ('18 months' vs 'eighteen months', '14.2M' vs
'14.2 million'). So for *this* eval:

> **The three post-LLM fixes are necessary and probably sufficient to clear 85%,
> and the replay tier tests them for $0.** Seeding the company entity alone is
> modeled at 27% → ~67%.

Do these first. They are the highest-leverage, lowest-cost moves and they are
already scoped in `SOLUTION.md §4`.

### Then: SGR and the extraction literature — what's worth adopting

**What SGR is.** Schema-Guided Reasoning (Rinat Abdullin; reference impl
`vamplabAI/sgr-agent-core`) is a *prompting methodology*, not a library: instead of
making the model fill a flat output schema directly, you give it an explicit,
typed **intermediate reasoning schema** to fill first, then derive the final
structured output from those intermediates. Constrained decoding of a flat schema
can silently degrade reasoning; SGR separates "think" from "emit." Three patterns:

| SGR pattern | What it is | How it maps to our pipeline |
|-------------|-----------|------------------------------|
| **Cascade** | sequential typed steps, each feeds the next | stage extraction: *find mentions → ground to evidence span → emit Claim triple* (our schema already grounds: `evidence` precedes `object_value`, `schemas.py:38`) |
| **Routing** | a discriminator field branches to sub-schemas | branch the extraction prompt by **document format** — a dashboard table, a Slack thread, and an interview want different extraction hints. We already have per-format *loaders*; this extends the idea to per-format *extraction*. |
| **Cycle** | a loop field drives repeated passes until "nothing new" | **gleaning** — we already run `glean_passes=1` (`pipeline.py`). The lever is making the glean prompt *predicate-family-specific* ("what revenue / headcount / reporting facts did you miss?") rather than generic, and gating on new-claim ratio. |

Reported SGR gains over plain structured output are ~5–10% — real but second-order
here, where the bottleneck is resolution, not the model's reasoning.

**The leverage-ordered list from the wider literature** (filtered to what helps
*us*, biggest first):

1. **Chunking** — the single biggest recall lever in the literature (attention
   dilution: smaller semantic chunks with ~10–20% overlap can multiply extracted
   facts). We target ~650 tokens already; worth A/B-testing 512 vs 650 with
   overlap **on the replay-recorded subset** — but note: a chunking change
   *invalidates the replay cache* (it changes what's sent to the LLM), so it's a
   Tier-1 cost.
2. **Gleaning, sharpened** — already present; make it predicate-family-specific
   and loop-until-dry (Tier 1).
3. **Schema flattening + field-description enrichment** — PARSE/ARCHITECT report
   10%+ from flatter schemas and rich field docstrings with inline examples
   (e.g. `predicate: # canonical key, e.g. 'arr', 'reports_to', 'ga_target'`).
   Zero extra cost. Worth a Tier-1 pass.
4. **Decomposition by predicate family** — separate focused passes (financial
   metrics / org structure / temporal) beat one 30-field pass, at N× call cost.
   Only if 1–3 don't reach the bar; expensive.
5. **Structured critic / reflection pass** — a verifier LLM emits *field-level*
   findings ("`as_of` missing on the ARR claim") and the extractor re-runs. High
   error-reduction in the literature, but it's a cost multiplier — last resort.

**What to *not* do yet** (unchanged from `SOLUTION.md`): a **reranker** and
**self-consistency / K-sample union** both polish *retrieval/precision*, not the
*resolution* bottleneck. Premature until recall is retrieval-bound.

---

## Recommended next action

1. **Build the replay tier (Tier 0).** A `CachingExtractor` + `ReplayExtractor`
   around the existing `extractor=` seam, persisting raw claims keyed on
   `content_hash`. One-time ~$2 record on the 14-file subset, then free iteration.
   *(Dev tooling — no production-contract change; cheap to add.)*
2. **Land the three post-LLM fixes against replay, for $0**: seed `HelixPay`
   (+ region/company aliases) in the roster, extend `metric_vocab`
   (`ga_target`/launch/cutover synonyms, company revenue), harden
   `normalize_value` (word-numbers, currency/unit suffixes, ~approx). Watch recall
   climb 27% → ~67% → toward the bar with zero spend.
3. **If still short of 85%, do one Tier-1 prompt/schema pass** (sharpen gleaning +
   flatten/enrich schema) on the subset (~$2).
4. **Gate once on the full corpus (Tier 2, ~$6)** before reporting a final number.

Net: the only paid runs are one subset record (~$2) and one final full gate (~$6).
Everything in between is free.
