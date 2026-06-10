# SP_015 — One-per-type proving record (human narrative)

> **Status: TEMPLATE — not yet run.** Filled in by the operator after the 9-doc proving loop
> passes on `helixpay_smoke`. This file is the *human-readable* record; it **gates nothing
> mechanical**. The gate (`scripts/full_run.py`) re-derives pass/fail from the machine
> artifact `workspace/acceptance/SP015_smoke_result.json` (emitted by `eval.smoke.check_smoke`)
> and recomputes the doc content hashes — a typed flag here cannot open the gate.

## How to produce the proof (operator, DB-gated, paid ~9 docs)

```
# 0. isolated smoke DB (own gitignored env: eval/smoke/.env or .env.smoke — DB name
#    helixpay_smoke; same password form; NEVER commit it, NEVER paste a connection string here)
python -m eval.smoke.build_smoke                 # build the one-per-type corpus + filtered golden ($0)
#    migrate + seed helixpay_smoke, then record the 9 docs (paid, Sonnet+Voyage, ~minutes)
#    run check_smoke against helixpay_smoke -> writes SP015_smoke_result.json
```

## Result summary (fill in)

- Smoke DB: `helixpay_smoke`  *(name only — never the DATABASE_URL / password)*
- Corpus built by: `eval.smoke.build_smoke` · machine result: `SP015_smoke_result.json`
- Verdict: __ / 9 PASS  (target 9/9; any INCOMPLETE/FAIL blocks the gate)

| # | archetype | source_uri | golden | completeness (ledger) | embedding | verdict |
|---|-----------|------------|--------|------------------------|-----------|---------|
| 1 | overview   | data/overview.md | | | | |
| 2 | pdf        | data/board-deck-q1-2026.pdf | | | | |
| 3 | dashboard  | data/dashboards/april-2026-kpi-dashboard.html | | | | |
| 4 | email      | data/email/customer-acai-express-thread.md | | | | |
| 5 | interview  | data/interviews/sales/maria-silva.md | | | | |
| 6 | org_chart  | data/org-chart.md | | | | |
| 7 | code       | data/code/contributors-analysis-q1-2026.md | | | | |
| 8 | chat       | data/chat/sales-floor-april.md | | | | |
| 9 | image      | data/images/revenue-trend-q1-2026.jpeg | | | | |

## Caveats recorded with this proof (do not drop)

- **Completeness needs SP_014.** Until SP_014's loss ledger is wired, the completeness column
  reads **INCOMPLETE** (no silent-loss proof) — and an INCOMPLETE doc is **not** a PASS, so the
  gate stays shut. This is by design.
- **Types, not instances.** A green 9/9 proves each *archetype*, not every *instance* — images
  (4 layouts) and dashboards (3 layouts) have intra-type spread; the full run's ledger is the
  backstop.
- **Advisory gate.** `make ingest`, `make ingest-record`, `replay record ./data`, and
  `deploy/deploy.sh` bypass `full_run.py`. The "no more full runs" rule is held by discipline +
  the SP_016 deploy decoupling until the enforcement chokepoint (open fork) lands.
