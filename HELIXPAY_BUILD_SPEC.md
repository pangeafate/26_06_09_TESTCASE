# HelixPay Ontology — Build Spec for Claude Code

This is a **build spec**, not prose to read for fun. Hand it to Claude Code. It is written to be executed as a **dynamic workflow** in the style Boris Cherny runs Claude Code: plan-first, a serial foundation that freezes the contracts, then **five worktree-isolated build agents in parallel plus a dedicated Eval & Ground-Truth agent**, an adversarial-verification pass, and a `/goal`-gated finish. Target: a working, deployed system in **~2-3 hours of multi-agent wall-clock**, inside the take-home's 4-6h budget.

The Eval agent is a different kind of agent than the five builders: it authors ground truth from the raw `data/` by inspection, so it depends on nothing the build slices produce and starts at the gate; and because it wrote neither the extraction nor the query code, it is the legitimate **author-independent grader** for the adversarial stage. It runs off the critical path and doubles as the verifier — it does not lengthen the build.

---

## Grading bar — read this first, every decision flows from it

The take-home tells us how it's graded. Most code will be LLM-written and they will **not** dock missing edge cases or a function that could be cleaner. What they read for is the part the model isn't reliable at yet:

1. **A thought-through architecture.**
2. **A project setup that actually runs** — ideally one command from a fresh clone.
3. **The conventions you put around the model** so it produces production-grade code instead of slop.

Plus: it must be **live in production, not local**; and `SOLUTION.md` must document the run, justify the architectural calls, and name what was left out *and why it's less important for the real product and less interesting for the exercise*.

Two consequences that override everything below:

- **Depth beats breadth.** A tight system that runs flawlessly with impeccable conventions scores higher than a sprawling one that half-works. When in doubt, cut scope, not polish.
- **The conventions are the deliverable.** `CLAUDE.md`, the frozen contracts, the prompt + structured-output discipline, and the verification harness are not scaffolding around the real work — they *are* the work being graded. In a parallel build they also keep the five agents consistent, so they earn their keep twice.

---

## 0. How to run this build

Paste the kickoff prompt (§10) into Claude Code. Ground rules:

