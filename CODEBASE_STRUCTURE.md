---
status: living
last-reconciled: 2026-06-09
authoritative-for: [directory-layout, layer-rules]
---

# Codebase Structure

## Layout (as of the Phase 0 gate)

```
helixpay/
  __init__.py
  config.py                 # env-only secrets + pinned model ids (no literals)
  contracts/                # FROZEN cross-module types — import from here, never redefine
    models.py               #   Document, Chunk, Entity, Claim, Link, Contradiction, Citation, AnswerBundle, OrgNode, EntityDetail
    connector.py            #   SourceConnector Protocol
    repository.py           #   Repository Protocol
    query.py                #   QueryEngine Protocol
  db/                       # the ONLY place with raw SQL
    schema.sql              #   the 8-table ontology schema
    migrate.py              #   apply schema (statement-by-statement, GL-ERROR-LOGGING)
    connection.py           #   psycopg connection helper (dict rows)
    repository.py           #   PostgresRepository — the one Repository impl
  seed/                     # deterministic backbone (pure parsers + DB loaders)
    roster.py               #   parse org-chart.md / overview.md → entities + links (NO db imports)
    metric_vocab.py         #   controlled metric vocabulary + canonical_key()
    run_seed.py             #   orchestrates seeding via Repository (CLI: python -m helixpay.seed.run_seed)
    fixtures.py             #   minimal query fixture (writes via Repository)
test/
  conftest.py               # `db` mark auto-skips unless DATABASE_URL set (no fallback creds)
  unit/contracts/**         # model + protocol tests (no DB)
  unit/seed/**              # parser + vocab tests (inline fixtures; real data marked `smoke`)
  integration/db/**         # DB-gated repository tests
.claude/                    # commands/{ingest,verify}.md, agents/verifier.md
pyproject.toml              # uv/hatchling, Python ≥3.12, pytest + mypy config
```

Owned-by-future-agents (not yet present): `ingest/` (Agent 1/2), `query/` (Agent 3),
`mcp/` `api/` `cli.py` (Agent 4), `deploy/` `Dockerfile` `Makefile` (Agent 5),
`eval/` `tests/golden/` `prompts/` (Agents 2/6).

## Layer rules (dependencies flow inward)

```
capabilities (ingest, query, mcp, api, seed)  →  shared logic (contracts)  →  models
infrastructure (db) stands alone behind the Repository seam.
```

- **Cross-module types live only in `helixpay/contracts/`** and are never redefined.
- **All DB access goes through `Repository`; raw SQL only in `helixpay/db/`.**
- **Secrets only from env** (`helixpay/config.py`); never hardcode or log them.
- Tests mirror the package under `test/unit/**` and `test/integration/**`.
