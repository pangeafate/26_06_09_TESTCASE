# Project Context

## What This Project Does

HelixPay Ontology ingests `data/` — a messy, multi-format snapshot of a fictional
B2B payments company — into a clean, temporal, provenance-carrying **ontology** in
Postgres (pgvector + native FTS), and exposes a **programmatic interface for an AI
agent** (library + CLI + FastAPI + streamable-HTTP MCP) to answer deep, cross-cutting
questions with source attribution: org hierarchy, staleness, aliases, and
first-class contradictions.

The build is executed as a **dynamic multi-agent workflow** (one serial gate →
five worktree-isolated build agents + one author-independent Eval agent →
adversarial verification), per `HELIXPAY_BUILD_SPEC.md`.

## Agent's Role

The coding agent owns the full seven-stage lifecycle for each slice: plan, review,
implement (TDD), plan-blind review, document, deploy, and behavioral closure. It
operates within DEV_RULES governance — frozen contracts, disjoint file ownership,
isolated review — and may act autonomously on workspace/docs/tooling but runs the
full lifecycle for production code, schema, integrations, and new capabilities.

## In Scope

- Idempotent, connector-shaped ingestion of `data/` (md, pdf, html, image, slack, email, code)
- Temporal claim/assertion ontology: conflicting values coexist; contradictions are first-class
- Hybrid retrieval (pgvector semantic + FTS lexical + recursive-CTE hierarchy) and grounded `ask()`
- Exposure surfaces: library, CLI, FastAPI, streamable-HTTP MCP server
- Author-independent eval: golden ground-truth set + two-level autotest
- Live production deploy to the VM behind the existing TLS reverse proxy

## Out of Scope

- Palantir's kinetic layer (writeback/actions) — read-only QA over a static snapshot
- Row-level / multi-tenant security — single-company snapshot
- Live ingestion (file watchers, source APIs) — `SourceConnector` seam left as the add-point
- Deep chart/figure extraction from JPEGs — caption-level only
- Trained cross-encoder reranker — RRF instead at this corpus size

(Each scope cut is justified twice — real-product and exercise — in `SOLUTION.md`.)

## Key Stakeholders

| Stakeholder | Role | Interaction Pattern |
|-------------|------|---------------------|
| Grader / reviewer | Evaluates architecture, runnability, conventions | Reads `SOLUTION.md`, runs `make up && make ingest && make demo`, hits the live URL |
| AI agent consumer | Primary runtime client | Connects to the streamable-HTTP MCP endpoint and calls `ask`/`get_entity`/`get_org_chart`/`find_contradictions` |
| Operator (deploy) | Owns the VM + TLS proxy + DNS | Runs compose, ingests once on the live box, watches CI |

## Deployment

- Repository: https://github.com/pangeafate/26_06_09_TESTCASE
- Live surface (target): `https://helixpay.<domain>/` with MCP at `/mcp` (streamable-HTTP)
- Secrets via env only: `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`, `DATABASE_URL`