- **Model / effort:** Opus 4.8, `/effort xhigh`, **auto mode on**. A parallel run freezes on a single permission prompt.
- **Plan first.** Claude enters plan mode, restates this plan, then executes. A broken run gets `/rewind`-ed and re-planned, not pushed forward.
- **Gate, then fan out.** The agents cannot start in parallel until the contracts are frozen, or they collide on shared types. So: **one serial gate (the orchestrator's Phase 0) → five parallel build agents + the Eval agent → integrate + adversarial verify.** This is fan-out-and-synthesize with an adversarial stage, where the Eval agent *is* the adversary.
- **Worktrees.** Each of the five runs in its own git worktree (`isolation: worktree`). File ownership is disjoint by construction (§6) — that is what makes parallel safe.
- **Verification ≠ author.** Each slice is checked by a separate verifier agent against §8. Kills self-preferential bias.
- **Finish what you start.** `/goal` gates completion: not done until `make demo` answers every eval question with citations and surfaces a real contradiction, and tests pass.

---

## 1. Goal, constraints, acceptance criteria

### Goal
Ingest `data/` (a messy multi-format snapshot of fictional B2B payments company **HelixPay**) into a clean, queryable **ontology about the organization**, and expose a **programmatic interface for an AI agent** to answer deep, cross-cutting questions with source attribution.

### Constraints
- **Agent-friendly, library-first.** The engine is a library (`ask()` and friends). CLI, HTTP, and MCP are thin adapters over it. Primary remote surface is an **MCP server over streamable-HTTP** (the consumer is an agent, and the grader works with Claude).
- **Deep questions, reasonable time.** Answers must handle hierarchy, staleness, aliases, contradictions, and carry source attribution. The ingest-time vs query-time split is a deliberate design call we own (see §2).
- **Moving target.** Ingestion is idempotent on content hash and connector-shaped, so adding live ingestion later is a new connector, not a rewrite.
- **Live in production.** We deploy to an existing VM (Docker + a TLS reverse proxy + DNS already pointing at it). `SOLUTION.md` opens with a real URL.
- **LLMs are deliberate.** Used at ingestion (extraction) and query (synthesis); the spec says when, where, and with what context.
- **Secrets via env only.** `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`, `DATABASE_URL`. Never hardcoded.

### Acceptance criteria
1. `make up && make ingest && make demo` works from a fresh clone with only env vars set.
2. Eval questions (§8) return answers that cite `source_uri` + `as_of`, surface contradictions rather than silently picking a side, resolve org hierarchy, and prefer fresh over stale (and say so).
3. MCP server exposes the §5 tools over HTTP and is callable by an agent at the live URL.
4. Re-running ingestion on unchanged `data/` is a no-op; changing one file re-ingests only what changed.
5. Deployed and reachable at the VM's domain; `SOLUTION.md` covers run + tradeoffs + scope cuts.

---

## 2. Architecture (the decisions, already debated)

**Thesis:** this is an *ontology-construction* task, not a RAG task. Naive "chunk → embed → vector search → LLM" fails exactly on hierarchy/staleness/aliases/contradictions. So we build a **temporal, provenance-carrying ontology** at ingest, with hybrid retrieval underneath it.

**Borrowed from Palantir's ontology, with one deliberate inversion.** Adopt object types + typed links + properties, mapped *from* sources with full provenance (never overwrite raw), and the "world model constrains the LLM" stance (agent reasons over governed facts, always cites). **Invert** the golden-record collapse: Palantir prevents contradictions upstream and stores one canonical value; we can't and shouldn't. Every property value is a **claim** — multiple conflicting values coexist, each with source + `as_of` + confidence — and **contradictions are first-class objects**. That is precisely what the task tests. Out of scope (name in SOLUTION.md): Palantir's kinetic layer (writeback/actions) and dynamic security — this is read-only QA over a static snapshot.

**Single Postgres, and be honest about why.** One store: `pgvector` for semantic search, native FTS for lexical (names, metric codes, numbers), recursive CTEs for hierarchy, plus the ontology and raw documents. The dataset is **small** (one company snapshot), so this is *not* a performance choice — pgvector at this scale is overkill on speed. It's chosen for the explicit live-in-production requirement, single-store operational simplicity (one thing to deploy, back up, reason about), and native FTS + CTEs. State exactly this in SOLUTION.md; a reviewer who notices the data is tiny will respect the honest framing. (If "live in production" weren't required, SQLite + FTS5 would be the bulletproof one-command choice — name it as the road not taken.)

**The deterministic backbone.** Two cheap moves de-risk the two flakiest LLM steps, built at the gate before any extraction:
- **Seed roster.** Parse `org-chart.md` (mid-April 2026) + `overview.md` into a canonical set of people/teams/links. Entity resolution then resolves messy mentions *against this fixed roster* instead of clustering blind. Makes the hierarchy backbone deterministic.
- **Metric vocabulary.** A small controlled vocabulary for the metrics that matter (ARR, churn, headcount, etc.), seeded from the Q1 financials and dashboards. Extraction maps raw predicates onto it. Without this, "ARR" and "annual recurring revenue" land as different predicates and contradiction detection silently no-ops.

**Layers:** ingestion/extraction → storage (one Postgres behind one `Repository`) → query/reasoning (`ask`) → exposure (library/CLI/HTTP/MCP).

---

## 3. Data model / schema (frozen at the gate)

