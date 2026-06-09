# SP_004 Delivery Report — Query Brain (Agent 3)

Branch `sprint/SP_004-query` · worktree `.claude/worktrees/SP_004` · tier Foundational.
Implements the `QueryEngine` Protocol over the frozen `Repository`, built and
tested against the seeded fixture DB.

## What landed (owned paths only)
- `helixpay/query/` — `retrieval.py`, `temporal.py`, `planner.py`,
  `contradictions.py`, `synthesis.py`, `graph.py`, `clients.py`, `engine.py`,
  `prompts/ask_synthesis.md`, `__init__.py` (lazy export of `HelixQueryEngine` +
  `build_default_engine`).
- `test/unit/query/**` (44 tests) + `test/integration/query/**` (5 db-marked).

## Verification
- `uv run pytest test` → **87 passed** with a live pgvector container
  (migrate + `seed_all`); **66 passed / 16 auto-skipped** without `DATABASE_URL`
  (the conftest DB-skip contract). `uv run mypy helixpay` → clean (25 files).
- Lifecycle: pre-impl gate PASS (SP_004); Stage 3 = 2 independent plan reviews
  (architect + code), Stage 5 = 2 independent **plan-blind** reviews (code +
  security); post-impl gate PASS; worktree-isolation + sprint-overlap PASS.
- The acceptance behaviour runs for real on the fixture: `ask("What was
  HelixPay's Q1 2026 revenue?")` surfaces the planted value-conflict (dashboard
  14.2M vs board deck 13.9M) with **both sides attributed** and **two
  `as_of`-stamped citations**; `get_org_chart()` root resolves to Wei Chen.

## Planner routes
Cheap lexical classification → `{structured | retrieval | both}` (`planner.py`):
- **structured** — a bare reporting-line question (hierarchy cue, no freshness /
  contradiction / ownership cue).
- **both** (the common case) — any metric/value question, ownership question,
  contradiction question, a hierarchy question carrying a freshness cue
  ("as of"/"latest"), or a question naming a proper noun.
- **retrieval** — open narrative with no structured anchor.
Two deliberate rules from review: a **metric question always probes
contradictions** even without the word "disagree" (that is where the planted
conflict hides), and a hierarchy+freshness question routes to `both` so the
temporal/staleness path runs.

## RRF weighting
Equal-weight reciprocal-rank fusion of `search_semantic` + `search_lexical`,
`score = Σ 1/(RRF_K + rank)`, **RRF_K = 60**, 1-based rank, deterministic
tie-break on ascending chunk id. RRF (not a trained reranker — explicit scope
cut, spec §11) because it ranks by *position*, so a 0..1 cosine and an unbounded
`ts_rank` fuse without scale normalisation, and it needs no training/model.

## No-uncited-claims enforcement mechanism
1. **Grounding** (`synthesis.build_grounding`): facts are numbered — governed
   claims `[C#]` (carry `claim_id`, citeable), retrieved chunks `[S#]` (context
   only).
2. **Synthesis** (`clients.AnthropicSynthesizer`, `claude-opus-4-8`): a named
   prompt (`prompts/ask_synthesis.md`) + a forced structured-output tool whose
   `input_schema` is `SYNTH_SCHEMA` (`sentences[].text` + `sentences[].cites`).
   No free-form prose path.
3. **Enforcement** (`synthesis.enforce_citations`): a factual sentence is kept
   **only** if it cites at least one `[C#]` claim marker; markers are mapped to
   `Citation` via `repo.get_sources`. Unknown / non-claim / chunk-only / malformed
   markers cannot become a citation, so the answer is structurally guaranteed to
   contain zero uncited claims; if nothing survives, a safe fallback answer with
   no citations is returned. Type-defensive against malformed/adversarial model
   output (never crashes, never fabricates a citation).

Contradictions are attached to `AnswerBundle.contradictions` **independently of
synthesis** (first-class, present-and-empty, never hidden), with both
`claim_a_id`/`claim_b_id` carried so each side is attributed.

## Observability (Agent 6 reads this)
Each `ask` logs `ask.trace` and stashes `engine.last_trace`:
`{route, retrieved_chunk_ids, subject_ids, cited_claim_ids, contradiction_ids}`
— integer ids only (no secret, connection string, prompt body, or claim values).

## Contract friction (flagged, NOT forked — a contract change re-freezes the gate)
1. **No alias read.** `EntityDetail.aliases` cannot be populated through the
   frozen Protocol (`resolve_entity` is mention→entity only; no
   `get_aliases(entity_id)`), and raw SQL is confined to `helixpay/db/`.
   `get_entity` returns `aliases: []`. **Recommend** `get_aliases(entity_id) ->
   list[str]`.
2. **No link/chunk provenance for citations.** `get_sources` is claim-only, and
   seeded reporting `links` carry no `source_chunk_id`; `Chunk` omits
   `source_uri`/`as_of`. So purely structural (org-hierarchy) answers and
   purely chunk-narrative answers are not citeable on the current fixture —
   citeable facts are **claims**, which is the ontology's design; those answers
   become fully cited once extraction (Agent 2) writes claims for them.
   **Recommend** `get_link_sources(link_ids)` and/or
   `get_chunk_sources(chunk_ids) -> list[Citation]`.
3. **No batched/filtered reads (perf).** Subject resolution is one
   `resolve_entity` per question term and entity-link reads use `get_links()` +
   Python filter. Capped (`_MAX_TERMS=40`, `_MAX_SUBJECTS=6`); fine at this
   corpus size. **Recommend** `resolve_entities(names)`,
   `get_links(from_entity_id=…)`, `get_entity_by_id(id)`.

## Deviations / gotchas for the orchestrator
- **Prompt location.** Query synthesis prompt lives at
  `helixpay/query/prompts/ask_synthesis.md`, not the top-level `prompts/` (owned
  by Agent 2). Justified deviation from the literal CLAUDE.md §7 "in `prompts/`"
  wording (stricter-rule reading on ownership) — recorded here for the §301
  adversarial stage.
- **Dependencies (consolidate at merge).** `anthropic`, `voyageai` — NOT added to
  `pyproject.toml` by this slice. Both are **lazy-imported inside the client
  methods** via `importlib`, so the package imports and the whole test suite run
  without them (and mypy stays clean without stubs).
- **`scripts/dev-gateway.py --stage manual` fails its `python-tests` step** here
  because it invokes **system `python3`**, which has no project deps installed
  (`ModuleNotFoundError: psycopg`). This is a project-wide toolchain mismatch
  (the authoritative command per CLAUDE.md §7 is `uv run pytest test`, which is
  green) affecting every agent equally, not a defect in this slice. Run the
  gateway under the uv env (or point its test command at `uv run pytest`).
- **PROGRESS.md** carries a worktree-local `**Current:** SP_004` pointer so the
  sprint gate validates this sprint; the orchestrator reconciles PROGRESS.md and
  the other meta-docs at integration.

## Hand-off to Agent 4 (exposure)
Public surface is exactly the `QueryEngine` Protocol —
`ask/get_entity/get_org_chart/find_contradictions`. Construct with
`helixpay.query.build_default_engine(repo)` (real Voyage/Anthropic seams, keys
read lazily on first use) or inject your own `Embedder`/`Synthesizer`. Agent 4
can drop its mock for the real engine without surface changes.
