# `eval/sample/` — curated smoke subset + ground truth

A **fast testing sample**: a curated ~11-doc slice of `data/` (≈5–6 min to extract vs ~1 h
for the full corpus) with a ground truth that is a **verbatim subset of the verified golden
oracle** (`test/golden/facts.yaml` + `eval/questions.yaml`), produced by
`build_sample.py`. Use it to iterate on the **extraction** quickly without re-running the
full hour.

## Why curated, not random

The whole point of this corpus is its **planted, cross-document conflicts**. Those need
specific document *pairs* to exist, so a random 10% (~4 docs) would contain none of them
and the sample eval would be blind to the behavior that matters. Size is therefore driven
by **trap coverage**, which lands at ~11 docs (~27%) — a bit above 10%, because the
contradictions are multi-source by design.

## What's covered (trap → docs)

| Planted trap / signal | Docs in the sample |
|---|---|
| **Confluence GA timeline contradiction** (THE primary) | `all-hands` (end-June, side A) + `board-deck` (end-Q3, side B) + corroboration: `board-update-2026-04-22`, `interviews/leadership/Daniel_Tan` |
| **NPS framing** (47 aggregate vs 62 SEA-enterprise) | `dashboards/april-2026-kpi-dashboard` (47) + `all-hands` (62) + `board-update` |
| **Honest-oracle revenue agreement** (no false 13.9M conflict) | `q1-2026-results.pdf` + `april dashboard` + `board-deck` — all 14.2M |
| **Two Marias** (Santos/CS ≠ Silva/Sales) | `email/customer-acai-express-thread` (Santos) + `interviews/sales/maria-silva` (Silva) |
| **Two Tans** (Daniel Tan ≠ Tan Wei Ming) | `code/contributors-analysis-q1-2026` + `interviews/leadership/Daniel_Tan` |
| **Org hierarchy** (Daniel→Arjun→Wei; Sara→Daniel; headcount 274) | `org-chart.md` |
| **Customer ownership** | `email/cosmos-hotels-debrief` (Marcus Lee→Cosmos) + Açaí thread (Santos→Açaí) |

Format coverage: md, pdf, html, email, interview, code, org-chart. **Dropped** from the
full golden set (and why): `md-overview-runway`, `slack-crm-cutover-june`,
`image-revenue-trend-caption` — their docs aren't trap-bearing; the questions that cited
them keep ≥2 other sources. Kept: **13/16 facts, 2/2 contradictions, 6/6 questions.**

## Regenerate

```bash
uv run python eval/sample/build_sample.py
```
Deterministic; re-run whenever the golden set grows (e.g. SP_013). It re-copies the docs
and re-filters the oracle — never hand-edit `eval/sample/facts.yaml` / `questions.yaml`.

## Run the extraction-iteration loop (~5–6 min/iteration, paid)

Two things make this correct:

1. **`source_uri` parity** — run ingest with **root `data` from inside `eval/sample`** so
   discovered paths are `data/...`, matching the golden refs verbatim. (Bonus: root `data`
   — not `./data` — means the sample cache files are cleanly named, avoiding the `._`
   prefix the full run hit.)
2. **DB isolation** — extract into a **separate database** so sample claims never mix with
   the full-corpus DB (which we keep for the production `pg_dump`). Add one line to `.env`
   (same password, DB name `helixpay_sample`) so no secret touches the shell:
   ```
   DATABASE_URL_SAMPLE=postgresql://postgres:<same-password>@db:5432/helixpay_sample
   ```

```bash
Put the sample URL in its own gitignored env file so no secret hits the shell — copy `.env`
and change only the DB name:

```bash
# one-time
cp .env eval/sample/.env.sample          # then edit: DATABASE_URL=...@db:5432/helixpay_sample
docker compose exec db createdb -U postgres helixpay_sample
ENV='--env-file eval/sample/.env.sample'
docker compose run --rm $ENV app python -m helixpay.db.migrate
docker compose run --rm $ENV app python -m helixpay.seed.run_seed

# each iteration: record the subset (paid ~5–6 min) → eval against the sample oracle
docker compose run --rm $ENV -w /app/eval/sample -v "$(PWD)/eval/sample:/app/eval/sample" \
  app python -m helixpay.ingest.replay record data --cache-dir .replay-cache
docker compose run --rm $ENV -v "$(PWD)/eval/sample:/app/eval/sample" \
  app python -m eval.run --golden eval/sample/facts.yaml --questions eval/sample/questions.yaml
```

`eval/run.py` already accepts `--golden`/`--questions` and matches facts by basename, so the
sample oracle is consumed as-is — no code change. After the first record, an
extraction-code change is a `--force` record of just these 11 docs; pure post-extraction
work (contradiction/provenance/query) can **replay** the sample cache at $0.

> Notes:
> - Add `eval/sample/.env.sample` to `.gitignore` (it carries the DB password); never commit it.
> - A `make *-sample` target is a tidy infra follow-up (overlaps **SP_013** eval-rigor
>   scope — coordinate there rather than editing the shared Makefile here).
> - This is a dev/test fixture (DEV_RULES Rule 15); it adds no production code path.