`helixpay/db/schema.sql`. Sketch — implementer fills indexes/constraints. The gate also **seeds** `entities` + `links` from the roster, and loads the metric vocab.

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE documents (             -- raw provenance, content-addressed for idempotency
  id BIGSERIAL PRIMARY KEY,
  source_uri TEXT NOT NULL, source_type TEXT NOT NULL,  -- md|pdf|html|image|slack|email|code
  title TEXT, author TEXT, lang TEXT, as_of DATE,
  ingested_at TIMESTAMPTZ DEFAULT now(),
  content_hash TEXT NOT NULL UNIQUE, raw_text TEXT
);
CREATE TABLE chunks (
  id BIGSERIAL PRIMARY KEY, document_id BIGINT REFERENCES documents(id) ON DELETE CASCADE,
  ordinal INT, text TEXT NOT NULL, embedding VECTOR(1024), tsv TSVECTOR
);                                   -- HNSW/IVFFlat on embedding; GIN on tsv
CREATE TABLE entities (
  id BIGSERIAL PRIMARY KEY, canonical_name TEXT NOT NULL,
  entity_type TEXT NOT NULL,         -- person|team|customer|product|metric|other
  attributes JSONB DEFAULT '{}', seeded BOOLEAN DEFAULT false
);
CREATE TABLE entity_aliases (
  id BIGSERIAL PRIMARY KEY, entity_id BIGINT REFERENCES entities(id) ON DELETE CASCADE,
  alias TEXT NOT NULL, source_chunk_id BIGINT REFERENCES chunks(id)
);
CREATE TABLE metric_vocab (          -- controlled vocabulary; predicates normalize onto canonical_key
  canonical_key TEXT PRIMARY KEY, display_name TEXT, aliases TEXT[]
);
CREATE TABLE claims (                -- the claim/assertion model: conflicting values coexist
  id BIGSERIAL PRIMARY KEY, subject_entity_id BIGINT REFERENCES entities(id),
  predicate TEXT NOT NULL,           -- canonicalized against metric_vocab where applicable
  object_value TEXT, object_entity_id BIGINT REFERENCES entities(id),
  as_of DATE, confidence REAL, valid_from DATE, valid_to DATE,
  superseded_by BIGINT REFERENCES claims(id),
  source_chunk_id BIGINT REFERENCES chunks(id), document_id BIGINT REFERENCES documents(id)
);                                   -- index (subject_entity_id, predicate)
CREATE TABLE links (                 -- typed relations incl. org hierarchy (recursive CTE)
  id BIGSERIAL PRIMARY KEY,
  from_entity_id BIGINT REFERENCES entities(id), to_entity_id BIGINT REFERENCES entities(id),
  link_type TEXT NOT NULL,           -- reports_to|owns|member_of|mentions
  as_of DATE, valid_to DATE, confidence REAL, source_chunk_id BIGINT REFERENCES chunks(id)
);
CREATE TABLE contradictions (        -- first-class objects
  id BIGSERIAL PRIMARY KEY, subject_entity_id BIGINT REFERENCES entities(id), predicate TEXT,
  claim_a_id BIGINT REFERENCES claims(id), claim_b_id BIGINT REFERENCES claims(id),
  kind TEXT, note TEXT, detected_at TIMESTAMPTZ DEFAULT now()  -- value_conflict|temporal|source_disagreement
);
```

---

## 4. Interface contracts (frozen at the gate — what every agent codes against)

`helixpay/contracts/`. Everything imports these and never redefines them. Signatures matter more than bodies.

```python
# models.py
Document, Chunk, Entity, Claim, Link, Contradiction
Citation(source_uri, as_of, snippet, claim_id?, chunk_id?)
AnswerBundle(answer:str, citations:list[Citation], contradictions:list[Contradiction],
             as_of_coverage:dict, confidence:float)   # contradictions surfaced, never hidden

# connector.py  -- Agent 1 (loaders) implements this; one impl per format
class SourceConnector(Protocol):
    source_type: str
    def discover(self, root:str) -> list[str]: ...               # find files this connector owns
    def load(self, path:str) -> tuple[Document, list[Chunk]]: ... # normalize one file

# repository.py  -- Agents 2 & 3 code against this; one Postgres impl built at the gate
class Repository(Protocol):
    def upsert_document(doc) -> int            # no-op if content_hash exists (idempotency)
    def add_chunks(chunks, embeddings, tsv) -> list[int]
    def upsert_entity(e) -> int; def add_alias(entity_id, alias, src) -> None
    def resolve_entity(name, entity_type=None) -> Entity|None     # matches against seeded roster first
    def add_claim(c) -> int; def add_link(l) -> None; def add_contradiction(c) -> None
    def canonical_predicate(raw:str) -> str                       # via metric_vocab
    def search_semantic(qvec, k) -> list[(Chunk,float)]
    def search_lexical(q, k) -> list[(Chunk,float)]
    def get_claims(subject_id, predicate=None) -> list[Claim]
    def get_links(link_type=None) -> list[Link]
    def get_org_subtree(root_id=None, as_of=None) -> dict         # recursive CTE
    def get_contradictions(subject_id=None) -> list[Contradiction]
    def get_sources(claim_ids) -> list[Citation]

