# SP_010 / SP_019 final mile — run finding & evidence

**Sprints:** SP_010 (recall/seed) + SP_019 (extraction attribution), Increment 2.
**DB referenced by name only:** `helixpay_smoke` (never a DATABASE_URL / DSN — CLAUDE.md §7).
**Date:** 2026-06-10.

## MEASURED $0 RESULT (replay tier, no API calls)

Reset the smoke DB derived rows (kept the 21 chunks + their embeddings + the 67-row seeded
roster), re-seeded with the new roster + vocab (`15 metrics` — `top_contributor` added; Açaí
Express SP seeded as a `customer`), replayed the 9 cached smoke extractions through the new
resolve/seed path with the **`_ConstantEmbedder` ($0 — no Anthropic, no Voyage)**, then graded
with `eval.run.check_extraction` (Level-1 only — no Opus `ask()`):

**Golden recall: 7/11 → 8/11 (64% → 73%), golden-precision 100%, found=8 mismatch=0 missing=3.**

The targeted $0 fact is now **FOUND**:
- ✓ `email-acai-owner` — the cached `Maria Santos --owns--> Açaí Express SP` link now persists
  and resolves. Seeding `Açaí Express SP` as a `customer` collapsed the dual `customer`/`other`
  mint to one seeded row (SP_019 seeded-snap), so the link endpoint is no longer ambiguous.

The 3 still **MISSING** are exactly the re-record-gated facts — confirmed unreachable at $0:
- ✗ `pdf-boarddeck-confluence-q3` — `no claim on (Project Confluence, ga_target)`. The cache
  carries `Confluence platform / "ga target date (revised)" / "end-Q3 (2026-09-30)"`: the
  predicate does not canonicalize **and** the value would not match golden `end of Q3 2026`
  under the grader normalize. Two baked defects.
- ✗ `slack-crm-cutover-june` — `no claim on (CRM migration, completion_target)`. The cache
  attributes `end of June` to `HelixPay` (predicate `pipedrive decommission date`), not to the
  `CRM migration` initiative. Wrong subject, baked in.
- ✗ `code-core-top-contributor` — `no claim on (helixpay/core, top_contributor)`. The cache
  has per-person commit counts (Sara=89=top) but never emitted a `top_contributor` claim.

**Zero false attributions (mismatch=0).** The deterministic layer added the one recall it can
and broke nothing.

## The honest gate to ≥80% (operator-approved paid re-record)

Reaching the 0.80 bar (≥9/11) requires one **paid re-record** of the 9 smoke docs with the new
SP_019 prompt (Sonnet extract + Voyage embed, no Opus — minutes, a few US cents). The prompt is
implemented and committed but **measured only under the operator spend gate** (standing
no-paid-extraction rule).

Projection (Stage-3 Findings 5/6) — **bar-clearing target 9/11 (82%)**:
- **Likely:** `slack-crm-cutover-june` — the value/as_of already match; the re-record only needs
  to re-subject the cutover to `CRM migration` with predicate `completion_target` (now in vocab).
- **Stretch (not counted on):** `pdf-boarddeck-confluence-q3` (golden phrasing "end of Q3 2026"
  vs source "end-Q3" — the grader's value normalize may still reject it; the principled fix is
  hardening `eval.run.normalize_value`, which is SP_013's oracle, not ours) and
  `code-core-top-contributor` (needs the extractor to assert the named lead — least reliable).

**Ordering (Stage-3 Finding 7):** SP_010 Increment 2 must be landed and the smoke DB re-seeded
*before* the re-record, or the new `top_contributor` / milestone predicates will not canonicalize.

## Reproduction (all $0 except the gated re-record)

```bash
# reset derived rows, keep chunks+embeddings+seeded (passwords stay inside the container, §7)
docker compose exec -T db sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -U "$POSTGRES_USER" \
  -d helixpay_smoke -c "DELETE FROM contradictions; DELETE FROM claims; DELETE FROM links; \
  DELETE FROM entity_aliases; DELETE FROM entities WHERE seeded = false;"'
# re-seed with the new roster + vocab (host-mount = live code; smoke URL derived in-container)
docker compose run --rm -v "$(pwd):/app" -w /app app sh -c \
  'DATABASE_URL="${DATABASE_URL%/*}/helixpay_smoke" python -m helixpay.seed.run_seed --data-dir data'
# $0 replay of the 9 smoke docs (ConstantEmbedder; run from eval/smoke so source_uris match cache)
docker compose run --rm -v "$(pwd):/app" -w /app/eval/smoke app sh -c \
  'DATABASE_URL="${DATABASE_URL%/*}/helixpay_smoke" python -m helixpay.ingest.replay replay data \
   --cache-dir /app/.replay-cache'
# $0 grade (Level-1 only — no Opus): expect recall 8/11
docker compose run --rm -v "$(pwd):/app" -w /app app sh -c \
  'DATABASE_URL="${DATABASE_URL%/*}/helixpay_smoke" python -c "from pathlib import Path; \
   from eval.run import load_golden, check_extraction; \
   from helixpay.db.repository import PostgresRepository; \
   r=check_extraction(PostgresRepository.from_url(), load_golden(Path(\"eval/smoke/facts.yaml\"))); \
   print(r.recall, r.found, r.total)"'
```

> Note: do NOT use the full `eval.run` / `make demo` for a recall-only re-measure — it also fires
> the Level-2 Opus `ask()` checks (a few extra cents). `check_extraction` alone is $0.
