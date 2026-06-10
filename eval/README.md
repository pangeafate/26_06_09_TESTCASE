# Eval & Ground-Truth — the author-independent oracle (Agent 6)

This harness decides whether the HelixPay build meets `/goal`
(`HELIXPAY_BUILD_SPEC.md` §8). It was authored by inspecting the **raw `data/`**
files by eye, against the **frozen contracts only** — it imports no build slice, so
its ground truth is an honest oracle and it is the legitimate author-independent
grader for the adversarial stage.

## What's here

| File | What it is |
|------|------------|
| `../test/golden/facts.yaml` | The golden ground truth — **≥30 by-eye bar facts, ≥2 per source format**, the real planted contradiction, plus `predicate_synonyms` (ARR ≡ "annual recurring revenue") and `entity_collisions` (two Marias / two Tans). |
| `questions.yaml` | The deep-question set, each with `checks:` exercising one failure mode (incl. a prefer-fresh-and-say-so freshness question, distinct from the surface-both contradiction case). |
| `run.py` | The two-level autotest harness — extraction recall/precision **+ Wilson CIs + macro-per-predicate recall**, answer checks, **WikiContradict 3-class contradiction scoring**, entity-collision + As-of-Correctness reporting. |
| `models.py` | Typed records (pydantic over the YAML) + report types (`wilson_interval`, `ContradictionClass`, …). |
| `../test/golden/test_*.py` | Tests of the **grader itself** (a wrong oracle is worse than none) — `test_rigor.py` covers the SP_013 statistical + structural checks. |

## Run it

```bash
# unit (no DB): validates the golden set + grades the harness logic
uv run pytest test/golden -q

# full two-level autotest (needs a migrated + ingested DB and Agent 3's QueryEngine)
export DATABASE_URL=postgresql://...
uv run python -m eval.run            # wired into `make test` / `make demo`
```

`python -m eval.run` exits **0** when `/goal` is met, **1** when it is not (a blocker
is printed), **2** when it cannot run (no DB, or `helixpay.query` not yet merged — it
degrades cleanly rather than crashing). The concrete `QueryEngine` is resolved lazily
at run time (`build_engine`), which is what keeps the oracle independent of the code it
grades; tests inject a stub engine.

## The recall bar

**Golden-set recall must be ≥ 80%** for `/goal` to go green (`DEFAULT_RECALL_BAR` in
`run.py`). **39 facts are on the bar** (the 40th, an image caption, is informational —
deep JPEG figure extraction is a SPEC §11 scope cut, so it does not count). 80% = at
most ~7 of 39 bar facts may be missed. The bar is deliberately below 100% because a few
facts depend on entity resolution the extractor legitimately may not nail on the first
pass (customer entities, the "HelixPay" company entity — see findings); it is high
enough that the org hierarchy, the financial headline metrics, the customer-ownership
links, and **both sides of the planted contradiction** must all land.

