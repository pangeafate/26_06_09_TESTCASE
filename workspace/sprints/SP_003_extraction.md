---
sprint_id: SP_003
tier: Foundational
features: [extraction, entity-resolution, contradiction-detection, ingestion-pipeline, embeddings]
user_stories: []
schema_touched: false
structure_touched: true
status: Complete
isolation: git-worktree
branch: sprint/SP_003-extraction
worktree: .claude/worktrees/SP_003
agent_owner: "Agent 2 (extraction & ontology)"
touches_paths:
  - helixpay/ingest/__init__.py
  - helixpay/ingest/embed.py
  - helixpay/ingest/pipeline.py
  - helixpay/ingest/resolve.py
  - helixpay/ingest/contradict.py
  - helixpay/ingest/extract/**
  - prompts/**
  - test/unit/ingest/**
  - test/integration/ingest/**
fix_type: ""
touches_checklist_items: [ingest-embed, ingest-extract-schema, ingest-extract-prompt, ingest-extract-llm, ingest-resolve, ingest-contradict, ingest-pipeline, ingest-observability]
---

# SP_003: Extraction & Ontology — per-chunk claims/relations, resolution, contradictions, pipeline

## Sprint Goal

Build the heart of the HelixPay ontology: the ingestion pipeline that turns Agent 1's
`Chunk`s into a temporal, provenance-carrying ontology. Per chunk, an LLM
(`claude-sonnet-4-6`) emits candidate **claims + relations** under a strict
structured-output schema with a **validate-and-repair-or-drop** loop; mentions resolve
against the **seeded roster** (roster-first, ambiguous-without-context never silently
picked); metric predicates **canonicalize via `metric_vocab`**; claims/links persist
through the `Repository`; and **contradictions are detected as first-class rows** by
grouping claims on `(subject, canonical_predicate)` over overlapping time windows.
Conflicting claims **coexist** — never collapsed; superseded facts are **never deleted**
(same-source temporal updates set `valid_to`/`superseded_by`). I also own the **Voyage
embedding seam** (1024-dim) and the **end-to-end pipeline** (`discover → load → embed →
add_chunks → extract → resolve → canonicalize → persist → detect contradictions`),
idempotent on `content_hash`.

This is the longest-pole, highest-blast-radius slice (spec §5, Agent 2). It runs the full
**Foundational** lifecycle: pre-impl gate + 2 plan-review iterations (independent
reviewers), TDD, 2 plan-blind post-impl iterations.

## Current State

- The Phase 0 gate is frozen on `main`: `helixpay/contracts/**` (models + `Repository`,
  `SourceConnector`, `QueryEngine` Protocols), `helixpay/db/**` (8-table schema +
  `PostgresRepository`), `helixpay/config.py` (pinned models: `EXTRACTION_MODEL`,
  `EMBEDDING_MODEL`, `EMBEDDING_DIM=1024`), and `helixpay/seed/**` (roster +
  `metric_vocab` + query fixture). 27 unit tests pass; 11 DB tests skip without
  `DATABASE_URL`.
- `helixpay/ingest/**` does not exist. `prompts/` does not exist.
- Agent 1 (loaders, SP_002) and I run in parallel against the frozen `Chunk` contract;
  Agent 1's `helixpay/ingest/loaders/**` is NOT yet on `main`. My pipeline therefore
  depends on the **loader interface**, not Agent 1's code (spec §6: "2 and 1 meet only
  through the `Chunk` contract").
- This environment has no `DATABASE_URL`, no `ANTHROPIC_API_KEY`/`VOYAGE_API_KEY`, and no
  running Postgres. Unit tests (stubbed clients, no DB) are the green bar here; DB-gated
  and key-gated integration tests are authored and auto-skip locally (they run at
  orchestrator integration, exactly like `test/integration/db/`).

## Desired End State

- `helixpay/ingest/embed.py` — `VoyageEmbedder` (1024-dim, batched, **injectable**
  low-level client built lazily so unit tests need no `voyageai` install/key), validates
  every vector length == `EMBEDDING_DIM`.
- `helixpay/ingest/extract/`:
  - `schemas.py` — pydantic structured-output schemas (`ClaimOut`, `RelationOut`,
    `ExtractionOut`) **validated against the contracts** (`EntityType`/`LinkType`,
    ISO-date `as_of`, non-empty predicate, confidence ∈ [0,1]).
  - `prompts.py` — a named-prompt registry that loads prompt files from `prompts/` by
    name and renders them with chunk variables. No inline prompt strings in code.
  - `llm.py` — an `LLMClient` Protocol + a lazily-built `AnthropicClient`
    (`claude-sonnet-4-6`); `call_structured(...)` runs the **validate-and-repair-or-drop**
    loop (one repair attempt feeding the validation error back; else drop + structured
    log) and logs prompt name, input summary, output, and repair outcome (Agent 6 reads
    these — spec §8 observability).
  - `extractor.py` — `ChunkExtractor.extract(chunk, ctx)` → validated `ExtractionOut` or
    `None`; per-item normalization drops items that can't map to contracts (logged).
- `helixpay/ingest/resolve.py` — `resolve_mention(repo, name, entity_type, context)`:
  roster-first via `repo.resolve_entity`; accent/honorific normalization +
  transliteration variants for the mixed-language roster; **new** (non-roster) entities
  `upsert_entity(seeded=False)` only for open-class types (default `{customer}`); an
  ambiguous bare name with no resolving context returns `None` (never a silent pick, never
  a duplicate "Maria"). Context is derived from the document (`source_uri` path segments,
  author) so the two Marias / two Tans disambiguate.
- `helixpay/ingest/contradict.py` — `detect(repo, subject_id, canonical_predicate)`:
  groups `get_claims(subject, pred)`, compares **value-normalized** objects over
  overlapping time windows, classifies `kind ∈
  {value_conflict, temporal, source_disagreement}`, and writes via `add_contradiction`
  (pair-deduped by the repo). Conflicting claims coexist — detection never edits/deletes
  a claim.
- `helixpay/ingest/pipeline.py` — `run(root="data", repo=None, *, discover=, embedder=,
  extractor=)` orchestrates the full path; injectable seams make it fully unit-testable
  without Agent 1, a DB, or API keys. Idempotent end-to-end (rides the repo's idempotent
  upserts). Same-source temporal **supersession** via `get_claims` + `get_sources` +
  `supersede_claim` (never deletes; never collapses cross-source disagreement).
- Tests: `test/unit/ingest/**` green with no DB/keys; `test/integration/ingest/**`
  authored, DB/key-gated. `mypy helixpay/ingest` clean.

## What We're NOT Doing

- Not implementing loaders (Agent 1) — the pipeline consumes the `Chunk`/`SourceConnector`
  contract via an **injected `discover` callable** that defaults to lazily importing
  `helixpay.ingest.loaders.discover_all` when Agent 1 lands.
- Not editing `helixpay/contracts/**`, `helixpay/db/**`, `helixpay/config.py`,
  `helixpay/seed/**`, `pyproject.toml`, `CLAUDE.md`, or meta-docs (frozen / shared /
  orchestrator-owned). New deps (`anthropic`, `voyageai`) are declared below, not added to
  `pyproject.toml`.
- Not building the query/`ask` layer (Agent 3), MCP/API/CLI (Agent 4), or the eval harness
  (Agent 6).
- Not running real LLM/Voyage calls in unit tests (clients are stubbed/injected).

## Technical Approach

### Module layout (all under my `touches_paths`)
```
helixpay/ingest/
  __init__.py          # package marker
  embed.py             # VoyageEmbedder (injectable, 1024d, batched, dim-checked)
  pipeline.py          # run(...) orchestration, injectable seams, idempotent, supersede
  resolve.py           # roster-first mention resolution + safe new-entity creation
  contradict.py        # (subject, canonical_predicate) grouping → contradiction rows
  extract/
    __init__.py
    schemas.py         # ClaimOut / RelationOut / ExtractionOut (validated vs contracts)
    prompts.py         # named-prompt registry loading prompts/*.md
    llm.py             # LLMClient Protocol + lazy AnthropicClient + call_structured
    extractor.py       # ChunkExtractor: per-chunk → validated candidates
prompts/
  extract_claims.md    # the named extraction prompt (+ repair guidance)
```

### Key decisions
1. **Injected seams, lazy SDK imports.** `voyageai`/`anthropic` are imported only inside
   the real client factories, never at module import. Unit tests inject stub clients, so
   the suite runs with neither SDK installed and no keys (the brief's "injectable client"
   requirement; also GL-ERROR-LOGGING External-Tool-Isolation).
2. **Structured output = pydantic schema + validate-and-repair-or-drop.** The LLM is asked
   for JSON matching `ExtractionOut`; on parse/validation failure, exactly one repair call
   echoes the validation error; still-bad → drop the chunk's output and log
   (`error_type=integration_error`). No free-form trust. Per-item: items whose
   `subject_type`/`link_type` aren't in the contract enums, or whose `as_of` won't parse,
   are dropped individually with a logged reason (the rest survive). `confidence` is
   **clamped** to `[0,1]` by a schema validator (an LLM slip like `1.2` shouldn't discard a
   good claim) [Stage-3 L1].
3. **Roster-first resolution, ambiguity-safe — `department` is the discriminator** [Stage-3
   C1/H2/H-4]. `repo.resolve_entity(name, type, context)` is the authority. `resolve.py`
   adds Unicode NFKD accent folding + honorific stripping + whitespace collapse (tries
   `[raw, folded]`). Disambiguation context uses **only keys that exist as seeded
   `attributes` keys** — `department`, `location`, `role` (from `roster.py`); `source_uri`/
   `author` are NOT roster attributes and have zero filtering effect, so they are mapped to
   a `department` hint, never passed raw. The two Marias share `location="São Paulo"`, so
   **only `department` separates them** (Silva=Sales, Santos=Customer Success). Because
   `_filter_by_context` does naive bidirectional substring matching, a raw path token like
   `customer_success` will NOT match the seeded `"Customer Success"`; `resolve.py` therefore
   normalizes path segments through a small **path→department map**
   (`customer_success`/`cs`→`Customer Success`, `product__pos_self_service`→`Product`,
   `engineering`→`Engineering`, `sales`→`Sales`, `leadership`→`Executive`, `finance`,
   `marketing`, `people`, `it`) before building the context. On `None`: create a new
   `seeded=False` entity **only** for open-class types (default `{customer}`) — never for
   `person`/`team` (roster is authoritative; an unresolved bare given-name is dropped +
   logged, so the two Marias never get a silent third "Maria").
4. **Canonicalize before write.** Every metric-bearing predicate goes through
   `repo.canonical_predicate(raw)` before `add_claim`, so "ARR" and "annual recurring
   revenue" land on `arr` and contradiction grouping actually fires. Pure pre-validation
   inside `extract/**` (no DB) uses `helixpay.seed.metric_vocab.canonical_key` [Stage-3
   M-4]; the authoritative persist-time canonicalization is `repo.canonical_predicate`.
5. **Claims are value-claims; entity-relations are links** [Stage-3 M3]. A persisted
   `Claim` always sets `object_value` (never `object_entity_id`) — the claims natural key
   COALESCEs `object_value` to `''`, so two entity-valued claims from one chunk with the
   same predicate would silently collide. Relations (`reports_to`, `dotted_line_to`, `owns`,
   `member_of`, `mentions`) go through `add_link`.
6. **Contradiction detection.** The pipeline resolves the subject to an `Entity` and uses
   **`entity.id` (an `int`, asserted non-`None` post-persist)** — `get_claims(subject_id,
   predicate)` takes an int, never a name [Stage-3 C-1]. Per touched `(subject_id,
   canonical_predicate)`: pairwise compare value-normalized objects (numeric parse: strip
   currency symbols/units, fold magnitude suffixes K/M/B; else casefold string) over
   overlapping windows (`as_of` points / `valid_from..valid_to`; a `None` `as_of` is treated
   as open/overlapping). Differing values + overlap → `add_contradiction`, but **only when
   both `claim_a_id` and `claim_b_id` are non-`None` ints** (else log+skip — `NULL` bypasses
   the repo's pair-dedup) [Stage-3 M-5]. Non-overlapping **decision tree** for `kind`
   [Stage-3 H-5]: (1) `source_disagreement` if equal `as_of` **and** different document;
   (2) `temporal` if `as_of` values differ; (3) `value_conflict` otherwise. Hypothetical /
   counterfactual values ("would have been", "if we'd renewed") are **suppressed at
   extraction** (the prompt instructs the model not to emit them) so the planted Cosmos
   "120K loss vs 165K would-be-renewal" does **not** become a false contradiction [Stage-3
   H1]. Claims are **never** modified by detection (no collapse).
7. **Supersession (changed-file re-ingest), not collapse.** A changed file has a new
   `content_hash` ⇒ a new `documents` row but the **same `source_uri`** (the path). When
   persisting claim `C(subject,pred,value)` from source `S` with `C.as_of` **not `None`**,
   look at `get_claims(subject,pred)`; for an existing claim `E` with `E.id is not None`
   whose source (`cites = repo.get_sources([E.id]); cites[0].source_uri if cites else None`)
   **equals `S`** and whose `as_of` is **older** (`E.as_of is not None and E.as_of <
   C.as_of`) with a different value, call `supersede_claim(E.id, C.id, valid_to=C.as_of)`
   [Stage-3 C-2/C-3/H4/L-1]. Supersession is skipped when either `as_of` is `None` (the
   `valid_to: date` contract forbids `None`) or the source differs. Cross-source
   disagreement is left to contradiction detection — supersession is **same-source-only**,
   so it never collapses a real contradiction and never deletes.
8. **Idempotency + the content_hash short-circuit gap (surfaced, not hidden)** [Stage-3
   H3]. Re-running produces zero new rows: `upsert_document` no-ops on `content_hash`,
   `add_chunks` no-ops on `(document_id, ordinal)`, `add_claim`/`add_link`/
   `add_contradiction` no-op on natural keys; the pipeline also dedupes documents by
   `content_hash` within a run. This satisfies the hard requirement (a second run is a
   no-op on **state**). The brief's stronger "unchanged `content_hash` short-circuits"
   (skip re-embed/re-LLM across runs) **cannot be done through the frozen `Repository`** —
   there is no read-by-hash method. Rather than fork the contract, the pipeline exposes an
   injectable `already_ingested: Callable[[str], bool] | None` seam (skips embed+extract for
   a hash it returns `True` for) and the delivery report **proposes a contract addition**
   (`get_document(content_hash) -> Document | None`) for the orchestrator to fold into the
   gate. The cost-skip is thus available when a checker is injected and documented as a
   deferred, contract-level follow-up otherwise.
9. **Prompt path is package-anchored** [Stage-3 M2]. `extract/prompts.py` resolves the
   `prompts/` directory as `Path(__file__).resolve().parents[3] / "prompts"`
   (`extract/`→`ingest/`→`helixpay/`→repo root), never CWD-relative, so it works under
   Agent 4's CLI from any directory and after merge to `main`. An env override
   (`HELIXPAY_PROMPTS_DIR`) is honored for tests/packaging.
10. **Observability (spec §8).** Every LLM call logs (via `logging`, structured fields):
    prompt name, `source_uri`/ordinal, candidate counts, and the validate/repair outcome —
    the trail Agent 6 reads to explain a missed golden fact (bad chunk / failed resolution /
    dropped-on-repair). Logs carry **IDs and counts, not raw chunk bodies** (chunk text is
    elided/capped), and never secrets or connection strings [Stage-3 L2, GL-ERROR-LOGGING].

## Dependencies

Declared here per `fanout/README.md` (do **not** edit `pyproject.toml` `[project].dependencies`
in a worktree; the orchestrator consolidates at merge):
- `anthropic>=0.39` — extraction LLM (`claude-sonnet-4-6`); imported lazily inside the real
  client factory only.
- `voyageai>=0.3` — embeddings (`voyage-3`, 1024-dim); imported lazily inside the real
  client factory only.

Neither is needed to run the unit suite (clients are injected/stubbed), so the absence of
both from this environment is expected and does not block TDD.

## Cross-agent notes
- `helixpay/ingest/__init__.py` is **owned by Agent 2** (declared in `touches_paths`). Agent
  1 owns only `helixpay/ingest/loaders/**` and must create just
  `helixpay/ingest/loaders/__init__.py`; the orchestrator ensures the `helixpay/ingest/`
  package marker exists before integrating Agent 1's files [Stage-3 M-3].
- `prompts/**` is a new top-level directory claimed by no other agent [Stage-3 L-3].
- Loader seam pinned verbatim against `AGENT_1_loaders.md`: `discover_all(root) ->
  list[tuple[SourceConnector, str]]`; each `(connector, path)` tuple is processed by
  `connector.load(path)` [Stage-3 H-1, M1].

### Dependency on Agent 1 (parallel)
`pipeline.run` accepts `discover: Callable[[str], Iterable[tuple[SourceConnector, str]]]`.
Default: a lazy import of `helixpay.ingest.loaders.discover_all`; if absent (Agent 1 not
merged), it raises a clear, actionable `RuntimeError` naming the missing module. Unit tests
inject a fake `discover` + fake connector returning contract-valid `Document`+`Chunk`s, so
the pipeline is proven end-to-end without Agent 1.

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `helixpay/ingest/__init__.py` | Create | Package marker |
| `helixpay/ingest/embed.py` | Create | Voyage embeddings (injectable, 1024d, batched) |
| `helixpay/ingest/extract/__init__.py` | Create | Subpackage marker |
| `helixpay/ingest/extract/schemas.py` | Create | Structured-output schemas vs contracts |
| `helixpay/ingest/extract/prompts.py` | Create | Named-prompt registry (loads `prompts/`) |
| `helixpay/ingest/extract/llm.py` | Create | LLMClient Protocol + lazy Anthropic + validate-repair |
| `helixpay/ingest/extract/extractor.py` | Create | Per-chunk extraction orchestration |
| `helixpay/ingest/resolve.py` | Create | Roster-first mention resolution |
| `helixpay/ingest/contradict.py` | Create | Contradiction detection |
| `helixpay/ingest/pipeline.py` | Create | End-to-end ingestion runner |
| `prompts/extract_claims.md` | Create | Named extraction prompt + repair guidance |
| `test/unit/ingest/test_embed.py` | Create | Batching, dim validation, injection |
| `test/unit/ingest/test_schemas.py` | Create | Contract-validated schema + enum/date rejects |
| `test/unit/ingest/test_prompts.py` | Create | Named prompt loads + renders; unknown name errors |
| `test/unit/ingest/test_llm.py` | Create | validate / repair-then-pass / drop-after-repair |
| `test/unit/ingest/test_extractor.py` | Create | Stub client → candidates; bad output dropped |
| `test/unit/ingest/test_resolve.py` | Create | Roster-first, accent fold, ambiguous→None, safe-create |
| `test/unit/ingest/test_contradict.py` | Create | Value-normalized conflict, kind classification, no-collapse |
| `test/unit/ingest/test_pipeline.py` | Create | All-fakes end-to-end + idempotent re-run |
| `test/integration/ingest/test_pipeline_integration.py` | Create | DB-gated: persists claims/links + ≥1 contradiction; idempotent; supersede |
| `test/integration/ingest/test_real_data_smoke.py` | Create | `smoke`+`db`+key-gated: real `data/` ingest, ≥1 real contradiction |

## Testing Strategy

TDD per `practices/GL-TDD.md`, red→green per unit. Unit tests mock all external services
(Voyage/Anthropic injected stubs; a minimal `FakeRepo` test double implements only the
Repository methods each test touches). Determinism: no real network, no real DB, no
random/time-dependent assertions.

1. **embed** — stub client; assert batching (N texts → N vectors in order), every vector
   length 1024, a wrong-length vector raises, empty input → empty output.
2. **schemas** — valid `ExtractionOut` builds; `subject_type`/`link_type` outside the
   contract enums reject; non-ISO `as_of` rejects; `confidence` clamped/validated.
3. **prompts** — `render("extract_claims", **vars)` returns the file contents with vars
   substituted; unknown prompt name raises a clear error; the prompt file exists on disk.
4. **llm** — stub returns valid JSON → parsed object; stub returns bad-then-good →
   one repair, object returned; bad-twice → `None` and a logged drop (assert via `caplog`).
5. **extractor** — stub LLM → `ExtractionOut`; an item with an unknown enum is dropped,
   valid siblings survive; observability fields logged.
6. **resolve** — `FakeRepo.resolve_entity` mimics roster semantics (two seeded Marias,
   both `location="São Paulo"`, depts Sales vs Customer Success): bare "Maria" + no context
   → `None`, **no entity created**; "Maria" + `{"department":"Customer Success"}` → Santos;
   **"Maria" reached from a `customer_success` path token** → normalized to `Customer
   Success` → Santos (the C1 regression test — proves the path→department map, not just the
   easy single-token "Sales" case); a `{"location":"São Paulo"}`-only context still returns
   `None` (location does not disambiguate — the H2 negative test); accented "João" folds to
   "Joao"; a new "Cosmos Hotels" (customer) is created `seeded=False`; an unresolved bare
   person name is **not** created.
7. **contradict** — `FakeRepo.get_claims` (returning `Claim`s with **non-`None` ids**) gives
   two conflicting revenue claims → one `add_contradiction` with the right `kind` per the
   decision tree (equal `as_of`+diff doc → `source_disagreement`; diff `as_of` → `temporal`;
   else `value_conflict`); equal values → none; `claim_a_id`/`claim_b_id` `None` → skipped;
   assert no claim is mutated (no-collapse). `FakeRepo.canonical_predicate` delegates to
   `metric_vocab.canonical_key` so "ARR"/"annual recurring revenue" group.
8. **pipeline** — fake `discover`+connector+embedder+extractor+`FakeRepo`: one document
   flows through to claims/links/contradictions; **chunks reach `add_chunks` with
   `document_id` set** (asserted) [H-2]; a second `run` adds zero rows (idempotent); an
   injected `already_ingested` returning `True` skips embed+extract for that hash. Edge
   cases [architect M4]: empty chunk list → clean no-op; an extractor returning empty/all-
   dropped `ExtractionOut` → zero claims, no crash; a chunk whose every mention resolves to
   `None` → zero claims written + logged.
9. **integration (DB-gated)** — on a freshly-migrated DB, the test **explicitly seeds
   `metric_vocab` and the needed entities** (the `pg_repo` fixture TRUNCATEs `metric_vocab`,
   so without this seeding canonicalization silently no-ops) [architect H5]. A **stub
   extractor** emitting two same-subject revenue claims with different values from two
   documents persists a real `contradictions` row (`value_conflict`/`source_disagreement`);
   a second run is a no-op; a **same-`source_uri`** newer-`as_of` claim supersedes (old row
   kept, `valid_to`/`superseded_by` set, **not** deleted), while a **different-`source_uri`**
   conflicting value yields a contradiction, **not** a supersession [architect H4]. Auto-
   skips without `DATABASE_URL`.
10. **real-data smoke (`smoke`+`db`+key-gated)** — explicit `skipif` for `ANTHROPIC_API_KEY`
    and `VOYAGE_API_KEY` (the `db` mark only gates `DATABASE_URL`; there is no auto key-skip)
    [Stage-3 M-2]. Runs the real pipeline over a handful of real `data/` files when all three
    are present; asserts ≥1 contradiction surfaces. Auto-skips here.

## Success Criteria

- [ ] `helixpay/ingest/{embed,pipeline,resolve,contradict}.py` and `extract/**` import cleanly
- [ ] Every LLM call uses a named prompt in `prompts/` + a structured-output schema with
      validate-and-repair-or-drop; repair outcome is logged (no free-form trust)
- [ ] Resolution is roster-first; the two Marias / two Tans disambiguate via context; an
      ambiguous bare name with no context yields `None` (no silent pick, no duplicate)
- [ ] Predicates canonicalize via `metric_vocab` before write
- [ ] Contradiction detection writes first-class rows; conflicting claims coexist (never
      collapsed); superseded facts set `valid_to`/`superseded_by` (never deleted)
- [ ] Pipeline is idempotent (second run adds zero rows) and injectable (no Agent 1 / DB /
      keys needed for the unit suite)
- [ ] Embeddings are 1024-dim, batched, injectable, dim-validated
- [ ] `test/unit/ingest/**` green with no DB/keys; integration tests authored + gated
- [ ] `mypy helixpay/ingest` clean; existing suite still green

### Doc Reconciliation Checklist

Meta-docs are orchestrator-owned (fan-out README); I touch none. Reconciliation happens at
integration. My delivery report carries: prompt inventory, the structured-output schema,
resolution accuracy on the name traps, contradictions found, and any new gotchas for
`CLAUDE.md`.

## Review Log

### Pre-Implementation Review
- **Iteration 1** (2026-06-09): architect-reviewer found 1 CRITICAL, 5 HIGH, 4 MEDIUM, 3 LOW. Files reviewed: workspace/sprints/SP_003_extraction.md, fanout/AGENT_2_extraction.md, CLAUDE.md §7, HELIXPAY_BUILD_SPEC.md §2/§4/§5/§8, helixpay/contracts/{models,repository,connector}.py, helixpay/db/repository.py, helixpay/db/schema.sql, helixpay/seed/{roster,metric_vocab}.py, helixpay/config.py, fanout/AGENT_1_loaders.md, test/conftest.py, data/org-chart.md, data/email/cosmos-hotels-debrief.md, data/interviews/**.
- **Iteration 2** (2026-06-09): code-reviewer (independent context) found 3 CRITICAL, 5 HIGH, 5 MEDIUM, 3 LOW. Files reviewed: workspace/sprints/SP_003_extraction.md, helixpay/contracts/{models,repository}.py, helixpay/db/repository.py, helixpay/config.py, helixpay/seed/{roster,metric_vocab}.py, test/conftest.py, pyproject.toml, fanout/README.md, fanout/AGENT_1_loaders.md.

**Resolution — all CRITICAL and HIGH addressed in the plan:**
1. **C1 (architect) / H-4 (code): two Marias don't disambiguate by location, and `customer_success` ≠ `Customer Success` under `_filter_by_context` substring matching** — Key decision 3 now makes `department` the discriminator, restricts context to roster attribute keys (`department`/`location`/`role`), and adds a path→department normalization map; resolve test #6 adds the Maria-Santos-from-`customer_success`-path case and a location-only negative.
2. **C-1 (code): `get_claims` takes `subject_id:int`, not a name** — Key decision 6 resolves to `Entity` and uses `entity.id` (asserted non-`None`).
3. **C-2/C-3 (code): `get_sources` returns `list[Citation]`; `Claim.id` is `Optional`** — Key decision 7 uses `cites[0].source_uri if cites else None` and guards `E.id is not None`; FakeRepo returns non-`None` ids (test #7).
4. **H1 (architect): Cosmos "120K vs 165K would-have-been" false contradiction** — counterfactual/hypothetical values are suppressed at extraction (prompt) and a negative test asserts the Cosmos chunk yields ≤1 `arr` claim and zero contradictions (Key decision 6).
5. **H2 (architect): `_filter_by_context` precision** — context keys enumerated as a subset of seeded attribute keys; a non-disambiguating context still returns `None` (negative test).
6. **H3 (architect): "content_hash short-circuits" not met** — surfaced honestly: injectable `already_ingested` seam + a proposed `Repository.get_document(content_hash)` contract addition in the delivery report, rather than forking the frozen contract (Key decision 8).
7. **H4 (architect) / L-1 (code): supersession `None`-`as_of` + same-vs-different source** — Key decision 7 skips supersession when either `as_of` is `None` or the `source_uri` differs; integration test #9 asserts same-uri→supersede (not deleted), different-uri→contradiction.
8. **H5 (architect): `pg_repo` truncates `metric_vocab`** — integration test #9 explicitly seeds `metric_vocab` + entities so canonicalization actually fires.
9. **H-1/H-2 (code): loader tuple semantics + `chunk.document_id` before `add_chunks`** — Cross-agent notes pin `(connector, path)`→`connector.load(path)`; pipeline test #8 asserts `document_id` is set.
10. **H-3 (code): FakeRepo.canonical_predicate** — wired to `metric_vocab.canonical_key` (no DB), test #7.
11. **H-5 (code): ContradictionKind decision tree overlap** — restated as a non-overlapping tree (Key decision 6).

**MEDIUM/LOW folded in:** `## Dependencies` section added (M-1); key-skip `skipif` for the smoke test (M-2); `helixpay/ingest/__init__.py` ownership + `prompts/**` notes (M-3/L-3); pure `canonical_key` vs `repo.canonical_predicate` split (M-4); `add_contradiction` non-`None` guard (M-5); value-claims-vs-links natural-key collision (architect M3); package-anchored prompt path + CWD-independence test (architect M2); edge cases enumerated — empty chunks / all-dropped / no-resolution (architect M4); `confidence` clamp decision (L1); logs carry ids/counts not raw bodies (L2); embed length-mismatch failure mode documented (L-2). Loader seam shape (architect M1) pinned.

**Deferred (non-blocking, tracked in delivery report):** cross-run cost-skip of unchanged documents pending the proposed `Repository.get_document` seam (H3); deep figure/image extraction stays caption-level (spec §11 scope cut, Agent 1's seam).

### Post-Implementation Review
- **Iteration 1** (2026-06-09): code-reviewer + debugger, both plan-blind (code+tests only, no plan). Combined they found 2 CRITICAL, 4 HIGH, ~6 MEDIUM, several LOW. Files reviewed: helixpay/ingest/{embed,pipeline,resolve,contradict}.py, helixpay/ingest/extract/{schemas,prompts,llm,extractor}.py, prompts/extract_claims.md, test/unit/ingest/*, test/integration/ingest/*.
- **Iteration 2** (2026-06-09): code-reviewer, plan-blind. Found 0 CRITICAL, 0 HIGH, 1 MEDIUM, 2 LOW. Files reviewed: same source + tests.
- **Iteration 3** (2026-06-10): code-reviewer, plan-blind, over the research-driven enhancement round (gleaning + grounding gate + schema reorder). Found 0 CRITICAL, 1 HIGH, 1 MEDIUM, 2 LOW. Files reviewed: helixpay/ingest/extract/{extractor,grounding,schemas}.py, prompts/{extract_claims,glean_claims}.md, helixpay/ingest/pipeline.py, test/unit/ingest/{test_extractor,test_grounding}.py. Resolved: HIGH — `grounding._NUM_CANDIDATE` matched a digit inside a token (`Q1`→`1`), added a `(?<![A-Za-z\d])` lookbehind (mirrors `_PURE_NUM_RE`) + test; MEDIUM — `_claim_key` omitted `as_of`, so gleaning could collapse a same-value/different-date claim — added `as_of` to the key + test; LOW — added relation-dedup, multi-pass-both-add tests. Re-verified: 110 passed / 14 skipped, mypy clean (27 files), DB integration green against a live pgvector container.

## Research-Driven Enhancements (post-gate, validated round — 2026-06-10)

After a GitHub/literature best-practices report (`research/extraction-design-and-best-practices.md`)
compared this design against Graphiti/GraphRAG/etc., I validated each recommendation with three
independent subagents (against the *frozen contracts*), then implemented the validated subset:

- **Gleaning (recall) — IMPLEMENTED.** Optional fixed follow-up extraction passes feed the
  already-extracted items back ("what's missing?") and merge new ones (deduped on
  `(subject, predicate, object_value, as_of)`). Off by default (`glean_passes=0`); production
  ingest sets `1`. Token-budget guard; a failed/empty gleaning pass stops the loop and never
  discards the base pass. New named prompt `prompts/glean_claims.md` (no inlined prompt).
- **Evidence grounding gate (precision) — IMPLEMENTED, narrowed.** `extract/grounding.py`
  grades each claim's value restorability against its cited evidence span (reusing
  `normalize_value`) + span-locality in the chunk. A subagent correctly flagged the report's
  "hard-drop" version as **net-negative for recall** (dashboard value/label/as-of live in
  separate DOM nodes), so the gate **flags-and-penalizes confidence, never drops**, and
  excludes `as_of` from grading. `evidence` stays Optional in the schema (required in the
  prompt).
- **Schema field reorder (LOW) — IMPLEMENTED.** `ClaimOut` emits `evidence` before
  `object_value`/`confidence` (generation-order effect); prompt JSON example matched.
- **Embedding-ANN entity resolution (MEDIUM) — DEFERRED (contract-blocked).** The frozen
  `entities` table has no embedding column and `Repository` exposes no list/ANN-entities
  method, so this needs a gate re-freeze. **Proposed contract change** for the orchestrator:
  add `entities.embedding VECTOR(1024)` (+ HNSW) and a
  `Repository.search_entities(qvec, k, entity_type=None) -> list[tuple[Entity, float]]` method.
- **NLI semantic contradictions (LOW) — DEFERRED** (only if eval shows missed non-numeric
  contradictions; avoids a heavy model dependency).
- **Don't gate on self-reported confidence / don't auto-resolve contradictions — CONFIRMED
  COMPLIANT** in code (confidence stored-only; contradictions surfaced, never resolved).

**Resolution — all CRITICAL/HIGH fixed; tests added; full suite re-run green (incl. against a live pgvector container):**
1. **`normalize_value` parsing defects (CRITICAL):** the old `_NUM_RE` pulled a stray digit from labels and treated `"18 months"` as `18M`, ignored the Unicode minus `−` (U+2212), and turned `"Q1 2026"` into `1.0`. Replaced with a **pure-number gate** (numeric only when the whole cleaned string is a number) + Unicode-minus normalization (applied to both the numeric and the text-comparison path). New tests: `18 months ≠ 18M`, `Q1 2026/v1.0 non-numeric`, `−11% == -11%`, unicode-minus text fallback.
2. **`roster_hint` always empty (CRITICAL):** the prompt advertised a roster section that was never populated. Added a caller-injectable `roster_hint` seam to `pipeline.run` threaded into `ChunkContext` (the frozen `Repository` has no entity-listing method, so it can't be auto-built without a contract change; resolution still enforces the roster downstream). Prompt reworded ("may be empty"); test asserts the hint reaches the extractor.
3. **`classify` mislabeled undated cross-source conflicts as `temporal` (HIGH):** restructured the decision tree so different-document + period-compatible (equal or either-undated `as_of`) is `source_disagreement`. New test.
4. **`values_conflict(None, x)` false positive (HIGH):** a missing value is no longer treated as a competing fact (None-guards). New test.
5. **Self-loop relation links (HIGH):** the pipeline now drops a relation whose endpoints resolve to the same entity (protects the recursive-CTE org graph). New test.
6. **`detect()` re-counted existing contradictions on re-run (found by running the integration test against a REAL pgvector DB — the FakeRepo hid it):** `detect` now dedups against `get_contradictions(subject_id)` so a re-run writes/returns zero. Unit + DB integration idempotency assertions tightened.
7. **MEDIUM/LOW:** honorific-only mention (`"Dr."`) no longer mints a junk entity; contradict-test FakeRepo dedups contradictions to mirror the repo; prompt fence instruction de-contradicted; dead test setup removed.

**Validation:** unit suite 61 ingest tests (88 repo-wide) green with no DB/keys; with a live `pgvector/pgvector:pg16` container the **full suite is 101 passed / 1 skipped** (the 1 skip is the API-key-gated real-data smoke), exercising the real SQL for upsert/add_chunks(pgvector)/resolve/canonicalize/add_claim/add_contradiction(ON CONFLICT)/supersede/get_sources. `mypy helixpay` clean (26 files).

**Deferred (LOW, non-blocking):** different-`as_of` + overlapping-window + different-document pairs are labeled `temporal` (a defensible labeling choice, contradiction still written); cross-run cost-skip of unchanged documents pending the proposed `Repository.get_document(content_hash)` seam (the injectable `already_ingested` seam covers it when a checker is supplied).
