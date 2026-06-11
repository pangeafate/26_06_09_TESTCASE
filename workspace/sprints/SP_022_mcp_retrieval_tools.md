---
sprint_id: SP_022
tier: Foundational
features: []
user_stories:
  - "As an agent (ChatGPT/Claude) connected to the live MCP, I can `search` the corpus, `fetch` a hit's full text, list the source `get_sources` inventory, and enumerate entities by type — so corpus-scoped and entity-scoped questions ('what discussions did Wei Chen have recently', 'what countries are covered') are answerable without `ask` synthesis."
schema_touched: false
structure_touched: false
status: In Progress
isolation: branch-only
branch: sprint/SP_022-mcp-retrieval-tools
worktree: ""
agent_owner: "main (operator-directed)"
dependencies: [SP_005, SP_009, SP_016]
dev_dependencies: []
touches_paths:
  - helixpay/contracts/repository.py
  - helixpay/db/repository.py
  - helixpay/query/engine.py
  - helixpay/api/engine.py
  - helixpay/mcp/server.py
  - test/unit/query/test_engine.py
  - test/unit/query/fakes.py
  - test/unit/api/test_mcp.py
  - test/integration/db/test_repository_reads.py
  - workspace/sprints/SP_022_mcp_retrieval_tools.md
  - PROGRESS.md
  - CLAUDE.md
touches_checklist_items: [repo-get-chunk, repo-list-documents, repo-list-entities, engine-search, engine-fetch, engine-get-sources, engine-list-entities, mcp-fetch-tool, mcp-list-entities-tool, exposure-protocol-fetch-listentities]
---

# SP_022: MCP retrieval tools — search / fetch / get_sources / list_entities

## Sprint Goal

Make the live MCP serve the **retrieval primitives** a connected agent needs to answer
corpus- and entity-scoped questions directly, not only through `ask` synthesis. Today the
real `HelixQueryEngine` implements only the four frozen `QueryEngine` methods, so the MCP
`search` and `get_sources` tools return `{"available": false}` in production (only the
`MockQueryEngine` answers them). Two question archetypes motivate this:

1. **Entity-scoped recent activity** — *"what discussions did Wei Chen have recently?"* →
   `search("Wei Chen")` returns dated, provenance-bearing chunk hits; `fetch(id)` returns a
   hit's full text + `as_of`. The *agent* reconstructs recency from the payload metadata.
2. **Corpus-wide enumeration** — *"what countries are covered in the discussions?"* →
   `list_entities("other")` enumerates the region/org-unit roster (HelixPay Brasil, SEA, …)
   and `get_sources()` lists the document inventory. Top-k `search` alone cannot enumerate
   exhaustively; enumeration is the reliable path (operator chose "trio + entity enumeration").

End state: all of `search`, `fetch`, `get_sources`, `list_entities` are live MCP tools
returning `{"available": true, ...}` against the real engine, with `as_of` + `source_uri`
threaded through every payload so temporal/provenance reasoning works.

## Scope & boundaries

- **The frozen `QueryEngine` Protocol (`contracts/query.py`) is NOT touched.** The four
  retrieval surfaces are optional, discovered by `mcp.server._retrieval`'s `getattr`. They
  are declared on the **`ExposureEngine`** extension (`api/engine.py`), exactly as the
  existing `search`/`get_sources` already are.
- **The `Repository` Protocol IS extended** with three additive read methods. This is a
  frozen-contract extension, sanctioned through the lifecycle (precedent: SP_009 added
  `get_chunk_sources`/`get_link_sources`/`known_content_hashes`). The methods are pure
  reads, additive, and break no existing caller.
- **No schema change, no migration, no DB write path.** All three new repo methods are
  `SELECT`-only over existing tables (`chunks`, `documents`, `entities`). `schema_touched:
  false`.
