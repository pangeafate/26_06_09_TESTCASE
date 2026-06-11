---
sprint_id: SP_023
tier: Foundational
features: []
user_stories:
  - "As an agent connected to the live MCP, I can read the *history* of a fact (`get_timeline`), traverse an entity's relationships beyond the org chart (`get_relationships`), discover the queryable metric vocabulary (`list_metrics`), and compare one predicate across entities (`get_claims_by_predicate`) — so temporal, graph, vocabulary-discovery and cross-entity questions are answerable without `ask` synthesis."
schema_touched: false
structure_touched: false
status: Complete
isolation: branch-only
branch: sprint/SP_023-graph-temporal-tools
worktree: ""
agent_owner: "main (operator-directed)"
dependencies: [SP_005, SP_009, SP_022]
dev_dependencies: []
touches_paths:
  - helixpay/contracts/models.py
  - helixpay/contracts/__init__.py
  - helixpay/contracts/repository.py
  - helixpay/db/repository.py
  - helixpay/query/engine.py
  - helixpay/api/engine.py
  - helixpay/mcp/server.py
  - test/unit/query/test_engine.py
  - test/unit/query/fakes.py
  - test/unit/api/test_mcp.py
  - test/integration/db/test_repository_reads.py
  - workspace/sprints/SP_023_graph_temporal_tools.md
  - CLAUDE.md
touches_checklist_items: [model-metricvocab, repo-get-links-to-entity, repo-list-metrics, repo-get-claims-by-predicate, engine-get-timeline, engine-get-relationships, engine-list-metrics, engine-get-claims-by-predicate, mcp-get-timeline-tool, mcp-get-relationships-tool, mcp-list-metrics-tool, mcp-get-claims-by-predicate-tool, exposure-protocol-four-surfaces]
---

# SP_023: Graph & temporal MCP tools — get_timeline / get_relationships / list_metrics / get_claims_by_predicate

## Sprint Goal

Expose, through the MCP surface, four capabilities the ontology *has in the data* but does
not currently surface to a connected agent. SP_022 added retrieval primitives
(`search`/`fetch`/`get_sources`/`list_entities`); this sprint adds the **ontology-shaped**
reads that distinguish HelixPay from a plain RAG store:

1. **Temporal history of a fact** — the ontology versions facts (`as_of`, `valid_from`,
   `valid_to`, `superseded_by`); facts are never overwritten. Today that signature feature
   is invisible over MCP. `get_timeline(entity, predicate)` returns the chronological claim
   history for a subject+predicate, exposing the supersession chain and conflicting coexisting
   values, each cited and `as_of`-stamped.
2. **Graph traversal beyond the org chart** — `get_org_chart` covers only `reports_to`. The
   link model also carries `owns`, `member_of`, `dotted_line_to`, `mentions`, none of them
   reachable. `get_relationships(entity, link_type?)` returns an entity's links in **both
   directions** (outgoing + incoming) so "who owns X", "who is on team Z", "who is connected
   to W" are answerable.
3. **Vocabulary discovery** — an agent cannot enumerate the metrics it may ask about.
   `list_metrics()` enumerates `metric_vocab` (canonical key + display name + aliases).
4. **Cross-entity comparison by predicate** — `get_claims` is single-subject and unexposed.
   `get_claims_by_predicate(predicate)` returns every claim whose **canonicalized** predicate
   matches, across all subjects, so "compare revenue across regions/quarters" is answerable.

End state: all four are live MCP tools returning `{"available": true, ...}` against the real
`HelixQueryEngine`, with `as_of`/`source_uri` threaded through every payload, and the planted
contradiction observable through the temporal and cross-entity views.

## Scope & boundaries

- **The frozen `QueryEngine` Protocol (`contracts/query.py`) is NOT touched.** All four new
  surfaces are optional, discovered by `mcp.server._retrieval`'s `getattr`, declared on the
  **`ExposureEngine`** extension (`api/engine.py`) — identical mechanism to SP_022's four.
- **The `Repository` Protocol IS extended** — one additive parameter and two additive read
  methods. This is a sanctioned frozen-contract extension (precedent: SP_009 added
  `get_chunk_sources`/`get_link_sources`; SP_022 added `get_chunk`/`list_documents`/
  `list_entities`). All are pure reads and break no existing caller.
