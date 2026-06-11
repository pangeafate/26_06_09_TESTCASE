# SOLUTION.md — HelixPay Ontology

A system that ingests HelixPay's scattered company data (markdown, PDF, HTML
dashboards, Slack, email, interviews, org chart, code analysis) into a **temporal,
provenance-carrying ontology** in Postgres + pgvector, and exposes a **programmatic
interface built for an AI agent to call** — MCP (streamable-HTTP), REST, and a CLI —
that answers deep, cross-dataset questions with citations, time-awareness, and
first-class contradictions.

---

## 1. Single-command execution

Prerequisites: Docker (running) and a `.env` file (copy `.env.example` → `.env`,
fill in the three secrets). Then:

```bash
make up        # build image, start pgvector + app, wait for health, migrate + seed
make ingest    # ingest ./data into the ontology (LLM extraction + embeddings)
make demo      # run the eval harness (golden recall + deep-question checks)
```

Ask a question directly once ingested:

```bash
docker compose run --rm app helixpay ask "Who is the Head of Engineering and when did that become true?"
# or hit the agent surfaces:
#   REST:  POST http://127.0.0.1:8000/ask   {"question": "..."}
#   MCP:   streamable-HTTP at /mcp  (12 tools: ask, get_entity, get_org_chart,
#                                    find_contradictions, get_sources, search,
#                                    fetch, list_entities, get_timeline,
#                                    get_relationships, list_metrics,
#                                    get_claims_by_predicate)
```

Secrets are read **only** from the environment via `helixpay.config`
(`ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`, `DATABASE_URL`); `.env` is gitignored and
never committed. `make test` runs the suite; DB-marked tests auto-skip without
`DATABASE_URL`.

---

## 2. Architecture & key decisions

### Shape

```
ingest:  discover → load (per-format SourceConnector) → chunk → embed (Voyage)
         → LLM extract (Claude) → resolve entities → canonicalize predicates
         → persist claims/links via Repository → detect contradictions
query:   plan route → hybrid retrieve (semantic + lexical RRF) + graph + temporal
         → synthesize a grounded, cited answer (Claude) → enforce zero-uncited
         → AnswerBundle{answer, citations, contradictions, as_of_coverage}
expose:  one ASGI app → REST + streamable-HTTP MCP (one port) + a CLI
```

### Decisions and the reasoning behind them

- **Every value is a `Claim`, never a cell.** A claim carries `(source, as_of,
  confidence)`. Conflicting claims **coexist** — we never collapse or overwrite.
  This is the core bet: a company's data *is* contradictory across formats and
  time, so the data model has to represent disagreement natively rather than pick
  a winner.
- **Contradictions are first-class rows — detected at ingest, exposed at query.**
  Detection needs the global view (both sides present), so it runs once at ingest
  and materializes `contradictions` rows; the query layer *reads* them into
  `AnswerBundle.contradictions` (present-and-empty, never hidden) and the
  `find_contradictions` MCP tool. The query layer deliberately does **not**
  LLM-invent contradictions — that keeps answers honest (a false contradiction is
  a graded failure).
- **Temporal by construction.** Facts carry `as_of`; superseded facts are marked
  `valid_to`/`superseded_by`, **never deleted**. "Freshest wins" is a query-time
  ordering, not a destructive update — so history is queryable.
- **All DB access goes through a `Repository` Protocol; one Postgres + pgvector
  implementation.** Hybrid retrieval (pgvector cosine + a DB-generated `tsv`
  lexical column, fused by reciprocal-rank fusion) lives behind it. No raw SQL
  escapes `helixpay/db/`. Swapping the store or the retrieval strategy is a
  contained change.
- **Frozen contracts (`helixpay/contracts/`) as the seam.** Models + four Protocols
  (`SourceConnector`, `Repository`, `QueryEngine`, embed/synthesis seams) are the
  only cross-module types. This is what let the system be built as independent
  slices and integrated without forks (the contracts are byte-identical across
  every slice).
- **Production conventions around model outputs.** Every LLM call uses a **named
  prompt** (`prompts/`, versioned as data — no inline prompt strings) plus a
  **structured-output schema** with **validate-and-repair-or-drop**: one repair
  attempt, then the malformed item is dropped and logged. No free-form trust. In
  this run that discipline rejected **560 of ~2160 extracted items (~26%)** as
  schema-invalid — a feature, not a bug.