# query.py  -- Agent 4 codes against this (stub until Agent 3 lands)
class QueryEngine(Protocol):
    def ask(question) -> AnswerBundle
    def get_entity(name) -> dict                 # entity + claims + aliases
    def get_org_chart(as_of=None) -> dict
    def find_contradictions(topic=None) -> list[Contradiction]
```

---

## 5. The gate + five agents

### Gate — Phase 0 (orchestrator, serial, ~25 min, blocks the rest)
Builds the frozen shared layer everything depends on: repo scaffold, `db/schema.sql`, `contracts/**` (all four Protocols + models), the Postgres `Repository` impl, `config.py`, `CLAUDE.md`, `.claude/` (commands + verifier-agent stub), and a **minimal seeded query fixture** (a few hand-written rows so Agent 3 can build against a live DB). **Plus the deterministic backbone:** parse `org-chart.md` + `overview.md` → seed `entities`/`links` roster; load `metric_vocab` from financials + dashboards. The golden ground-truth set and the eval harness are **not** built here — they belong to Agent 6, which authors them independently. **Freezes when** contracts import cleanly, the schema applies, and the seed loads. Do not fan out before this.

### Agent 1 — Loaders / ingestion normalization
**Owns** `helixpay/ingest/loaders/**`, `tests/loaders/**`. One `SourceConnector` impl per format (md, pdf, html, image, slack, email, code) → `Document` + `Chunk`, plus chunking (~500-800 tokens, preserve speaker/section boundaries). HTML dashboards: extract the numbers **and** their as-of dates. JPEG charts: vision caption pass (deep figure extraction is stretch — degrade to caption). **Depends on:** contracts only. **Done when** each format parses the real files in `data/` and validates against the contract.

### Agent 2 — Extraction & ontology  *(longest pole, highest-value)*
**Owns** `helixpay/ingest/extract/**`, `resolve.py`, `contradict.py`, `prompts/`, `tests/ingest/**`. Per chunk, LLM emits `claims` + `relations` under a **strict structured-output schema** with a **validate-and-repair loop** (output validated against contracts; repaired or dropped, never trusted raw). Entity resolution maps mentions to the **seeded roster** (embeddings + normalization; LLM tie-break only for ambiguous cases; handle transliteration across the mixed languages). Predicates canonicalized via `metric_vocab`. Contradiction detection groups by `(subject, canonical_predicate)` with overlapping time windows → writes `contradictions`. Writes via `Repository`. Idempotent: unchanged `content_hash` short-circuits; a changed file supersedes prior claims via `valid_to`, never deletes. **Model:** Sonnet 4.6 for extraction (cheap, parallel at runtime). **Depends on:** contracts + Repository + the `Chunk` type (not Agent 1's code). **Done when** chunks populate entities/claims/links/contradictions and the conventions (prompts, repair loop, no-uncited-claims) are visible and tested.

### Agent 3 — Query brain (retrieval + graph + reasoning)
**Owns** `helixpay/query/**`, `tests/query/**`. Hybrid retrieval (`search_semantic` + `search_lexical` → reciprocal-rank fusion); recursive-CTE hierarchy/ownership with cycle guard and `as_of` filtering; temporal resolver (freshest wins, staleness flagged, `as_of_coverage` populated); contradiction surfacing; and `ask()` — a lightweight planner that routes {structured | retrieval | both}, gathers facts + chunks, and synthesizes grounded strictly in retrieved material with **every claim cited**. **Model:** Opus 4.8 for synthesis. **Depends on:** Repository (reads against a small seeded fixture DB, not real extracted data). **Done when** `ask(q)` returns a cited, time-aware `AnswerBundle` on the fixture.

### Agent 4 — Exposure
**Owns** `helixpay/mcp/**`, `helixpay/api/**`, `helixpay/cli.py`, `tests/api/**`. Thin adapters over the `QueryEngine` Protocol (mock until Agent 3 lands). **MCP server in streamable-HTTP transport** (hard requirement — stdio is local-only and would break the live-URL story), tools: `ask`, `get_entity`, `get_org_chart`, `find_contradictions`, `get_sources`, `search`, typed per object type. FastAPI: `POST /ask`, `GET /entity/{name}`, `GET /org-chart`, `GET /contradictions`, `GET /health`. CLI: `helixpay ask "..."`, `helixpay ingest ./data`. **Done when** MCP tools are callable over HTTP, `/health` is green, and the CLI answers.

### Agent 5 — Infra & deploy
**Owns** `deploy/**`, `Dockerfile`, `docker-compose.yml`, `Makefile`, `.env.example`, the reverse-proxy vhost (§9). Compose (app + pgvector), the one-command run, and the live-VM deploy. **Depends on:** CLI/compose entrypoint names (frozen at the gate). **Done when** `make up && make ingest && make demo` is green locally and the deploy is reachable at the domain. (`make demo` invokes Agent 6's harness.)

### Agent 6 — Eval & Ground-Truth *(dedicated verification agent, author-independent)*
**Owns** `eval/**`, `tests/golden/**`, `.claude/agents/verifier.md`. Runs in two phases.

*Phase A — at the gate, in parallel with everyone (depends only on contracts + the raw `data/`):* author the **golden ground-truth set** by hand-inspecting the raw files — a dozen-plus verified facts spread across every format: a couple from markdown, a PDF table figure, a dashboard number with its as-of date, a Slack thread, an interview Q&A, an org-chart reporting line. Each golden fact is `(subject, predicate, value, as_of, source_uri)`. Write `eval/questions.yaml` (the deep-question set, §8) and the harness skeleton (`eval/run.py`) against the contracts. Because this is derived from the data and not from any build slice's output, it is an independent oracle.

*Phase B — at integration:* run the **two-level autotest** (§8) — extraction precision/recall against the golden facts, then the answer checks against the deep questions — and act as the **adversarial verifier**: check each build slice against §1 + §8, file findings for the fixer, do not edit other agents' code. **Model:** Opus 4.8 (it's grading, not bulk extraction). **Done when** the harness runs end-to-end, reports extraction precision/recall and per-question pass/fail with latency, and the `/goal` condition is evaluable from its output.

---

## 6. Ownership & sequencing (disjoint by construction)

| Phase | Agent | Owns (writes only here) | Codes against |
|---|---|---|---|
| Gate (serial) | orchestrator | scaffold, `db/**`, `contracts/**`, `config.py`, `CLAUDE.md`, `.claude/**`, seed roster + metric_vocab, query fixture | — |
| Parallel | 1 Loaders | `ingest/loaders/**` | contracts |
| Parallel | 2 Extraction | `ingest/extract/**`, `resolve.py`, `contradict.py`, `prompts/` | contracts, Repository |
| Parallel | 3 Query brain | `query/**` | Repository (+ fixture DB) |
| Parallel | 4 Exposure | `mcp/**`, `api/**`, `cli.py` | `QueryEngine` Protocol (stub) |
| Parallel | 5 Infra/deploy | `deploy/**`, Docker/compose/Makefile, vhost | gate entrypoints |
| Parallel | 6 Eval/Ground-Truth | `eval/**`, `tests/golden/**`, `.claude/agents/verifier.md` | contracts + raw `data/` |

No two agents write the same file. Agents 1 and 2 meet only through the `Chunk` contract; 2 and 3 meet only through `Repository`; 4 builds against the `QueryEngine` stub; 6 derives everything from the raw data and the contracts, so it owes nothing to the builders and starts at the gate. **Critical path:** Gate → Agent 2 (extraction) → integration. Everyone else, including Eval, builds in parallel against the seeded fixture / raw data while extraction runs, so wall-clock ≈ gate + Agent 2 + integration. The Eval agent does not lengthen this — it works during the build and grades at the end. Don't add a *seventh* agent unless it shortens Agent 2.

---

## 7. CLAUDE.md (written at the gate, drop in repo root)

```md
# CLAUDE.md — HelixPay Ontology

## Stack & commands
- Python 3.12, uv. Postgres + pgvector. FastAPI. MCP Python SDK (streamable-HTTP).
- make up | ingest | demo | test | fmt. Run `make fmt && make test` before any PR.

## Conventions
- Cross-module types live in helixpay/contracts/. Never redefine them locally.
- All DB access goes through Repository. No raw SQL outside db/.
- Secrets only from env: ANTHROPIC_API_KEY, VOYAGE_API_KEY, DATABASE_URL. Never hardcode.
- Models: extraction = claude-sonnet-4-6; synthesis/ask = claude-opus-4-8; embeddings = voyage (1024d).
- Every LLM call uses a named prompt in prompts/ and a structured-output schema; validate output
  against contracts and repair-or-drop. No free-form trust.

## Ontology rules (the point of the project)
- Never collapse conflicting facts into one value. Store every value as a Claim (source + as_of + confidence).
- Contradictions are first-class rows, surfaced in answers, never silently resolved.
- Never delete superseded facts; set valid_to / superseded_by.
- Entity resolution matches against the seeded roster first. Predicates canonicalize via metric_vocab.
- ask() output must contain zero uncited claims.

## Gotchas (append every time Claude trips)
- pgvector needs CREATE EXTENSION vector; before migrations.
- MCP must run streamable-HTTP, not stdio, or it only works locally.
- HTML dashboards: capture the number AND its as-of date — that's where contradictions hide.
- Ingestion is idempotent on content_hash; re-running on unchanged data is a no-op.
```

Also create `.claude/commands/ingest.md`, `.claude/commands/verify.md` (`make test && make demo`), `.claude/agents/verifier.md` (`isolation: worktree`).

---

## 8. Verification & eval (owned and run by Agent 6, the #1 quality lever)

This whole section is **Agent 6's remit**. It is authored from the raw `data/`, independent of the build slices, which is what makes it a trustworthy oracle.

**Ground truth — `tests/golden/facts.yaml`.** A dozen-plus facts verified by eye from the raw files, one or more per format, each as `(subject, predicate, value, as_of, source_uri)`:

```yaml
- subject: "Head of Engineering"   # resolves to a roster entity
  predicate: reports_to
  value: "CEO"
  as_of: 2026-04-15
  source_uri: data/org-chart.md
- subject: ARR
  predicate: value
  value: "<the figure as printed>"
  as_of: 2026-03-31
  source_uri: data/dashboards/<file>.html        # plus a conflicting one from the board deck, on purpose
- subject: "<customer>"
  predicate: owned_by
  value: "<AE name>"
  as_of: 2026-04-21
  source_uri: data/email/<thread>.eml
# ... markdown, slack, interview, code-contributor facts likewise
```

**Deep questions — `eval/questions.yaml`** — exercise each failure mode:

```yaml
- q: "Who does the Head of Engineering report to, as of the latest org chart?"
  checks: [resolves_hierarchy, uses_freshest_as_of, cites_source]
- q: "What was HelixPay's ARR in Q1 2026?"
  checks: [surfaces_contradiction_if_sources_disagree, cites_source, states_as_of]
- q: "Summarize the CEO's priorities."   # CEO has no interview; pull from all-hands, board update, exec chat, email
  checks: [cross_document_synthesis, cites_multiple_sources]
- q: "Do the dashboards and the board deck disagree on any key metrics?"
  checks: [returns_contradictions, attributes_each_side]
- q: "List the customers mentioned and who owns each relationship."
  checks: [entity_resolution, alias_handling, cites_source]
```

**Two-level autotest — `eval/run.py`, wired into `make test` and `make demo`:**
1. *Extraction check* — after ingest, assert every golden fact exists as a claim/link with the right `source_uri` and `as_of`; report **precision/recall** over the golden set. Catches extraction regressions directly.
2. *Answer check* — run each deep question through `ask` and assert its `checks` (cites source, states `as_of`, resolves hierarchy, surfaces the planted contradiction); report per-question pass/fail + latency.

**Observability that feeds the check:** extraction logs every LLM call with its named prompt, inputs, structured output, and validate/repair outcome; the answer layer logs the plan route, what was retrieved, and which claims were cited. Agent 6 reads these to explain *why* a golden fact was missed (bad chunk, failed resolution, dropped on repair) rather than just that it was.

**Pass condition for `/goal`:** `make test` green, golden-set recall above the bar Agent 6 sets in `SOLUTION.md`, `make demo` answers all deep questions with `as_of`-stamped citations, and at least one answer surfaces a real planted contradiction.

**Adversarial stage (after integration):** Agent 6 — author of none of the build code — checks each slice against §1 + these checks, files findings, and one fixer resolves them; then `/simplify` for CLAUDE.md compliance.

---

## 9. Deploy to the VM (Docker + existing TLS reverse proxy + DNS already pointing)

Two compose services; the DB never exposed, the app reachable only via the existing proxy.

```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    environment: [POSTGRES_PASSWORD, POSTGRES_DB=helixpay]
    volumes: [pgdata:/var/lib/postgresql/data]
    healthcheck: ["CMD-SHELL", "pg_isready -U postgres"]
  app:
    build: .
    env_file: .env                       # ANTHROPIC_API_KEY, VOYAGE_API_KEY, DATABASE_URL
    depends_on: { db: { condition: service_healthy } }
    ports: ["127.0.0.1:8000:8000"]       # loopback only; the proxy reaches it
volumes: { pgdata: {} }
```

Binding to `127.0.0.1:8000` lets one compose file serve both worlds: locally the grader hits `localhost:8000`; on the VM the existing proxy forwards the subdomain to that loopback port. Add one vhost (use whichever proxy is installed):

```
# Caddy
helixpay.<domain> { reverse_proxy 127.0.0.1:8000 }
```
```nginx
# nginx (inside the existing TLS server block for the subdomain)
location / { proxy_pass http://127.0.0.1:8000; proxy_set_header Host $host; }
```

Secrets: a `.env` on the VM (chmod 600, not committed; `.env.example` ships). Ingest on the live box, once, after `docker compose up -d`:

```
docker compose run --rm app helixpay ingest ./data
```

Idempotent, so re-running is safe — that's also the **moving-target demo**: drop a new file, re-run, watch it converge. The MCP endpoint lives at `https://helixpay.<domain>/mcp` (streamable-HTTP), which an agent can connect to directly. The grader's local path stays `docker compose up`, unchanged.

---

## 10. Kickoff prompt (paste into Claude Code)

> Build the system in `HELIXPAY_BUILD_SPEC.md` as a **workflow**. `/effort xhigh`, auto mode.
>
> **Goal:** ingest `data/` into a temporal, provenance-carrying ontology in Postgres (pgvector + FTS) and expose a library + CLI + FastAPI + streamable-HTTP MCP so an agent can answer the deep questions in `eval/questions.yaml` with citations, hierarchy resolution, staleness handling, alias resolution, and surfaced contradictions. Deploy to the VM behind the existing TLS proxy.
>
> **Constraints:** single Postgres; claim/assertion model (never collapse conflicts); contradictions first-class; idempotent ingestion on content_hash; connector-shaped loaders; entity resolution against a seeded org-chart roster; predicates canonicalized via a seeded metric vocab; secrets via env only; every LLM call uses a named prompt + structured-output schema + validate-and-repair; zero uncited claims in `ask()`.
>
> **Execution:**
> 1. **Gate (do alone, first):** scaffold; write `db/schema.sql`; freeze `contracts/**` (SourceConnector, Repository, QueryEngine, models) + the Postgres Repository; `config.py`; `CLAUDE.md`; `.claude/` commands + verifier-agent stub; a minimal seeded query fixture; **seed entities/links from org-chart.md + overview.md and load metric_vocab from the financials/dashboards.** Do NOT author the golden set or eval harness here — that's Agent 6. Do not fan out until contracts import, schema applies, and the seed loads.
> 2. **Fan out — 5 build agents + 1 eval agent, each its own worktree, ownership per §6:** 1 = `ingest/loaders/**`; 2 = `ingest/extract` + resolve/contradict (longest pole); 3 = `query/**`; 4 = `mcp|api|cli` (mock QueryEngine until 3 lands); 5 = Docker/compose/Makefile/deploy/vhost; 6 = `eval/**` + `tests/golden/**`, authoring ground truth from the raw `data/` and the eval harness (starts immediately, depends only on contracts + data). No agent edits outside its column; each writes its own tests.
> 3. **Synthesize:** integrate, then **Agent 6 runs the adversarial verification** (it authored none of the build code) against §1 + §8 — extraction precision/recall on the golden set, then the answer checks — files findings, one fixer resolves, then `/simplify`.
> 4. `/goal`: not done until `make test` passes, `make demo` answers every eval question with citations and at least one surfaced contradiction, and the app is reachable at the domain.
>
> Verify end-to-end before reporting; tell me where you were uncertain.

---

## 11. Scope cuts (state in SOLUTION.md, each with the two-part justification)

- **Deep chart/figure extraction from JPEGs** — caption-level only. *Less important for the real product:* dashboards/HTML already carry the structured numbers; image figures are mostly redundant. *Less interesting for the exercise:* it's OCR plumbing, not architecture.
- **Kinetic layer (writeback/actions)** — omitted. *Real product:* nothing acts on the data yet; it's a read-only knowledge surface. *Exercise:* it's Palantir's differentiator but orthogonal to the ontology-from-mess problem being tested.
- **Row-level / multi-tenant security** — omitted. *Real product:* matters at multi-customer scale, not for a single snapshot. *Exercise:* pure access-control plumbing.
- **Live ingestion (file watchers, source APIs)** — not implemented, but the `SourceConnector` seam makes it a small add. *Real product:* needed eventually. *Exercise:* the architecture seam is the signal; the polling loop is mechanical.
- **Trained cross-encoder reranker** — RRF instead. *Real product:* a quality upgrade. *Exercise:* marginal at this corpus size; note the upgrade path.

---

### Why this is shaped for five build agents plus a dedicated Eval agent
Frozen contracts + a seeded deterministic backbone + disjoint file ownership = worktree agents that never collide and never re-derive the flaky parts. The gate carries the conventions the grader reads for; the five build the machinery around them. The Eval agent is deliberately separate: it authors ground truth from the raw data with no sight of the build code, so its golden set is an honest oracle and it can serve as the author-independent adversary at the end — the single highest-leverage defense against the laziness, self-preferential bias, and goal drift that would otherwise pass off a half-built system as done. It runs alongside the build and grades at integration, so it buys all of that without costing critical-path time.

---

## 12. Integration — the owned, gated phase (DEV_REINFORCE F-5)

Contract-first fan-out makes every slice independently testable, but it pushes
**all integration risk to a single post-merge moment**. In the first build every
slice read green while nothing had been proven end-to-end: query was validated on
the seeded fixture, exposure on a mock engine, eval's harness on a stub, and
extraction had never run on the real corpus. "All slices green" said nothing about
whether the wired system works. Integration must therefore be a *named phase with
an owner and a gate* — not a footnote in Agent 6's brief.

**Owner:** orchestrator + Agent 6 (the author-independent grader).

**Definition of done — `/goal` is met only when ALL hold against real keys + DB:**
1. The six branches merge with disjoint ownership; the one shared seam (parent
   package `__init__.py`, pre-created per §F-1) and the dependency union
   (`scripts/consolidate-deps.py` → `pyproject.toml`) are resolved.
2. `make up && make ingest && make demo` is green **from a fresh clone** with only
   env vars set.
3. Agent 6's two-level autotest (§8) reports extraction precision/recall over the
   golden set at or above the stated recall bar, every deep question cites
   `source_uri` + `as_of`, and ≥1 real planted contradiction is surfaced.
4. The deploy is reachable at the live URL; `/health` green; `/mcp` speaks
   streamable-HTTP.

**Orchestrator rule:** *slices green ≠ build done.* The integration gate is a
separate mandatory stage; do not report `/goal` met, or deploy as done, until it
passes. Where feasible, run one thin real end-to-end path (one document → ingest
→ ask) *during* the build so integration risk is sampled continuously rather than
discovered all at once at the most expensive moment.