- **No new LLM call, no embedding cost** beyond what `search` already does (one query
  embedding via the existing `hybrid_search`, identical to `ask`'s retrieval step). `fetch`
  / `get_sources` / `list_entities` are pure DB reads — **$0**.

## Design

### 1. `Repository` contract additions (`contracts/repository.py` + `db/repository.py`)

```python
def get_chunk(self, chunk_id: int) -> Optional[Chunk]: ...
def list_documents(self) -> list[Document]: ...
def list_entities(self, entity_type: Optional[str] = None) -> list[Entity]: ...
```

- `get_chunk` — `SELECT id, document_id, ordinal, text FROM chunks WHERE id = %s`; returns
  `_chunk_from_row(...)` or `None`. **Why not reuse `get_chunk_sources`?** That method
  *truncates* the text into a `snippet` (`_truncate_snippet`) and is document-joined;
  `fetch` needs the **full, untruncated** chunk text.
- `list_documents` — `SELECT id, source_uri, source_type, title, author, lang, as_of,
  ingested_at, content_hash, raw_text FROM documents ORDER BY as_of DESC NULLS LAST,
  id ASC`. A new `_document_from_row` helper builds the **full** `Document` (including
  `raw_text`). **(R-fix HIGH-3)** — the repo read returns an honest, complete model; payload
  trimming (dropping `raw_text`) happens at the **engine/wire boundary** in `get_sources()`,
  not by returning a half-populated `Document` from the contract. Corpus is 44 docs, so
  loading `raw_text` for an inventory is negligible.
- `list_entities` — `SELECT id, canonical_name, entity_type, attributes, seeded FROM
  entities [WHERE entity_type = %s] ORDER BY entity_type, canonical_name`; returns
  `_entity_from_row(...)`. `entity_type=None` lists all. Invalid/unknown type → empty list
  (no raise — consistent with `canonical_predicate`'s never-raise convention). Note: an
  unknown type and a known-but-empty type are both `[]` (indistinguishable); acceptable for
  the enumeration use case.

### 2. `ExposureEngine` additions (`api/engine.py`)

Extend the Protocol + `MockQueryEngine` with `fetch` and `list_entities` (`search`,
`get_sources` already declared):

```python
def fetch(self, id: str) -> dict: ...
def list_entities(self, entity_type: Optional[str] = None) -> list[dict]: ...
```

**(R-fix H3)** Also update `MockQueryEngine.search` so its canned dicts carry the **same
keys** the real engine emits (`id`/`title`/`url`/`snippet`/`score`/`source_as_of`/
`document_id`) — today the mock returns `{chunk_id,text,...}`, which would diverge from
production and let a shape regression pass tests. Add coherent canned `fetch`/`list_entities`
data (keep the planted-contradiction story intact). Update the `ExposureEngine` class
docstring ("two optional surfaces" → four).

### 3. `HelixQueryEngine` implementations (`query/engine.py`)

All four return JSON-friendly `dict`s (the MCP layer serializes; no model leakage).
**Two cross-cutting rules** applied wherever a date is emitted or provenance is joined:

- **(R-fix H2) date guard:** every `Optional[date]` → str is `d.isoformat() if d is not
  None else None`. Never a bare `.isoformat()` (documents/citations legitimately have
  `as_of=None`).
- **(R-fix C1) rank-preserving provenance join:** never zip `hybrid_search` output against
  `get_chunk_sources` output — the latter returns `ORDER BY ch.id ASC` and **omits** chunks
  whose document row is missing. Build `cites = {c.chunk_id: c for c in
  self.repo.get_chunk_sources([c.id for c, _ in hits])}` (one batched call), then iterate the
  hits **in RRF rank order** and `cites.get(chunk.id)` each, with a fallback when absent.

Methods:

- `search(query, k=10) -> list[dict]` — `hits = retrieval.hybrid_search(self.repo,
  self.embedder, query, k=k)`. Build `cites` per the rule above. For each `(chunk, score)`
  **in rank order**: `c = cites.get(chunk.id)`; `uri = c.source_uri if c else ""`;
  `as_of = c.as_of.isoformat() if (c and c.as_of) else None`. Result:
  `{"id": str(chunk.id), "title": uri, "url": uri, "snippet": _snippet(chunk.text),
  "score": score, "source_as_of": as_of, "document_id": chunk.document_id}`. **(R-fix
  layer-boundary)** `_snippet` is a small module-private helper **defined in
  `query/engine.py`** (clip to a local `_SNIPPET_MAX` + "…") — the engine MUST NOT import
  `db.repository._truncate_snippet` (that would make the query/capabilities layer depend on
  the db/infrastructure layer, violating the inward-dependency rule). The two truncations
  are independent by design (the db `_sources` reads keep their own copy). **(R-fix HIGH-1)**
  the date key is `source_as_of` — the *document's*
  date, NOT a per-fact reporting period (CLAUDE.md's documented as_of trap); for the
  "recent discussions" use case the document date is the right recency signal.
- `fetch(id) -> dict` — **(R-fix C2)** `try: cid = int(id)` / `except ValueError:` →
  not-found payload. `chunk = self.repo.get_chunk(cid)`; if `None` (or bad id) →
  `{"id": id, "title": "", "text": "", "url": "", "metadata": {"found": False}}`. Else join
  provenance via batched `get_chunk_sources([cid])` (index by id) → `{"id": id, "title":
  uri, "text": chunk.text, "url": uri, "metadata": {"source_as_of": iso|null, "document_id":
  ..., "ordinal": ..., "found": True}}`. `text` is the **full, untruncated** chunk text
  (contrast `search`'s snippet). **Deliberate divergence** from `get_org_chart` (which
  raises on malformed input): a `fetch` id is an opaque handle minted by `search`, so a bad
  id degrades to `found:False` rather than a tool error — documented, eyes-open.
- `get_sources() -> list[dict]` — body calls `self.repo.list_documents()` (**never**
  `self.repo.get_sources(...)`, the unrelated claim-provenance homonym — a one-line code
  comment pins this). Projects away `raw_text`: `[{"source_uri", "source_type", "title",
  "author", "as_of": iso|null}]`. **(MEDIUM-1 accepted eyes-open)** the engine method name
  matches the published tool name `get_sources`; the cross-layer homonym with
  `Repository.get_sources(claim_ids)` is disambiguated by `self` vs `self.repo` + the comment.
- `list_entities(entity_type=None) -> list[dict]` — `self.repo.list_entities(entity_type)` →
  `[{"id", "canonical_name", "entity_type", "seeded"}]`. **(R-fix L2)** `attributes` is
  intentionally excluded (use `get_entity` for per-entity detail).

### 4. MCP tools (`mcp/server.py`)

Register two new tools alongside the existing six; keep the `_retrieval` guarded-dispatch
wrapper for **consistency** with the already-shipped `search`/`get_sources` (whose tests
assert `payload["available"] is True`). A full MCP connector — Claude, or **ChatGPT in
Developer Mode** — reads `results` directly.

```python
@mcp.tool()
def fetch(id: str) -> dict:
    """Fetch the full text + provenance of a single chunk by id (from `search`)."""
    return _retrieval("fetch", id)

@mcp.tool()
def list_entities(entity_type: Optional[str] = None) -> dict:
    """Enumerate ontology entities, optionally by type (person/team/customer/product/
    metric/other). Use for corpus-wide 'what X are covered' questions."""
    return _retrieval("list_entities", entity_type)
```

**(R-fix MEDIUM-3 — scope decision, stated honestly):** result *items* carry OpenAI-friendly
`id`/`title`/`url`/`text` keys but remain inside the `{available, results}` envelope —
**directly usable by any full MCP client (Claude, ChatGPT Developer-Mode connector)**. It is
**not** the strict OpenAI *Deep Research* `search`→`{results:[{id,title,url}]}` / `fetch`→
bare `{id,title,text,url,metadata}` shape (that mode forbids the envelope). A
Deep-Research-specific unwrapping adapter is an explicit **follow-up**, not this sprint —
flagged so we don't overclaim. Update the module + `build_mcp` docstrings (six→eight tools).

## Testing Strategy

- **`test/unit/query/fakes.py`** — extend `FakeRepository` with `get_chunk`,
  `list_documents`, `list_entities` + registration helpers (`add_document`, `add_chunk_row`)
  backed by `documents: dict[int, Document]` / `chunks: dict[int, Chunk]` stores. Keep it
  `Repository`-Protocol-conformant **(R-fix M2)**. Additive; existing tests unaffected.
- **`test/unit/query/test_engine.py`** — new cases:
  - `search` returns id/url-bearing dicts **in descending RRF score order** — assert
    `results[i]["score"] >= results[i+1]["score"]` AND that provenance is correctly
    re-aligned by `chunk_id` even when chunk ids are NOT in score order **(R-fix C1/M4)**;
    `source_as_of` present when the chunk has a citation, `null` when not, and the
    no-citation hit falls back to `title="", url=""` **(R-fix H1)**.
  - `fetch` returns the **full untruncated** chunk text — assert it equals the stored chunk
    text AND is longer than `search`'s snippet for the same long chunk **(R-fix: truncation
    asymmetry)**; unknown (valid-int) id → `found: False`; non-int id (`"abc"`, `""`) →
    `found: False`, **no raise** **(R-fix C2)**.
  - `get_sources` returns the inventory with `as_of` ISO strings AND tolerates a document
    with `as_of=None` → `null`, no crash **(R-fix H2)**.
  - `list_entities` filters by type and lists-all on `None`; unknown type → `[]`;
    `attributes` absent from the dicts **(R-fix L2)**.
  - `HelixQueryEngine` still satisfies `QueryEngine` and now `ExposureEngine`; a typed
    `_: ExposureEngine = engine` assignment compiles (mypy) **(R-fix H2-arch)**.
- **`test/unit/api/test_mcp.py`** — extend `EXPECTED_TOOLS` to eight; assert `fetch` +
  `list_entities` registered and pass through to the extended `MockQueryEngine`; assert the
  mock `search` now emits the new key shape (`id`/`title`/`url`/`source_as_of`) **(R-fix
  H3)**; keep + extend the degradation test (a `CoreOnly` engine → `available: false` for
  all four retrieval tools).
- **`test/integration/db/test_repository_reads.py`** (`db`-marked, auto-skips without
  `DATABASE_URL`) — round-trip: upsert a document + chunks + entities, then `get_chunk`
  (full text + miss→`None`), `list_documents` (assert `ORDER BY as_of DESC NULLS LAST`
  explicitly with two dated docs **(R-fix M5)**; `raw_text` IS populated on the model),
  `list_entities` (filtered + all). Plus a typed `_: Repository = repo` conformance check
  **(R-fix H2-arch)**.

## Success Criteria

- All four retrieval tools (`search`/`fetch`/`get_sources`/`list_entities`) return
  `{"available": true, ...}` against the real `HelixQueryEngine` (not just the mock); a
  `QueryEngine`-only engine still degrades to `{"available": false}`.
- `search` results stay in RRF rank order with provenance re-aligned by chunk id; `fetch`
  returns full untruncated text and degrades (`found:false`) on a bad/absent id without
  raising; every emitted date is `source_as_of` (the document date), `None`-guarded.
- The frozen `QueryEngine` Protocol is untouched; the three new `Repository` reads are
  additive and pure-read; no schema change.
- Green bar: full unit suite + the new unit tests pass, the 4 db-integration tests pass
  against pgvector pg16, `mypy` clean, all validators PASS.
- Live: after deploy, `scripts/verify_mcp.py` lists eight tools and `list_entities('other')`
  + `search` return real results over the seeded backbone.

## Reviews

### Pre-Implementation Review

Foundational ⇒ ≥2 independent iterations (per `practices/GL-SELF-CRITIQUE.md`).

- **Iteration 1** — architect-reviewer, plan-as-written, adversarial; 0 CRITICAL, 3 HIGH + 4 MEDIUM + 3 LOW, REQUEST-CHANGES — all folded (HIGH-1 doc `as_of`≠fact period → renamed payload key `source_as_of`; HIGH-3 lossy `Document` → repo returns full model, trim at engine boundary; MEDIUM-3 `{available,results}` overclaim removed; HIGH-2/MEDIUM-1/2/4 conformance test + homonym comment + batched join + malformed-id contract). Files reviewed: SP_022_mcp_retrieval_tools.md, contracts/repository.py, contracts/query.py, contracts/models.py, api/engine.py, query/engine.py, db/repository.py, query/retrieval.py, mcp/server.py.
- **Iteration 2** — code-reviewer, plan-as-written, adversarial; 2 CRITICAL + 3 HIGH + 5 MEDIUM + 3 LOW, REQUEST-CHANGES — all folded (CRITICAL C1 RRF rank order destroyed by zipping `get_chunk_sources` [`ORDER BY ch.id`] → mandate `{chunk_id: Citation}` dict + iterate in rank order; CRITICAL C2 unguarded `int(id)` → `try/except ValueError`→`found:False`; HIGH H1 missing-citation fallback, H2 uniform `.isoformat()`-or-`None`, H3 mock/real key parity). Files reviewed: SP_022_mcp_retrieval_tools.md, query/engine.py, query/retrieval.py, db/repository.py, contracts/models.py, contracts/repository.py, api/engine.py, mcp/server.py, test/unit/query/fakes.py, test/unit/query/test_engine.py, test/unit/api/test_mcp.py.
- **Iteration 3 (confirmation)** — code-reviewer, re-review of the revised plan; all 7 prior CRITICAL/HIGH **CONFIRMED closed**, 1 NEW HIGH (layer-boundary: `search` snippet truncation must not import `db.repository._truncate_snippet` → resolved with a query-layer `_snippet`), folded → **0 CRITICAL / 0 HIGH, APPROVE** (hard-stop floor not reached). Files reviewed: SP_022_mcp_retrieval_tools.md, db/repository.py, query/engine.py, query/retrieval.py.

### Post-Implementation Review

Foundational ⇒ ≥2 independent iterations; plan-blind (Rule 5 — reviewer sees only code + tests).

- **Iteration 1** — code-reviewer, plan-blind over the diff; 0 CRITICAL, 2 HIGH + 1 MEDIUM + 4 LOW, APPROVE-WITH-NITS — folded (HIGH-1 `search` emitted `"id":"None"` for an `id=None` chunk [production-unreachable, `FakeRepository` gap] → skip `id is None` + regression test; HIGH-2 `fetch` dict-vs-list `results` asymmetry documented in `_retrieval`; LOWs: k-truncation test, mock `document_id` explicit, stale module docstring). Files reviewed: contracts/repository.py, db/repository.py, query/engine.py, api/engine.py, mcp/server.py, test/unit/query/test_engine.py, test/unit/query/fakes.py, test/unit/api/test_mcp.py, test/integration/db/test_repository_reads.py.
- **Iteration 2** — architect-reviewer, plan-blind, confirmation perspective; 0 CRITICAL / 0 HIGH, APPROVE-WITH-NITS — frozen `QueryEngine` confirmed unchanged, `ExposureEngine`+getattr seam sound, no SQL leak (query→db), low blast radius. MEDIUM-2 (`fetch` miss-metadata key asymmetry → `KeyError` risk) **fixed**: miss payload now carries the stable `_MISS_META` key set (None-valued). MEDIUM-1 (`get_sources` cross-layer homonym) accepted eyes-open (comment + tests); LOW (`_SNIPPET_MAX` duplicated across layers) noted, deliberate. Files reviewed: contracts/query.py, contracts/repository.py, db/repository.py, query/engine.py, api/engine.py, mcp/server.py.

**Verification after folds:** 622 unit passed / 1 db-skipped, **4/4 DB integration passed against
pgvector pg16** (real SQL: `get_chunk` full-text + miss, `list_documents` ordering + `raw_text`,
`list_entities` filter), mypy clean (71 files), 11/11 validators PASS.

## Documentation & Deploy

- Reconcile: `PROGRESS.md` (active sprint + history), `CLAUDE.md` (MCP tool list /
  retrieval-surface convention, any gotcha), and the published MCP tool list in
  SOLUTION/README if it enumerates tools.
- Deploy: push → CI `Deploy to Production`; `scripts/verify_mcp.py` must list the eight
  tools live; spot-call `list_entities("other")` and `search` against the live `/mcp`.