The set was grown from 15 → 39 bar facts (SP_013) because *a dozen facts cannot support a
recall bar* — one miss was an 8-point swing (per the evaluation & ground-truth
best-practices research note, P0 #1). The harness now reports a **Wilson 95% confidence
interval** and **macro-per-predicate recall** alongside the point estimate, so the bar is
read with its uncertainty, not as a bare ratio.

### Precision / recall, defined

- **recall** (micro) = `FOUND / bar facts` — the fraction of golden facts present in the
  ontology with the right value + source (+ `as_of`). Reported with its **Wilson 95% CI**.
- **macro recall** = mean of per-predicate recall, weighting every predicate equally — it
  surfaces a rare-predicate miss (e.g. `dotted_line_to` recall 0) that a micro score
  dominated by the common predicates would hide. The rendered report lists per-predicate
  recall worst-first.
- **golden-set precision** = `FOUND / (FOUND + MISMATCH)` — of the golden subjects the
  extractor *attempted* (a claim/link on the right `(subject, predicate)` exists), the
  fraction it got *right*. This is **not** corpus precision (we don't enumerate every
  spurious claim); it is labelled "golden-precision" in the output so it isn't misread.
- Per-fact verdict: **FOUND** (value + source [+ as_of] all match) · **MISMATCH** (a
  claim/link on the right subject+predicate exists but the value, source, `as_of`, or
  link direction is wrong) · **MISSING** (nothing — subject unresolved or no claim).

> **CI caveat (stated, not hidden):** Wilson assumes i.i.d. Bernoulli trials, but golden
> facts are **clustered by source document**, so the true standard error is wider than the
> reported interval. The rendered report prints this caveat inline.

### The match function (specified, not implicit)

A golden fact MATCHES a claim/link iff **all** of:

- **subject** — resolved `entity_id` equal (`Repository.resolve_entity` with the fact's
  `source_uri` as context). Asserting the resolved id (not the string) is what keeps the
  two Marias / two Tans distinct.
- **predicate** — `canonical_predicate(fact) == canonical_predicate(claim)`.
- **value** — numeric equality via the **shared** `helixpay.ingest.normalize.values_equal`
  (currency / magnitude / word-number / unicode-minus aware), with a documented substring
  fallback for free **text** (dates/labels the numeric path can't compare). When both sides
  are pure numbers the numeric verdict is final (no substring fallback — so `"41"` never
  matches `"241"`).
- **source_uri** — same basename, or the golden URI is a substring of the claim's.
- **as_of** — `AS_OF_TOLERANCE_DAYS` (default **0** — exact) against the claim's own date
  **or** any of its source-citation dates (a dashboard exported `2026-04-21` reporting a Q1
  figure may stamp either the export date or the period end `2026-03-31`).

> **Shared-normalizer coupling (by design).** The matcher reuses `values_equal` so
> predicted-vs-gold equivalence cannot drift from contradiction detection. `normalize.py`'s
> own docstring names the eval matcher as an intended consumer, so it is shared substrate,
> not a build slice — but to preserve oracle-independence the grader keeps its **own**
> equality assertion (eval-authored golden pairs in `test_rigor.py`), so a normalizer
> regression is still caught by the oracle's tests.

### Contradiction scoring (WikiContradict 3-class)

Beyond the `/goal` floor ("≥1 real contradiction surfaced"), each planted contradiction a
question references is scored **Correct** (the right subject+predicate conflict is surfaced
AND references **both** distinct claim ids), **Partial** (surfaced but only one side carries
a claim id), or **Incorrect** (no matching contradiction → a silent merge). Scoring is
subject-aware: a conflict on the wrong entity does not earn credit.

### Freshness vs contradiction (As-of Correctness)

Freshness is scored **apart** from contradiction (research P1 #6): a *prefer-fresh-and-
say-so* question (`q-latest-revenue-freshness`: Q1 14.2M is fresher than Q4 15.4M, and they
are NOT a conflict) feeds an **As-of Correctness** count, distinct from the surface-both
contradiction question. A system that always returns the newest value scores well on
freshness but must still surface genuine conflicts.

## The honest-oracle correction (read this)

The SPEC §8 example golden set and the gate's query fixture
(`helixpay/seed/fixtures.py`) assume a **Q1 revenue** contradiction — dashboard
`14.2M` vs board-deck `13.9M`. **That conflict does not exist in the raw data.**
Revenue is **SGD 14.2M in every source**: `q1-2026-results.pdf`, the April dashboard,
`board-deck-q1-2026.pdf` (p.3), `overview.md`, and the all-hands transcript. The
`13.9M` is synthetic fixture data invented so Agent 3 had a live contradiction row to
build against — fine as a dev aid, **not** ground truth.

The **real planted contradiction** is the **Confluence platform GA date**:

| Side | Value | Source | as_of |
|------|-------|--------|-------|
| Public (all-hands) | end of June 2026 (end-Q2) | `data/all-hands-2026-04-15.md` | 2026-04-15 |
| Internal / board | end of Q3 2026 (~Sep 30) | `data/board-deck-q1-2026.pdf` | 2026-05-12 |

Corroborated by the weekly review (04-21), the board update (04-22), and Daniel Tan's
interview (04-10, "realistic GA is late August to mid September … I'd commit to
September 30"). The board deck itself flags that the all-hands stance was unchanged
from the original plan — i.e. the conflict is intentional. It is **temporal + a
public-vs-internal source disagreement**: a correct answer surfaces both sides,
attributes each, and prefers the freshest (Q3) while noting the change.

A secondary, softer planted conflict is the **NPS framing** — the all-hands led with
`62` (the SEA-enterprise segment) while the honest aggregate is `47`. Not a value
conflict on one predicate; a framing/segment disagreement. The harness rewards an
answer that distinguishes the two with sources, and (via `no_false_contradiction`)
**penalizes** a system that invents a revenue conflict to satisfy the question.

## Findings for the fixer (filed, not patched — Agent 6 edits no one else's code)

1. **CRITICAL — ground-truth correction.** Do not grade against a revenue
   contradiction; the real one is the Confluence timeline (above). The gate fixture's
   `13.9M` should be relabelled a synthetic dev row, not treated as a golden fact.
2. **HIGH — no `HelixPay` company entity is seeded.** Company-level metrics (revenue,
   NPS, runway, headcount, net-new-merchants) attach to a `HelixPay` org entity, but
   the gate seeds only `HelixPay Brasil` + products from `overview.md`. Either the gate
   seeds a parent `HelixPay` entity or extraction must create it; otherwise five golden
   claims are MISSING regardless of correct extraction. (Observed live: `run.py` reports
   "subject 'HelixPay' unresolved" on a seeded-but-un-ingested DB.)
3. **MEDIUM — customer entities + `owns` links.** `Cosmos Hotels`, `Açaí Express SP`,
   etc. are not seeded; extraction must create the customer entities and the AE/CSM
   `owns` links, keeping the two-Marias trap distinct (Maria Santos = CS; Maria Silva =
   Sales). The `q-customers-and-owners` answer check + the two email golden links test this.

Findings are emitted as part of the adversarial Phase-B pass; the harness output
(per-fact MISSING/MISMATCH reasons, per-question check breakdown) is the evidence.
