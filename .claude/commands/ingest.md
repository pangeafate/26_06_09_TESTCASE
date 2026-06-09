---
description: Ingest the HelixPay dataset into the ontology (idempotent)
---

Run the full ingestion over `data/`: discover files with each `SourceConnector`,
normalize to `Document` + `Chunk`s, extract claims/links/contradictions, and write
through the `Repository`. Idempotent on `content_hash` — re-running on unchanged
data is a no-op; a changed file supersedes prior claims (never deletes).

> Depends on Agent 5's Makefile. Once it lands:
>
> ```bash
> make ingest          # = uv run python -m helixpay.ingest ./data
> ```
>
> Until then, the gate-level pieces are:
>
> ```bash
> uv run python -m helixpay.db.migrate        # apply schema (needs DATABASE_URL)
> uv run python -m helixpay.seed.run_seed     # seed roster + metric_vocab + fixture
> ```

Required env: `DATABASE_URL`, `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`.