- **Agent-first interface.** MCP over **streamable-HTTP** (not stdio, which is
  local-only) is the primary surface so a remote agent can call it; REST and CLI
  are the same engine behind thin adapters (`get_engine()` DI seam), so adding a
  human UI later is a small change, not a rewrite.

---

## 3. Honest results — eval baseline

`make demo` runs a two-level, author-independent golden harness.

```
LEVEL 1 — extraction recall:  27% (4/15)   golden-precision 100%   [found 4, missing 11]
LEVEL 2 — deep questions:     6/6 fail at least one gating check
/goal verdict:                RED — recall 27% < 80% bar
```

**This is a truthful baseline of a system whose machinery works but whose
extraction tuning is incomplete.** The failures cluster into three diagnosable
root causes, not scattered noise:

1. **The company entity doesn't resolve (≈6 of 11 misses).** The seed roster has
   63 people/teams but not "HelixPay" itself, so company-level metrics (revenue,
   runway, headcount, NPS, net-new-merchants) fail to attach. Seeding the company
   entity alone lifts recall ~27% → ~67%.
2. **Predicate canonicalization gaps.** The Confluence GA dates *were* extracted
   but under free-text predicates, so they neither match the golden key
   (`ga_target`) nor align as two sides of the **planted contradiction** — which
   therefore never materialized. `metric_vocab` needs the relevant synonyms.
3. **Contradiction over-firing on value normalization.** `'18 months'` vs
   `'eighteen months'`, `'SGD 14.2M'` vs `'SGD 14.2 million'` were flagged as
   conflicts. `normalize_value` must collapse numeric/word/unit formatting before
   comparison; this also causes one false revenue contradiction that fails the
   `no_false_contradiction` check.

**What already works:** entity-link facts from structured sources (email
ownership, org-chart reporting lines) pass; on the answer side, `cites_source`,
`states_as_of`, and `uses_freshest_as_of` pass on multiple questions — synthesis,
citation enforcement, and temporal ordering are functioning. The bottleneck is
**upstream (resolution / canonicalization / normalization), not retrieval.**

Ingest produced: **44 documents, 100 chunks, 1604 claims, 367 entities, 256
links, 17 contradictions.**

---

## 4. Unimplemented / next, with rationale

Prioritized by leverage against the baseline above:

- **Seed the company entity + alias map (highest leverage).** ~6 facts, ~40
  recall points. Small change to the seed roster.
- **Extend `metric_vocab` predicate canonicalization** (GA/launch dates, cutover
  targets, contributor, company revenue). Materializes the planted contradiction
  and several facts.
- **Robust `normalize_value`** (numeric words, unit/currency suffixes, tilde/approx)
  to kill false contradictions.
- **A reranker is deliberately *not* next.** The baseline shows retrieval ranking
  is not the bottleneck — adding a cross-encoder now would polish the wrong stage.
  Revisit only after resolution/canonicalization land and recall is retrieval-bound.
- **Cost / performance.** Extraction is sequential and LLM-bound (this run: ~60 min,
  ~$6 one-time — dense, fact-rich corpus emitting near the output cap, plus a
  gleaning pass). Concurrent per-document extraction and **prompt-caching the
  static system prompt** would cut both materially. Idempotent on `content_hash`,
  so it is a one-time cost.
- **Agentic extraction via MCP (future direction).** Today extraction is a
  deterministic batch pipeline and MCP is query/read-only. Letting an agent drive
  extraction through *guarded* MCP write-tools (that enforce resolve-first,
  canonicalize, supersede-not-delete, contradiction-as-row at the tool boundary)
  is a natural evolution — but it is a larger build than this task requires, and
  the batch pipeline is the right reference oracle to grade it against.

### Scope note

This implementation is intentionally fuller than a 4–6h sketch on the
infrastructure and conventions axes (Docker deploy, contracts, validate-and-drop,
a real eval harness) because those are the evaluation focus. The honest gap is the
last extraction-tuning mile (the three root causes above), which the harness
measures precisely — and which is the first thing I would close next.
