# SP_020 — Mint-time dedup: run finding & evidence

**Sprint:** SP_020 (mint-time dedup, remove the Açaí hardcode). **DB:** `helixpay_smoke` (name
only, never a DSN — §7). **Date:** 2026-06-11.

## MEASURED $0 RESULT (replay tier, no API calls) — the proof

Removed the hardcoded `Açaí Express SP` seed and re-fixed the bug class at mint time
(`resolve.resolve_mention` snaps an open-class mention to an existing same-name row when one
side is the catch-all `other`). Then: deleted the previously-seeded Açaí row + derived rows,
re-seeded (66 entities — **Açaí no longer seeded**, confirmed 0 `Express SP` rows), replayed the
9 cached extractions through the **live** `resolve.py` (with the `_ConstantEmbedder`, $0), and
graded with `check_extraction`:

**Golden recall: 11/11 (100%), precision 100%, mismatch=0 — with NO hardcoded account.**

- ✓ `email-acai-owner` FOUND. After the replay there is exactly **one** Açaí row
  (`id 582, customer, seeded=false`) — the `other`-typed mention snapped to the `customer` row
  at mint time instead of minting a duplicate, so the bare name resolves and the
  `Maria Santos --owns--> Açaí Express SP` link persists at ingest.
- The other 10 facts held (no regression).
- **Safety guard verified:** the two Marias stay distinct — `id 35 Maria Santos` and
  `id 28 Maria Silva`, both seeded `person`, **not** bridged (persons are non-creatable and
  never reach the snap).

This is the answer to "we can't hardcode each account": the *class* is fixed for every account.

## Harness gotcha hit (and fixed) — recorded in CLAUDE.md

The first replay attempt reported `email-acai-owner` MISSING with **two** Açaí rows. Root cause:
the replay ran with CWD `/app/eval/smoke`, so `python -m helixpay.ingest.replay` imported the
**baked/installed** `helixpay` (old `resolve.py`), not the host-mounted edit — the mint-time
dedup never executed. Re-running with `PYTHONPATH=/app` used the live code → one row → 11/11.

## On the paid re-record

SP_020 changed **only resolution** (`resolve.py`), not extraction (no prompt change). The $0
replay already exercises the live `resolve.py` against the real cached extractions and shows
11/11 with no hardcode — so it is the authoritative test for this change. A paid re-record would
re-run the (unchanged) extraction at cost and only add LLM-variance noise; it does not test the
SP_020 change. The earlier SP_019 paid re-record already validated extraction at 11/11.

## Reproduction ($0)

```bash
# reset derived + the now-unseeded Açaí; re-seed (no Açaí)
docker compose exec -T db sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -U "$POSTGRES_USER" \
  -d helixpay_smoke -c "DELETE FROM contradictions; DELETE FROM claims; DELETE FROM links; \
  DELETE FROM entity_aliases; DELETE FROM entities WHERE seeded = false;"'
docker compose run --rm -v "$(pwd):/app" -w /app app sh -c \
  'DATABASE_URL="${DATABASE_URL%/*}/helixpay_smoke" python -m helixpay.seed.run_seed --data-dir data'
# replay with PYTHONPATH=/app (REQUIRED — else the baked resolve.py runs; see CLAUDE.md gotcha)
docker compose run --rm -v "$(pwd):/app" -w /app/eval/smoke app sh -c \
  'PYTHONPATH=/app DATABASE_URL="${DATABASE_URL%/*}/helixpay_smoke" \
   python -m helixpay.ingest.replay replay data --cache-dir /app/.replay-cache'
# grade ($0, no Opus): expect 11/11, Açaí found, two Marias distinct
docker compose run --rm -v "$(pwd):/app" -w /app app sh -c \
  'DATABASE_URL="${DATABASE_URL%/*}/helixpay_smoke" python -c "from pathlib import Path; \
   from eval.run import load_golden, check_extraction; \
   from helixpay.db.repository import PostgresRepository; \
   r=check_extraction(PostgresRepository.from_url(), load_golden(Path(\"eval/smoke/facts.yaml\"))); \
   print(r.recall, r.found, r.total)"'
```
