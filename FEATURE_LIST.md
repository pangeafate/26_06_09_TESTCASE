---
status: living
last-reconciled: 2026-06-09
authoritative-for: [features]
---

# Feature List

Status legend: ✅ done · 🚧 in progress · ⬜ planned (owning agent in parens).

## Phase 0 — Gate (SP_001) ✅

| Feature | Status | Source |
|---------|--------|--------|
| Frozen contracts (models + 4 Protocols) | ✅ | `helixpay/contracts/**` |
| Ontology schema (8 tables, pgvector + FTS) | ✅ | `helixpay/db/schema.sql` |
| Postgres Repository (idempotent, temporal, roster-first resolve, recursive org subtree, hybrid search) | ✅ | `helixpay/db/repository.py` |
| Schema migrator (statement-by-statement, GL-ERROR-LOGGING) | ✅ | `helixpay/db/migrate.py` |
| Env-only config + pinned model ids | ✅ | `helixpay/config.py` |
| Deterministic roster seed (people/teams/links/aliases; name traps distinct) | ✅ | `helixpay/seed/roster.py`, `run_seed.py` |
| Controlled metric vocabulary | ✅ | `helixpay/seed/metric_vocab.py` |
| Query fixture (incl. a planted contradiction) | ✅ | `helixpay/seed/fixtures.py` |
| HelixPay `CLAUDE.md` §7 conventions | ✅ | `CLAUDE.md` |
| `.claude/` commands + verifier agent stub | ✅ | `.claude/**` |
| Tests: 38 (unit + smoke + DB-gated integration); mypy clean | ✅ | `test/**` |

## Ahead (parallel build, post-gate)

| Feature | Status | Owner |
|---------|--------|-------|
| Loaders / connectors (md/pdf/html/image/slack/email/code) | ⬜ | Agent 1 |
| Extraction + entity resolution + contradiction detection | ⬜ | Agent 2 |
| Query brain: hybrid retrieval + `ask()` grounded + cited | ⬜ | Agent 3 |
| Exposure: MCP (streamable-HTTP) + FastAPI + CLI | ⬜ | Agent 4 |
| Infra/deploy: Docker, compose, Makefile, vhost | ⬜ | Agent 5 |
| Eval + golden ground truth + adversarial verify | ⬜ | Agent 6 |