- **One additive contract model** — `MetricVocab` (a previously-unmodeled table). This is a
  **new** type, not a fork/redefinition of a frozen one, so it is consistent with the "don't
  fork the type" rule (the four Protocols + existing models stay byte-identical).
- **No schema change, no migration, no DB write path.** Every new repo read is `SELECT`-only
  over existing tables (`claims`, `links`, `metric_vocab`, `entities`). `schema_touched:
  false`, `structure_touched: false`.
- **No new LLM call, no embedding cost — $0.** All four tools are pure DB reads (no
  `hybrid_search`, no synthesis). Cheaper than SP_022's `search`.
- **Reuse over new substrate (Pre-Feature Discipline):** `get_timeline` and
  `get_relationships` are built on *existing* reads (`get_claims`, `get_links`,
  `get_link_sources`, `get_sources`, `list_entities`) — only `get_links` gains one parameter
  for the incoming direction. New repo reads are added **only** where none fit (`list_metrics`,
  `get_claims_by_predicate`).

## Design

### 1. `MetricVocab` contract model (`contracts/models.py`)

```python
class MetricVocab(BaseModel):
    """A controlled-vocabulary metric (the metric_vocab table). New additive model."""
    canonical_key: str
    display_name: Optional[str] = None
    aliases: list[str] = Field(default_factory=list)
```

Added to `models.__all__` **and** re-exported from the `helixpay/contracts/__init__.py`
package (import line + `__all__` entry) — every cross-module type is imported as
`from helixpay.contracts import MetricVocab`, so omitting the package re-export is a hard
`ImportError` at startup (Stage-3 C1). Mirrors how `Document`/`Entity` model their tables; the
`seed` layer may later reuse it (currently `upsert_metric` takes loose args — out of scope to
change; deferred-reconciliation follow-up).

### 2. `Repository` contract additions (`contracts/repository.py` + `db/repository.py`)

```python
def get_links(self, link_type=None, from_entity_id=None, to_entity_id=None) -> list[Link]: ...
def list_metrics(self) -> list[MetricVocab]: ...
def get_claims_by_predicate(self, predicate: str, subject_id: Optional[int] = None) -> list[Claim]: ...
```

- **`get_links` gains `to_entity_id`** (appended → keyword- and positionally-backward-
  compatible, exactly as `from_entity_id` was appended in SP_009). When set, filters
  `to_entity_id = %s`; if both `from_entity_id` and `to_entity_id` are given they AND together
  (a legitimate "edge from A to B" query — no precondition that only one is set). This is what
  makes **incoming** edges ("who reports to / owns / is member_of X") reachable without a second
  method. **The Protocol docstring is updated** to document `to_entity_id` symmetrically with
  `from_entity_id` and note "appended SP_023" (Stage-3 MEDIUM-4/L1), and the `FakeRepository`
  gains the param.
- **`list_metrics`** — `SELECT canonical_key, display_name, aliases FROM metric_vocab ORDER BY
  canonical_key ASC` → `[MetricVocab(...)]`. Empty table → `[]`.
