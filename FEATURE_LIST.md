---
status: living
last-reconciled: 2026-06-12
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

## Round 2 — post-gate hardening (recall + replay)

| Feature | Status | Source |
|---------|--------|--------|
| `$0` replay tier: record/replay extractor wrappers + `make ingest-record`/`replay` (`replay-tier`) | 🚧 | `helixpay/ingest/replay.py`, `Makefile` (SP_010) |
| Company entity resolution: seed `HelixPay` distinct from `HelixPay Brasil` (`recall-company-entity`) | 🚧 | `helixpay/seed/roster.py` (SP_010) |
| Project entities (`Project Confluence`, `CRM migration`) + `ga_target`/`completion_target` vocab (`recall-metric-vocab`) | 🚧 | `helixpay/seed/roster.py`, `metric_vocab.py` (SP_010) |
| Shared value normalization wired into contradiction detection (`recall-normalize`) | 🚧 | `helixpay/ingest/contradict.py` → `normalize.py` (SP_010) |
| Target-predicate temporal-slip contradiction — Confluence GA (`recall-target-contradiction`) | 🚧 | `helixpay/ingest/contradict.py` (SP_010) |
| Structured chart extraction: image vision pass transcribes per-series datapoints (actual vs plan), extractor emits one claim per region/period; image datapoints graded on the recall bar (`img-structured-caption`, `img-chart-extract-guidance`, `img-recall-bar-golden`) | 🚧 | `helixpay/ingest/loaders/image.py`, `prompts/extract_claims.md`, `test/golden/facts.yaml` (SP_021) |

## Round 3 — provenance surface + answer UX (query side)

| Feature | Status | Source |
|---------|--------|--------|
| Close the chunk-citation hole: `[S#]`-grounded sentences cite real chunk `Citation`s via `get_chunk_sources` (`chunk-citation-close`) | ✅ | `helixpay/query/synthesis.py`, `engine.py` (SP_012) |
| Link citations: relationship answers cite `[L#]` links via `get_link_sources` (`surface-link-citation`) | ✅ | `helixpay/query/synthesis.py`, `engine.py` (SP_012) |
| Consensus/dissent rollup: collapse N coexisting claims to one ranked consensus + explicit dissent (`consensus-dissent`) | ✅ | `helixpay/query/consensus.py` (SP_012) |
| Type contradictions (`value`/`temporal`/`source disagreement`/`relationship`) into the synthesis prompt, incl. link conflicts (`contradiction-typing`) | ✅ | `helixpay/query/contradictions.py`, `synthesis.py` (SP_012) |
| Verbatim-span citations: `Citation.snippet` quotes `Claim.evidence` (`verbatim-citations`) | ✅ | `helixpay/query/synthesis.py` (SP_012) |
