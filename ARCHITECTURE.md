---
status: living
last-reconciled: 2026-06-09
authoritative-for: [system-design, components]
---

# Architecture

Full design rationale: `HELIXPAY_BUILD_SPEC.md` §2. This file records what the
Phase 0 gate established.

## Thesis

This is an **ontology-construction** task, not a RAG task. Naive "chunk → embed →
vector search → LLM" fails on hierarchy, staleness, aliases, and contradictions. So
we build a **temporal, provenance-carrying ontology** at ingest, with hybrid
retrieval underneath it. Borrowed from Palantir's ontology (typed objects + links +
properties, full provenance, world-model-constrains-the-LLM) with one deliberate
inversion: we do **not** collapse to a golden record — every value is a `Claim` and
**contradictions are first-class objects**.

## Layers

```
ingestion/extraction  →  storage (one Postgres behind one Repository)  →  query/reasoning (ask)  →  exposure (lib/CLI/HTTP/MCP)
```

- **Storage:** a single Postgres (`pgvector` semantic + native FTS lexical +
  recursive CTEs for hierarchy). Chosen for the live-in-production requirement and
  single-store operational simplicity — not for performance (the corpus is tiny).
- **The Repository seam:** every component depends on the `Repository` Protocol;
  the one `PostgresRepository` impl confines all SQL to `helixpay/db/`.
- **Frozen contracts:** `helixpay/contracts/` holds the four Protocols + models that
  every build agent codes against. They are frozen at the gate so the parallel
  agents never collide on shared types.

## Deterministic backbone (de-risks the two flakiest LLM steps)

- **Seed roster** — `org-chart.md` + `overview.md` parsed into a canonical set of
  people/teams/links. Entity resolution matches messy mentions against this fixed
  roster (roster-first), keeping the planted name traps distinct (two Marias, two
  Tans) and making the hierarchy deterministic.
- **Metric vocabulary** — a controlled vocab (`metric_vocab`) so "ARR" and "annual
  recurring revenue" canonicalize to one predicate; without it, contradiction
  detection silently no-ops.

## Components built at the gate

| Component | File(s) | Role |
|-----------|---------|------|
| Contracts | `helixpay/contracts/**` | frozen models + Protocols |
| Schema | `helixpay/db/schema.sql` | 8-table ontology (see `DATA_SCHEMA.md`) |
| Repository | `helixpay/db/repository.py` | the one storage impl (idempotent, temporal) |
| Config | `helixpay/config.py` | env secrets + pinned models |
| Seed | `helixpay/seed/**` | roster + metric_vocab + query fixture |

## Out of scope (see `SOLUTION.md` when written)

Palantir's kinetic layer (writeback/actions); row-level/multi-tenant security; live
ingestion (the `SourceConnector` seam is the add-point); deep JPEG figure extraction
(caption-level); trained cross-encoder reranker (RRF instead).