- **`get_claims_by_predicate(predicate, subject_id=None)`** — the only non-trivial read. Stored
  predicates may be **raw or period-qualified** ("Q1 2026 revenue"), because canonicalization
  happens on *read* (consensus/contradiction paths), NOT on write. So an exact `predicate = %s`
  match would silently miss most rows. The match is therefore done in the **db layer** (where
  the vocab join + the period-strip regex already live):
  1. `key = self.canonical_predicate(predicate)` (handles alias + leading-period-qualifier).
  2. Build the lowercased match set: `{key, predicate}` **∪ the canonical key's aliases**,
     fetched with `SELECT aliases FROM metric_vocab WHERE lower(canonical_key) = lower(%s)`
     (Stage-3 H2 — without the alias fetch a claim literally stored `"arr"` is invisible to
     `get_claims_by_predicate("revenue")`). The set is passed to SQL as a **`sorted(list)`** —
     a Python `set` is not a valid psycopg `ANY(%s)` param (Stage-3 H3).
  3. SQL: match `lower(predicate) = ANY(%s)` **OR** the leading-period-stripped
     `regexp_replace(lower(predicate), '^((q[1-4]|h[12]|fy|20[0-9]{2})[[:space:]/-]+)+', '')
     = ANY(%s)`. **The separator class is `+` (one-or-more), NOT `*`** (Stage-3 H1): POSIX ERE
     has no `\b`, so `*` would over-strip a *concatenated* token ("fy2026 ebitda" → "ebitda",
     "2026revenue" → "revenue"), diverging from Python's `\b`-anchored `_strip_period_qualifier`
     and collapsing distinct predicates. Requiring ≥1 separator reproduces the boundary for
     every real period-qualified predicate ("Q1 2026 revenue" → "revenue") while refusing to
     split a glued token. `ORDER BY subject_entity_id ASC NULLS LAST, as_of DESC NULLS LAST,
     id ASC`. When `subject_id` is given, `AND subject_entity_id = %s` is appended.
  A **distinct** suffix ("revenue vs plan") still stays its own predicate — only an exact
  post-strip set hit matches (mirrors `canonical_predicate`'s documented behavior, CLAUDE.md).
  Unknown predicate (not in vocab) → set is just `{raw}` → exact/period-strip match on that
  literal (never raises). Returns **all** matching claims incl. superseded ones (each carries
  `superseded_by`/`valid_to` so the consumer sees the version state — the ontology never
  collapses). The optional `subject_id` lets `get_timeline` reuse this one matching path
  (Stage-3 M1/MEDIUM-3 — no per-claim N+1 canonicalization, and the two tools are guaranteed to
  agree on what "predicate X" means).

### 3. `ExposureEngine` surfaces (`query/engine.py`) — all return JSON-friendly `dict`s

Two cross-cutting rules carried from SP_022: **every `Optional[date]` → `iso|None`** (never a
bare `.isoformat()`), and **provenance joined by id into a `{id: Citation}` dict** (never
zipped). A shared private `_iso(d)` helper centralizes the date guard.

- **`get_timeline(entity, predicate) -> dict`** — `subj = repo.resolve_entity(entity)`; if
  `None` → `{"entity": entity, "predicate": predicate, "resolved": False, "timeline": []}`
  (an ambiguous bare name resolves to `None` — never a silent pick; the agent must
  disambiguate). Else `target = repo.canonical_predicate(predicate)` (for the label) and
  `claims = repo.get_claims_by_predicate(predicate, subject_id=subj.id)` — **reusing the one
  matching path** (Stage-3 M1: no per-claim N+1 canonicalization; guaranteed-consistent with the
  cross-entity tool). Order **ascending** by `(as_of or date.min, valid_from or date.min, id)`
  (the repo returns `as_of DESC`; the engine re-sorts ascending for a chronology — `date.min`
  sentinels are safe, no `None` comparison). Citations via `repo.get_sources([ids])` indexed by
  `claim_id`. Each entry: `{claim_id, predicate: target, value: object_value, as_of: iso|None,
  valid_from: iso|None, valid_to: iso|None, superseded_by, confidence, source_uri,
  source_as_of, snippet}`.
- **`get_relationships(entity, link_type=None) -> dict`** — resolve (None → `resolved: False`,
  `relationships: []`). `out = repo.get_links(link_type, from_entity_id=subj.id)`;
  `inc = repo.get_links(link_type, to_entity_id=subj.id)`; merge **deduped by `link.id`**
  (a self-loop appears once, tagged `outgoing`). Names via `{e.id: e.canonical_name for e in
  repo.list_entities()}` (full scan; corpus is small — avoids adding a get-entity-by-id read).
  Citations via `repo.get_link_sources([ids])` by `link_id`. Each entry: `{link_id, link_type,
  direction: "outgoing"|"incoming", from_entity_id, from_name, to_entity_id, to_name,
  as_of: iso|None, valid_to, source_uri, source_as_of, snippet}`. Sorted by `(link_type,
  link_id)` for determinism.
- **`list_metrics() -> list[dict]`** — `[{"canonical_key", "display_name", "aliases"} for m in
  repo.list_metrics()]`.
- **`get_claims_by_predicate(predicate) -> dict`** — `target = repo.canonical_predicate(
  predicate)`; `claims = repo.get_claims_by_predicate(predicate)`; names via `list_entities()`
  map; citations via `repo.get_sources([ids])`. `{"predicate": target, "count": n, "claims":
  [{claim_id, subject_entity_id, subject_name, value, as_of: iso|None, valid_to,
  superseded_by, confidence, source_uri, source_as_of}]}`.

### 4. `MockQueryEngine` (`api/engine.py`)

Extend the `ExposureEngine` Protocol with the four method signatures and give the mock
deterministic canned data **coherent with its planted Q1-revenue contradiction** (so the
contradiction is observable through `get_timeline("HelixPay","revenue")` — two coexisting
values — and through `get_claims_by_predicate("revenue")`). Add a `get_relationships`
("Maria Santos" → `reports_to` → org root, plus an incoming edge) and a `list_metrics`
(revenue + ARR with aliases). Update the `ExposureEngine` class + module docstrings
("four optional surfaces" → eight).

### 5. MCP tools (`mcp/server.py`)

Register four tools alongside the existing eight (→ **twelve**), each a thin `_retrieval`
dispatch (keeps graceful degradation: a `QueryEngine`-only engine returns
`{"available": false}`). Update module + `build_mcp` docstrings (eight→twelve). As with
SP_022, the items remain inside the `{available, results}` envelope (Developer-Mode / full MCP
clients read `results` directly; a strict OpenAI Deep-Research adapter remains a deliberate
follow-up, not this sprint).

## Testing Strategy

- **`test/unit/query/fakes.py`** — extend `FakeRepository`: a `metrics: list[MetricVocab]`
  store + `add_metric` helper + `list_metrics`; `get_links` gains `to_entity_id`;
  `get_claims_by_predicate(predicate, subject_id=None)` (canonical-equality match via the fake's
  own `canonical_predicate` — alias matching works through `self.vocab`, so a claim stored
  `"arr"` with `vocab={"arr":"revenue"}` is found by `get_claims_by_predicate("revenue")`).
  This is behaviorally equal to the SQL path for alias/exact matching; the **period-strip
  regex** is the one thing the fake does NOT reproduce and is proven only in the db test
  (Stage-3 M2: unit tests for these methods therefore use canonical/alias predicates, never
  period-qualified spellings). Keep it `Repository`-Protocol-conformant. Additive; existing
  tests unaffected.
- **`test/unit/query/test_engine.py`** — new cases:
  - `get_timeline` returns the subject+predicate history in **ascending** `as_of` order with
    the supersession chain visible (a superseded claim carries `superseded_by`); both sides of
    a same-period value conflict coexist (none dropped); each entry is cited
    (`source_uri`/`source_as_of`); an **unresolved/ambiguous** entity → `resolved: False`,
    `timeline: []`, no raise; predicate canonicalization matches a raw-stored predicate
    (alias) onto the requested key.
  - `get_relationships` returns **both** outgoing and incoming edges with correct `direction`
    and resolved `from_name`/`to_name`; `link_type` filter narrows; a self-loop is emitted
    **once with `direction == "outgoing"`** (Stage-3 MEDIUM-1); unresolved entity →
    `resolved: False`; provenance `source_uri` present when the link has a citation,
    absent-citation tolerated.
  - `list_metrics` returns canonical_key/display_name/aliases dicts; empty vocab → `[]`.
  - `get_claims_by_predicate` returns claims across **multiple** subjects with resolved
    `subject_name`, `count` correct, `as_of` ISO-or-`None`; a predicate alias canonicalizes to
    the same set; an unknown predicate → `count: 0` (no raise).
  - `HelixQueryEngine` still satisfies `QueryEngine` and `ExposureEngine` (typed assignment +
    `isinstance`).
- **`test/unit/api/test_mcp.py`** — `EXPECTED_TOOLS` → twelve; assert the four new tools
  registered and pass through to the extended `MockQueryEngine` (`get_timeline` history,
  `get_relationships` edges, `list_metrics`, `get_claims_by_predicate`); extend the
  degradation test so a `CoreOnly` engine → `available: false` for **all eight** retrieval
  tools.
- **`test/integration/db/test_repository_reads.py`** (`db`-marked, auto-skips without
  `DATABASE_URL`) — round-trip on a real `PostgresRepository`:
  - `get_links(to_entity_id=...)` returns the **incoming** edge and excludes the outgoing one;
    `link_type` + `to_entity_id` AND together.
  - `list_metrics` round-trips an `upsert_metric` (canonical_key/display_name/aliases).
  - `get_claims_by_predicate` matches a **period-qualified** stored predicate ("Q1 2026
    revenue"), a canonical one ("revenue"), AND a literal **alias** ("arr") onto the same key
    across two subjects; a distinct suffix ("revenue vs plan") is **excluded**; and a
    **concatenated** token ("fy2026 ebitda") is **NOT** over-stripped to "ebitda" (Stage-3 H1
    regression — proves the `+`-separator regex). Also `subject_id=` narrows to one subject
    (the `get_timeline` path). Plus the typed `_: Repository = repo` conformance check holds.

## Success Criteria

- All four tools (`get_timeline`/`get_relationships`/`list_metrics`/`get_claims_by_predicate`)
  return `{"available": true, ...}` against the real `HelixQueryEngine`; a `QueryEngine`-only
  engine still degrades to `{"available": false}`.
- `get_timeline` exposes the supersession chain and coexisting conflicting values in
  chronological order, each cited; an ambiguous entity degrades to `resolved: False` without
  raising. `get_relationships` returns both directions with resolved endpoint names.
  `get_claims_by_predicate` matches raw/period-qualified/canonical predicate spellings onto one
  key across subjects, excluding distinct suffixes.
- The frozen `QueryEngine` Protocol is untouched; the new `Repository` reads and the
  `MetricVocab` model are additive; no schema change; **$0** (no LLM/embedding calls).
- Green bar: full unit suite + the new unit tests pass; the new db-integration tests pass
  against pgvector pg16; `mypy` clean; all validators PASS.

## Reviews

### Pre-Implementation Review

Foundational ⇒ ≥2 independent iterations (per `practices/GL-SELF-CRITIQUE.md`).

- **Iteration 1** — architect-reviewer, plan-as-written, adversarial; 0 CRITICAL, 3 HIGH + 5 MEDIUM + 3 LOW, REQUEST-CHANGES — all folded (HIGH-1 `contracts/__init__.py` MetricVocab re-export unlisted→added to touches_paths + §1; HIGH-3 POSIX regex omits Python's `\b`→separator class changed `*`→`+`; HIGH-2 engine passes raw predicate not canonical key→pinned; MEDIUM-1 self-loop direction test; MEDIUM-3 get_timeline N+1→reuse get_claims_by_predicate(subject_id); MEDIUM-4 drop "at most one" + get_links docstring). Files reviewed: SP_023_graph_temporal_tools.md, contracts/models.py, contracts/repository.py, contracts/__init__.py, contracts/query.py, db/repository.py, db/schema.sql, query/engine.py, api/engine.py, mcp/server.py, test/unit/query/fakes.py.
- **Iteration 2** — code-reviewer, plan-as-written, adversarial; 1 CRITICAL + 3 HIGH + 2 MEDIUM + 2 LOW, REQUEST-CHANGES — all folded (CRITICAL C1 `contracts/__init__.py` re-export→ImportError, same as arch HIGH-1; HIGH H1 SQL `*`→`+` over-strip `fy2026 ebitda` + regression test; HIGH H2 alias-fetch sub-step under-specified→explicit `SELECT aliases` step + alias unit test; HIGH H3 Python `set` invalid for `ANY(%s)`→`sorted(list)`; MEDIUM M1 get_timeline N+1; MEDIUM M2 fake can't period-strip→unit tests use canonical/alias spellings only). Files reviewed: SP_023_graph_temporal_tools.md, contracts/models.py, contracts/repository.py, contracts/__init__.py, db/repository.py, query/engine.py, api/engine.py, mcp/server.py, test/unit/query/fakes.py, test/unit/query/test_engine.py, test/unit/api/test_mcp.py, test/integration/db/test_repository_reads.py.
- **Iteration 3 (confirmation)** — main, re-read of the revised plan; all prior CRITICAL/HIGH folds verified present in the design + testing sections (init re-export listed; `+`-separator regex with `fy2026 ebitda` regression; alias-fetch step + `sorted(list)`; `get_timeline` reuses `get_claims_by_predicate(subject_id)`; get_links docstring/at-most-one) → **0 CRITICAL / 0 HIGH, APPROVE** (hard-stop floor not reached). Files reviewed: SP_023_graph_temporal_tools.md.

### Post-Implementation Review

Foundational ⇒ ≥2 independent iterations; plan-blind (Rule 5 — reviewer sees only code + tests).

- **Iteration 1** — code-reviewer, plan-blind over the diff; 0 CRITICAL, 1 HIGH + 4 MEDIUM + 5 LOW, APPROVE-WITH-NITS — folded (HIGH H2 mock `get_claims_by_predicate` ignored its `predicate` arg [hardcoded "revenue"], the "mock masks shape drift" trap → mock now canonicalizes the input via its canned vocab + returns empty for non-revenue; L2 added `resolved:True, timeline:[]` unit test; LOW snippet-asymmetry documented in docstring; MEDIUMs on the full `list_entities` scan + two-cursor read accepted eyes-open as documented O(N)/consistent-with-`canonical_predicate`). Files reviewed: contracts/models.py, contracts/__init__.py, contracts/repository.py, db/repository.py, query/engine.py, api/engine.py, mcp/server.py, test/unit/query/test_engine.py, test/unit/query/fakes.py, test/unit/api/test_mcp.py, test/integration/db/test_repository_reads.py.
- **Iteration 2** — architect-reviewer, plan-blind, confirmation; 0 CRITICAL / 0 HIGH, 1 MEDIUM + 3 LOW, APPROVE — frozen `QueryEngine` confirmed untouched, `ExposureEngine`+getattr degradation tested across all 8 optional tools, Repository extensions additive + backward-compatible, no query→db leak, ontology invariants (no-collapse, supersession-visible, None-on-ambiguity, consistent canonicalization) preserved + tested, the SQL/Python period-strip divergence traced and pinned by the `fy2026 ebitda` regression. MEDIUM (cross-layer `get_claims_by_predicate`/`list_metrics` homonym, the SP_022 `get_sources` hazard) **fixed**: engine docstrings now note they are distinct from the `Repository` methods (dict vs `Claim[]`/`MetricVocab[]`); LOW fake null-subject ordering aligned to SQL `NULLS LAST`; LOW `source_as_of` semantics (claim period vs document date) documented. Files reviewed: contracts/query.py, contracts/models.py, contracts/__init__.py, contracts/repository.py, db/repository.py, query/engine.py, api/engine.py, mcp/server.py + tests.

**Verification after folds:** unit suite (no `DATABASE_URL`, the normal condition) **636 passed / 1 db-skipped**; **8/8 DB-integration reads passed against pgvector pg16** (`get_links` incoming, `list_metrics` round-trip, `get_claims_by_predicate` period-strip + alias + `fy2026` non-over-strip + `subject_id` narrowing); `mypy` clean (71 files). Two pre-existing env-only failures (org-chart `as_of` with undated SP_011 seed edges; `test_rest` engine-global pollution when `DATABASE_URL` is set) fail identically with this sprint's work stashed — NOT introduced here.

## Documentation & Deploy

- Reconcile: `CLAUDE.md` (MCP tool list eight→twelve + a gotcha on the period-strip match and
  the both-directions traversal), `SOLUTION.md`/README if they enumerate tools.
- Deploy: **Deployed + verified 2026-06-11.** Operator approved ("Deploy"). Canonical FF push of
  `b91a67a` → `origin/main` → CI `Deploy to Production` green (gateway 21s via uv + deploy 48s:
  rsync → `deploy.sh` → `/health` 200). Live probe of `https://helixpay.serverado.app/mcp`:
  `tools/list` now returns **12 tools** (was 8); the four new tools
  (`get_timeline`/`get_relationships`/`list_metrics`/`get_claims_by_predicate`) are present and
  return `available:true` on the real `HelixQueryEngine`; `verify_mcp.py` exit 0. Results are over
  the **seeded backbone** (full-corpus extraction remains the separately-gated paid step). The
  local pre-push gateway was bypassed (audited: system-python no-deps false failure; `b91a67a`
  verified green via uv; CI authoritative per Rule 11).
