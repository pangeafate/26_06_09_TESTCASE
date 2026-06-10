# SP_019 — Extraction attribution: run finding & evidence

**Sprint:** SP_019 (extraction attribution) · **Branch:** `sprint/SP_019-extraction-attribution`
**Status:** all three layers implemented; operator-approved paid re-record RAN 2026-06-10.
**DB referenced by name only:** `helixpay_smoke` (never a DATABASE_URL / DSN — CLAUDE.md §7).

## MEASURED RESULT (operator-approved re-record, 2026-06-10)

Reset the smoke DB derived rows (kept chunks+embeddings+seeded roster), re-recorded all 9 docs
with the SP_019 prompt through the new pipeline (Sonnet extract + Voyage embed, no Opus — a few
cents), then graded with `python -m eval.run --golden facts.yaml`:

**Golden recall: 4/11 → 7/11 (36% → 64%), golden-precision 100%, found=7 mismatch=0 missing=4.**

The three facts SP_019 targeted are now **FOUND**:
- ✓ `html-dashboard-revenue` — subject fixed (`metric|Q1 2026 Revenue` → `HelixPay`) **and**
  as_of corrected to the Q1 end (`2026-03-31`, not the dashboard's "As of 2026-04-21").
- ✓ `html-dashboard-nps` — same.
- ✓ `interview-brasil-revenue` — regional attribution worked; **not** falsely merged into the
  company (mismatch=0; Level-2 `q-dashboards-vs-boarddeck` passes `no_false_contradiction✓`).

The 4 still **MISSING** are exactly the SP_010 hand-off items (alias / vocab / resolution /
shape — NOT attribution):
- ✗ `pdf-boarddeck-confluence-q3` — no clean `(Project Confluence, ga_target)` claim (shape).
- ✗ `slack-crm-cutover-june` — no `(CRM migration, completion_target)` claim (surface form).
- ✗ `email-acai-owner` — endpoint `Açaí Express SP` unresolved (entity alias).
- ✗ `code-core-top-contributor` — no `(helixpay/core, top_contributor)` (predicate vocab:
  the extractor emits `primary owner`).

**Bottom line:** the re-record confirmed the thesis — the metric-attribution + dashboard-as_of
defects are fixed (3/3 target facts now FOUND, zero false attributions), lifting recall to 64%.
The remaining 28% to clear the 80% bar is **SP_010 territory** (roster aliases + predicate
vocab), not extraction attribution. (Note: running the full `eval.run` also fired the Level-2
`ask()` checks on Opus — a few extra cents beyond the approved record; use `check_extraction`
alone for a $0 recall-only re-measure.)

---

## Original plan & evidence (pre-run)

## What shipped (deterministic, $0, test-proven)

- **Layer 0 — `helixpay/ingest/repair.py`:** a known **company** metric typed as the *subject*
  (`subject_type="metric"`) is re-attributed to the seeded company with the metric as the
  predicate. Period-qualifier aware (`"Q1 2026 Revenue"` → recognised). Milestone predicates
  (`ga_target`/`completion_target`) are **excluded** so a project/product GA is never pulled
  onto the company. No-op for regional/unknown metrics (`"HelixPay Brasil revenue"`).
- **Layer 2 — `helixpay/ingest/resolve.py`:** a type-agnostic **seeded-roster snap** before
  minting kills the `metric|HelixPay` duplicate (a company name mis-typed `metric`). Snaps only
  to a seeded row, only on the mint path, never bridges the two-Marias/two-Tans trap.
- **Layer 1 — `prompts/extract_claims.md`:** removes the metric-as-subject license, attributes
  ownerless KPIs to the primary entity (or named region), demands canonical period-stripped
  predicates and the value's-own-period `as_of` (the dashboard date-vs-quarter bug), with a
  negative few-shot incl. the regional case. **Paid to measure — gated.**

Automated proof (no DB, deterministic): `test/unit/ingest/test_pipeline.py::test_layer0_*` push
the **exact `.replay-cache/` surface forms** through `_ingest_document` and assert the dashboard
revenue/NPS land on the seeded company (NPS canonicalizes to `nps`), no `metric|...` is minted,
and the Brasil value is **not** merged. 617 tests pass, mypy clean.

## The honest recall picture (cache + grader audit — the load-bearing finding)

A claim-by-claim audit of `.replay-cache/` against `eval/smoke/facts.yaml` under the real grader
(`eval/run.py:122-152`; as_of passes iff the **claim's** as_of OR **any source's** as_of equals
golden) shows the dominant blocker for the 7 failing golden facts is **as_of / predicate /
claim-shape baked into the cache** — which **no $0 post-processing can repair**:

| golden fact (source) | cache reality | $0 layers reach | re-record? |
|---|---|---|---|
| dashboard `revenue` 14.2M @ **2026-03-31** | `metric\|Q1 2026 Revenue`, as_of **2026-04-21** (doc date) | MISSING→**MISMATCH** (subject fixed; as_of wrong) | **yes** (as_of) |
| dashboard `nps` 47 @ **2026-03-31** | `metric\|Aggregate NPS`, as_of **2026-04-21** | MISSING→**MISMATCH** | **yes** (as_of) |
| `Project Confluence` `ga_target` end-Q3 | buried in odd predicates on `HelixPay` | no clean claim | **yes** (shape) |
| `helixpay/core` `top_contributor` Sara | `helixpay/core` / **`primary owner`** / Sara / 2026-04-08 | predicate+as_of off | **yes** (+ SP_010 vocab) |
| `HelixPay Brasil` `revenue` 4.8M @ 2026-03-31 | regional (interview/image), distinct subject (correct) | n/a | **yes** (attribution+as_of) |
| `CRM migration` `completion_target` end-Jun | chat | shape/predicate | **yes** |
| `Maria Santos` owns `Açaí Express SP` | email relations | link/resolution | **yes** |

**Conclusion for the operator:** the deterministic layers make attribution *correct* (kill the
`metric|HelixPay` dupe; attribute dashboard/chat company metrics to HelixPay) but **do not move
the golden number at $0** — the failing facts carry as_of/predicate/shape errors that only
re-extraction fixes. **Reaching ≥80% requires the Layer-1 re-record.** No $0 recall number is
claimed.

## Pending operator step 1 — live $0 diagnostic (confirms the thesis, no spend)

The running app is a **baked image without a code mount**, and `helixpay_smoke` has no host port,
so the live replay needs a rebuild. Expected result: dashboard revenue/NPS move
MISSING→**MISMATCH** and the `metric|HelixPay` dupe disappears — evidence the residual is the
re-record case. Exact commands (passwords stay **inside** the container — never on the host shell):

```bash
# 1. rebuild so the container has the SP_019 code
docker compose build app
# 2. reset derived rows on the THROWAWAY smoke DB (keep chunks+embeddings+seeded roster);
#    POSTGRES_PASSWORD is expanded inside the container, never printed to the host.
docker compose exec -T db sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -U "$POSTGRES_USER" -d helixpay_smoke -c \
  "DELETE FROM claims; DELETE FROM links; DELETE FROM entities WHERE seeded = false;"'
# 3. replay the cached extractions through the new resolve+repair ($0 — no Anthropic/Voyage call)
docker compose run --rm -e DATABASE_URL_FROM_SMOKE app sh -c \
  'DATABASE_URL="postgresql://$POSTGRES_USER:$POSTGRES_PASSWORD@db:5432/helixpay_smoke" \
   python -m helixpay.ingest.replay replay data'
# 4. re-grade
docker compose run --rm app sh -c \
  'DATABASE_URL="postgresql://$POSTGRES_USER:$POSTGRES_PASSWORD@db:5432/helixpay_smoke" \
   python -m eval.run --golden eval/smoke/facts.yaml'
```

## Pending operator step 2 — the gated paid re-record (the path to ≥80%)

The measured lever. Re-record the 9 smoke docs on `helixpay_smoke` with the SP_019 prompt
(`python -m helixpay.ingest.replay record data --force`) — **Sonnet extract + Voyage embed, no
Opus**. Cost: 9 docs × ~1 chunk, ≈ 3k input / 0.8k output tokens each ≈ **a few US cents total**,
minutes of wall-clock. **Do not run without operator approval** (standing no-paid-extraction
rule). Then re-grade as above; expect the dashboard/NPS as_of and the metric subjects to land,
lifting recall toward the ≥80% bar. Record the actual number here after the approved run.

## Hand-off to SP_010 (its files, not edited here)

- Surface-form alias expansion: `Confluence platform`/`Confluence GA`/`CRM migration` → seeded canon.
- A `primary owner` → `top_contributor` predicate decision for `helixpay/core`.
- Optional: mirror the period-strip into `metric_vocab.canonical_key` (deferred in SP_015 717c4ec).
