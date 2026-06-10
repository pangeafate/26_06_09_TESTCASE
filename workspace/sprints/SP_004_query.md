---
sprint_id: SP_004
tier: Foundational
features: [query-engine, hybrid-retrieval, temporal-resolver, contradiction-surfacing, grounded-ask]
user_stories: []
schema_touched: false
structure_touched: true
status: In Progress
isolation: git-worktree
branch: sprint/SP_004-query
worktree: .claude/worktrees/SP_004
agent_owner: "Agent 3 (query brain)"
touches_paths:
  - helixpay/query/**
  - test/unit/query/**
  - test/integration/query/**
fix_type: ""
touches_checklist_items: [query-retrieval-rrf, query-graph-org, query-temporal-resolver, query-contradictions, query-planner, query-synthesis-citations, query-engine-impl]
---

# SP_004: Query Brain — retrieval + graph + reasoning + grounded `ask()`

## Sprint Goal

Implement the `QueryEngine` Protocol (spec §4, §5 Agent 3) over the frozen
`Repository`: hybrid retrieval (semantic + lexical → reciprocal-rank fusion),
recursive-CTE org hierarchy with dotted-line distinction, a temporal resolver
(freshest-wins, staleness flagged, `as_of_coverage` populated), contradiction
surfacing as first-class objects, and a grounded `ask()` whose synthesis is
strictly grounded in retrieved material with **zero uncited claims**. Built and
tested against the **seeded fixture DB** (roster + metric_vocab + the planted Q1
revenue value-conflict), not real extracted data, so it can land before the
extraction pole (Agent 2) finishes.

## Current State

- Phase 0 gate (SP_001) is frozen on `main`: `helixpay/contracts/**` (models +
  `QueryEngine`/`Repository` Protocols + `OrgNode`/`EntityDetail` TypedDicts),
  `helixpay/db/repository.py` (`PostgresRepository`, the one impl — recursive-CTE
  `get_org_subtree`, `search_semantic`/`search_lexical`, `get_sources`,
  `get_contradictions`, `resolve_entity`, `canonical_predicate`), `config.py`
  (pinned `SYNTHESIS_MODEL=claude-opus-4-8`, `EMBEDDING_MODEL=voyage-3`,
  `EMBEDDING_DIM=1024`), and `helixpay/seed/**` which loads the deterministic
  backbone + a query fixture (Revenue entity with two conflicting `revenue`
  claims — dashboard SGD 14.2M vs board deck SGD 13.9M — and a
  `value_conflict` contradiction across both sources).
- No `helixpay/query/` package yet. Agent 4 (exposure) currently mocks the
  `QueryEngine` Protocol until this lands.
- Local toolchain: Python 3.12 + uv + Docker (pgvector pg16) available; no
  `ANTHROPIC_API_KEY`/`VOYAGE_API_KEY` in the dev shell (so the LLM/embedding
  boundary must be injectable and stubbed in tests — we never make paid calls in
  the suite).

## Desired End State

- `helixpay/query/` exports a concrete `HelixQueryEngine` satisfying the
  `QueryEngine` Protocol (`ask`, `get_entity`, `get_org_chart`,
  `find_contradictions`), constructed over a `Repository` plus injectable
  `Embedder` and `Synthesizer` seams (real Voyage/Anthropic by default; fakes in
  tests).
- `ask(q)` returns a cited, time-aware `AnswerBundle` on the fixture for the §8
  question shapes: hierarchy, staleness, the ARR/revenue contradiction,
  cross-document synthesis, customer ownership. At least one answer surfaces the
  planted contradiction with **both sides attributed**.
- `get_org_chart()` resolves the roster hierarchy (Wei Chen at root, dotted-line
  reports distinct from solid); `get_entity(name)` returns entity + claims (+
  aliases/links best-effort — see Contract Friction).
- Hybrid retrieval fuses `search_semantic` + `search_lexical` via RRF; the
  temporal resolver prefers later documents over the 2026-04-15 roster and says
  so; `ask()` output is enforced to contain zero uncited claims.
- Unit tests (no DB, stubbed LLM/embedder, in-memory fake Repository) green;
  DB-marked integration tests run `ask()`/graph/contradiction paths against the
  real seeded fixture when `DATABASE_URL` is set (auto-skip otherwise);
  `mypy helixpay` clean.

## What We're NOT Doing

- No `Repository`/contract changes (frozen — friction flagged below, not forked).
- No extraction, loaders, MCP/API/CLI, Docker/Makefile, or eval harness (Agents
  1/2/4/5/6). We consume `Repository` reads; we do not write ingest data.
- No trained cross-encoder reranker — RRF only (explicit scope cut, spec §11;
  marginal at this corpus size).
- No raw SQL anywhere — all DB access via the `Repository` Protocol (CLAUDE.md §7).
- No edits to `prompts/**` (Agent 2 owns it); the synthesis prompt lives as a
  named, versioned prompt under `helixpay/query/prompts/` to honour the
  named-prompt discipline without crossing ownership.

## Technical Approach

Layered modules under `helixpay/query/` (capabilities → shared logic → models;
no infra imports beyond the injected seams):

1. **Seams (`clients.py`)** — `Embedder` Protocol (`embed_query(text)->
   list[float]`, 1024-d) and `Synthesizer` Protocol (`synthesize(prompt, *,
   schema)-> dict`). Concrete `VoyageEmbedder`/`AnthropicSynthesizer` built lazily
   from `helixpay.config` (no key access at import). Tests inject fakes. Keeps the
   high-noise external-tool boundary isolated (CLAUDE.md §14).
2. **Retrieval (`retrieval.py`)** — `hybrid_search(repo, embedder, query, k)`:
   `search_semantic(qvec, k)` + `search_lexical(query, k)` → **reciprocal-rank
   fusion** `score = Σ 1/(RRF_K + rank)` (RRF_K=60, equal weight; deterministic
   tie-break on chunk id). Returns fused `[(Chunk, score)]`. Pure given the repo +
   embedder, so unit-testable with a fake repo.
3. **Graph (`graph.py`)** — `org_chart(repo, as_of)` delegates to
   `get_org_subtree` (cycle-guarded recursive CTE; dotted vs solid already
   distinct in `OrgNode`). `entity_detail(repo, name)` → resolve_entity → claims
   via `get_claims`, links via `get_links` filtered to the entity. Aliases:
   best-effort (see Contract Friction).
4. **Temporal (`temporal.py`)** — `resolve_freshest(claims)` groups by
   `(subject, predicate)`, orders by `as_of` desc, returns the freshest plus the
   superseded set; `staleness(...)` flags when the freshest evidence predates a
   reference (e.g., a later doc disagrees with the 2026-04-15 roster);
   `as_of_coverage(citations)` → `{min, max, by_source}` summary for the bundle.
5. **Contradictions (`contradictions.py`)** — `relevant(repo, subject_ids,
   predicates, topic)`: `get_contradictions()` filtered by resolved subject and/or
   `canonical_predicate(topic)`. Never silently resolves; both claim ids carried
   so the synthesis can attribute each side.
6. **Planner (`planner.py`)** — `route(question)-> Plan` classifying
   `{structured | retrieval | both}` from cheap lexical signals (hierarchy →
   structured+graph; metric/number/"disagree" → both + contradiction probe;
   "summarize"/open → both). Records the chosen route for the answer log.
7. **Synthesis + citation enforcement (`synthesis.py`)** — assemble a grounding
   context of numbered facts (claims `[C#]` carrying claim_id, retrieved chunks
   `[S#]` carrying chunk_id), call `Synthesizer` with the named prompt
   (`prompts/ask_synthesis.md`) under a structured-output schema returning
   `sentences=[{text, cites:[markers]}]`. `enforce_citations(...)` drops/flags any
   factual sentence with no marker (the **no-uncited-claims** guard), maps markers
   → `Citation` via `repo.get_sources` (claims) and chunk provenance, and
   assembles the final `AnswerBundle`.
8. **Engine (`engine.py`)** — `HelixQueryEngine` wires the above: `ask` runs
   plan → gather (retrieval/structured/contradictions) → synthesize → enforce →
   bundle (with `as_of_coverage`, `contradictions` present-and-attributed,
   `confidence`); `get_entity`/`get_org_chart`/`find_contradictions` are thin
   structured reads. Logs plan route, retrieved ids, cited ids (Agent 6 reads
   these).

### Contract Friction (flagged, not forked — re-freezes the gate per fanout README)
- **No alias read on `Repository`.** `EntityDetail.aliases` cannot be populated
  through the frozen Protocol (`resolve_entity` only goes mention→entity; there is
  no `get_aliases(entity_id)`), and raw SQL outside `helixpay/db/` is forbidden.
  `get_entity` returns `aliases: []` and the delivery report recommends adding
  `get_aliases(entity_id)->list[str]` to the Protocol.
- **No entity-by-id read.** `get_org_subtree` returns names but not roles;
  enriching `OrgNode.role`/per-node attributes would need a by-id entity read the
  Protocol lacks. Left unset; recommend `get_entity_by_id` alongside the above.

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `helixpay/query/__init__.py` | Create | Export `HelixQueryEngine` (+ seam Protocols) |
| `helixpay/query/clients.py` | Create | `Embedder`/`Synthesizer` seams + lazy Voyage/Anthropic impls |
| `helixpay/query/retrieval.py` | Create | Hybrid retrieval + RRF fusion |
| `helixpay/query/graph.py` | Create | Org chart + entity-detail reads |
| `helixpay/query/temporal.py` | Create | Freshest-wins + staleness + as_of_coverage |
| `helixpay/query/contradictions.py` | Create | Contradiction surfacing/filtering |
| `helixpay/query/planner.py` | Create | Route classifier {structured\|retrieval\|both} |
| `helixpay/query/synthesis.py` | Create | Grounding context + citation enforcement |
| `helixpay/query/prompts/ask_synthesis.md` | Create | Named synthesis prompt (grounded, cite-every-claim) |
| `helixpay/query/engine.py` | Create | `HelixQueryEngine` (the `QueryEngine` impl) |
| `test/unit/query/test_retrieval.py` | Create | RRF fusion math + ordering |
| `test/unit/query/test_temporal.py` | Create | Freshest-wins, staleness, coverage |
| `test/unit/query/test_planner.py` | Create | Route classification per question shape |
| `test/unit/query/test_synthesis.py` | Create | Citation enforcement: uncited sentence dropped/flagged |
| `test/unit/query/test_contradictions.py` | Create | Topic/subject filtering, both sides carried |
| `test/unit/query/test_engine.py` | Create | `ask`/`get_*` wiring with fakes; Protocol conformance |
| `test/integration/query/test_query_integration.py` | Create | `ask`/graph/contradiction over the real seeded fixture (db-marked) |

## Dependencies

Declared here (NOT added to `pyproject.toml` — orchestrator consolidates at merge,
per fanout README). Imported **lazily inside the concrete client methods** so the
`helixpay.query` package imports cleanly without them and the unit suite never
needs them:
- `anthropic` — `claude-opus-4-8` synthesis in `AnthropicSynthesizer`.
- `voyageai` — `voyage-3` 1024-d query embeddings in `VoyageEmbedder`.

## Testing Strategy

Per `practices/GL-TDD.md`, red→green→refactor per unit; mock the external LLM and
embedding clients in unit tests; use the `db`-marked seeded fixture DB for
integration.

1. **Retrieval** — fake repo returns known semantic/lexical rankings; assert RRF
   ordering and that an item ranked in both beats one ranked in one; tie-break
   deterministic.
2. **Temporal** — claims with mixed `as_of` → freshest selected, older flagged
   superseded; `as_of_coverage` reports min/max; a later doc beats the 2026-04-15
   roster and staleness is flagged.
3. **Planner** — each §8 question shape routes to the expected plan
   (hierarchy→structured, metric→both, summarize→both, "disagree"→contradiction).
4. **Synthesis** — a structured response with one cited + one uncited factual
   sentence yields a bundle whose answer keeps only cited claims and whose
   `citations` map back to claim/chunk provenance; an all-uncited answer degrades
   safely (flagged, no fabricated citations).
5. **Contradictions** — `find_contradictions("revenue")` filters the fixture
   conflict; both `claim_a_id`/`claim_b_id` present.
6. **Engine** — `HelixQueryEngine` satisfies `isinstance(.., QueryEngine)`
   (runtime-checkable); `ask` end-to-end with fakes returns a bundle with
   citations and (for the revenue question) a surfaced contradiction.
7. **Integration (DB-gated)** — migrate + seed a throwaway pgvector container;
   `ask("What was HelixPay's ARR/revenue in Q1 2026?")` (stubbed synthesizer,
   real retrieval+reads) surfaces the planted contradiction with two attributed,
   `as_of`-stamped citations; `get_org_chart()` root is Wei Chen. Auto-skips when
   `DATABASE_URL` is unset.

## Success Criteria

- [ ] `helixpay/query/` exports `HelixQueryEngine`; `isinstance(engine, QueryEngine)` true
- [ ] Hybrid retrieval fuses semantic+lexical via RRF (tested ordering)
- [ ] Temporal resolver: freshest-wins + staleness flag + `as_of_coverage` (tested)
- [ ] Planner routes the five §8 question shapes correctly (tested)
- [ ] `ask()` enforces zero uncited claims (tested: uncited sentence dropped/flagged)
- [ ] `find_contradictions("revenue")` returns the fixture conflict with both sides
- [ ] DB integration: `ask` surfaces the planted contradiction with 2 attributed `as_of` citations; org root = Wei Chen (runs under Docker pgvector; auto-skips without `DATABASE_URL`)
- [ ] `uv run pytest test` green; `uv run mypy helixpay` clean
- [ ] No raw SQL outside `helixpay/db/`; no `prompts/**`/contract edits; secrets env-only
- [ ] PROGRESS.md updated (worktree-local)

### Doc Reconciliation Checklist

Meta-doc reconciliation is the orchestrator's at integration (fanout README:
worktree agents don't edit shared meta-docs). This sprint touches only its own
`touches_paths` + a worktree-local PROGRESS pointer; no shared meta-doc is edited
here.

- [ ] (orchestrator) `FEATURE_LIST.md` — query engine deliverable
- [ ] (orchestrator) `ARCHITECTURE.md` — query/reasoning layer
- [ ] (orchestrator) `CODEBASE_STRUCTURE.md` — `helixpay/query/` layout

## Review Log

### Pre-Implementation Review

- **Iteration 1** (2026-06-09): architect-reviewer (independent sub-agent, plan-aware) found 1 CRITICAL, 3 HIGH, 3 MEDIUM, 3 LOW. Files reviewed: workspace/sprints/SP_004_query.md, HELIXPAY_BUILD_SPEC.md §2/§4/§5/§8, fanout/AGENT_3_query.md, helixpay/contracts/{query,repository,models}.py, helixpay/db/repository.py, helixpay/seed/{fixtures,metric_vocab,roster}.py, CLAUDE.md §7. Verdict: APPROVE-WITH-CHANGES.
- **Iteration 2** (2026-06-09): code-reviewer (independent sub-agent, plan-aware) found 3 CRITICAL, 5 HIGH, 4 MEDIUM, 3 LOW. Files reviewed: workspace/sprints/SP_004_query.md, fanout/AGENT_3_query.md, HELIXPAY_BUILD_SPEC.md §5/§8, helixpay/contracts/{query,repository,models}.py, helixpay/db/repository.py, helixpay/config.py, helixpay/seed/fixtures.py, test/conftest.py, practices/GL-TDD.md. Verdict: APPROVE-WITH-CHANGES.

**Resolution — all CRITICAL and HIGH addressed:**
1. **arch-C1 / arch-H1 (ARR≠revenue key; contradiction probe must not gate on strict predicate ==)**: `metric_vocab` keeps `arr` and `revenue` as distinct keys; the fixture's planted conflict is on `revenue`. (a) The acceptance/integration test uses the **revenue** phrasing the fixture actually contains (honest — `ask("…Q1 2026 revenue…")`). (b) `ask`'s contradiction probe gathers `get_contradictions(subject_id)` for **every resolved subject** PLUS predicate-match over the full set, never strict `predicate==canonical(topic)` only, and runs on any metric/value question (not gated on the word "disagree"). (c) `find_contradictions(topic)` resolves topic both ways — `resolve_entity(topic)` and `resolve_entity(display_name_of(canonical_predicate(topic)))` for a subject filter, plus `canonical_predicate(topic)` predicate match, unioned; `topic=None` → all. `find_contradictions("ARR")` honestly returns `[]` on the fixture (no ARR conflict seeded). The arr/revenue distinction is stated in the module docstring + delivery report.
2. **code-C1 (no eager `load_config` at import)**: `clients.py` reads env **inside** the concrete methods (lazy `import anthropic`/`voyageai` too); `helixpay/query/__init__.py` exports only the class + an explicit `build_default_engine(repo)` factory — never constructs real clients at import. Unit suite never touches keys or the SDK packages.
3. **code-C2 (integration test must seed)**: integration test calls `load_fixture(pg_repo)` then asserts `len(bundle.contradictions) >= 1` with both `claim_a_id`/`claim_b_id` populated and 2 `as_of`-stamped citations — not a vacuous pass.
4. **code-C3 (fake `get_sources` must exercise the retain path)**: the in-memory fake Repository implements `get_sources` to return a well-formed `Citation` for the cited claim id, so the citation-enforcement test exercises *retain-cited + drop-uncited*, not only the all-uncited degrade path.
5. **arch-H3 (chunk-only citations have no Protocol provenance)**: pinned policy — **claim-backed** sentences are the citeable unit (`get_sources` → `Citation(source_uri, as_of)`); retrieved chunks `[S#]` are synthesis *context only* and do not by themselves satisfy the citation requirement. A factual sentence citing only chunks/no marker is dropped/flagged. This guarantees zero uncited claims. Genuine friction logged: no chunk→document read → recommend `get_chunk_sources(chunk_ids)->list[Citation]`.
6. **arch-H2 (role is reachable — don't over-claim friction)**: `get_org_chart`/`get_entity` enrich `OrgNode.role`/entity attributes opportunistically via `resolve_entity(name)` (canonical names resolve unambiguously). The remaining genuine frictions are aliases (no `get_aliases`) and a perf note (no `get_links(from_entity_id=…)` / `get_entity_by_id`).
7. **code-H1 (RRF tie-break untested)**: `test_retrieval.py` includes a case with two chunks of equal RRF score asserting ascending chunk-id order.
8. **code-H2 (canonical_predicate hits DB; fake must stub)**: the fake Repository implements `canonical_predicate` via an in-memory dict; contradiction tests cover both a canonical-mapping topic and a raw≠canonical topic, asserting the filter is on the canonicalized value.
9. **code-H4 (freshness routing)**: planner test asserts an "as of / latest" hierarchy question triggers `as_of` handling; the engine computes `as_of_coverage` (incl. a `stale` flag vs the 2026-04-15 roster) from gathered evidence regardless of route.
10. **code-H5 / arch-M1 (runtime_checkable only checks names)**: `test_engine.py` calls all four methods on the fake-wired engine and asserts return types (`AnswerBundle`/`EntityDetail`/`OrgNode`/`list[Contradiction]`); `mypy helixpay` enforces signatures.
11. **code-H3 / arch-L1 (prompt location)**: synthesis prompt lives at `helixpay/query/prompts/ask_synthesis.md` — a justified deviation from the literal "`prompts/`" wording to avoid crossing Agent 2's ownership (stricter-rule reading); recorded for the §301 adversarial stage in the delivery report.

**Deferred (MEDIUM/LOW, non-blocking, tracked):**
- arch-M3/code-M1 `as_of_coverage` shape pinned by test: keys `{"earliest", "latest", "sources": {uri: iso}, "stale": bool}` (ISO-date strings).
- code-M3 None-safe freshness sort (`as_of or date.min`) — tested with a `None` `as_of` claim.
- code-M4 integration fake embedder returns `[0.01]*1024` (matches fixture; avoids undefined zero-vector cosine); contradiction surfacing asserted via the structured probe, not semantic rank.
- code-M2 / arch (perf) `get_links` full scan + no `get_entity_by_id` → friction note + Protocol recommendations in delivery report (not forked).
- arch-M2/code-L1 fakes live in `test/unit/query/conftest.py` (within `touches_paths`); `__init__` exports only `HelixQueryEngine` + `build_default_engine`.
- code-L2 no `__init__.py` in test dirs (matches existing `test/unit/**` layout). code-L3 `anthropic`/`voyageai` in `## Dependencies` for orchestrator merge; lazy-imported so local unit+integration runs need neither.
- arch-L2/L3 planner negative-phrasing test + structured answer-log shape (`{"route", "retrieved_chunk_ids", "cited_claim_ids"}`) for Agent 6.

### Post-Implementation Review

- **Iteration 1** (2026-06-09): code-reviewer (independent sub-agent, **plan-blind** — saw only code + tests + frozen contracts) found 2 CRITICAL, 4 HIGH, 5 MEDIUM, 4 LOW. Files reviewed: helixpay/query/{retrieval,temporal,planner,contradictions,synthesis,graph,clients,engine}.py, helixpay/query/prompts/ask_synthesis.md, test/unit/query/*.py, test/integration/query/test_query_integration.py. Verdict: APPROVE-WITH-CHANGES.
- **Iteration 2** (2026-06-09): security-auditor (independent sub-agent, **plan-blind**) found 0 CRITICAL, 1 HIGH, 2 MEDIUM, 2 LOW. Files reviewed: helixpay/query/{clients,synthesis,engine,retrieval,graph,contradictions,temporal,planner}.py. Verdict: APPROVE-WITH-CHANGES. Confirmed: no secret/connection-string leak (the `ask.trace` log carries integer ids only), no `eval`/`exec`/raw SQL, `importlib.import_module` takes constant module names (no injection), and the citation guard cannot be made to fabricate a citation by adversarial markers.

**Resolution — all CRITICAL and HIGH addressed (tests added; suite 87 green, mypy clean):**
1. **code-C1 (both contradiction sides must be citeable even cross-subject)**: `engine._gather_claim_facts` now fetches the conflicting contradiction's subject's claims when a side is missing from the resolved set, so both sides reach grounding and are citeable. Test: `test_ask_surfaces_contradiction_even_when_subject_entity_unresolved`.
2. **code-C2 (`relevant()` topic path was dead → metric conflict missed when the entity doesn't resolve)**: `contradictions.relevant` now takes `topics` and predicate-matches on the canonicalized term; `engine.ask` passes the question's candidate terms. A metric question surfaces the conflict even with zero resolved subjects. Tests: `test_relevant_by_topic_when_entity_unresolved`, engine test above.
3. **code-H1 (staleness off-by-one)**: `as_of_coverage` flags `stale` only when the freshest evidence is **strictly older** than the roster date; evidence on the roster date is current. Test: `test_as_of_coverage_on_roster_date_is_not_stale`.
4. **code-H2 (double-`replace` prompt corruption / injection)**: `render_prompt` now substitutes both placeholders in a single regex pass; injected braces are never re-expanded. Test: `test_render_prompt_single_pass_no_reexpansion`.
5. **sec-H1 (SDK exception could surface a prompt-bearing traceback)**: `engine.ask` wraps `synthesize` and degrades to the safe-empty output on any client error, logging a route-only warning (never the prompt/secret).
6. **sec-M1 (malformed/adversarial structured output crashed `ask`)**: `enforce_citations` is now type-defensive (non-list `sentences`, non-dict items, wrong-typed `text`/`cites`/markers, bad `confidence`) — never crashes, never fabricates a citation. `clients.synthesize` guards `json.loads`/non-dict tool input → safe empty. Test: `test_enforce_is_robust_to_malformed_output`.

**Deferred (MEDIUM/LOW, non-blocking, tracked):**
- code-H3 / sec perf: `resolve_entity`/`canonical_predicate` are one-call-per-term hot loops; capped at `_MAX_TERMS=40`/`_MAX_SUBJECTS=6` and documented. Real fix is a batched `resolve_entities`/`get_links(from_entity_id=…)` Protocol read (delivery-report friction list).
- code-H4 prompt location: governance-recorded deviation (see delivery report); query prompt under `helixpay/query/prompts/` to avoid Agent 2's `prompts/` ownership.
- code-M1 dedup via set (done in `enforce_citations`); code-M4 source-date dedup compares `date` objects (done); code-M5 dead-param (removed via `topics`).
- sec-LOW prompt-injection of chunk text is neutralised by the claim-backed citation guard (worst case is text/claim mispairing, never a fabricated source or RCE); explicit fenced-grounding hardening noted as optional.
- code-M2 `_enrich_roles` in-place mutation is safe (PostgresRepository returns a fresh subtree per call); code-M3/L3/L4 fake/test-fidelity polish noted.
