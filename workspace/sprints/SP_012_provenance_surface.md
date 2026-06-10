---
sprint_id: SP_012
tier: Standard
features: [chunk-citation-close, consensus-dissent, contradiction-typing, verbatim-citations]
user_stories: []
schema_touched: false
structure_touched: false
status: Complete
isolation: branch-only
branch: sprint/SP_012-provenance-surface
worktree: ""
agent_owner: "Agent D (provenance-surface)"
fix_type: ""
dependencies: []
dev_dependencies: []
touches_paths:
  - helixpay/query/synthesis.py
  - helixpay/query/contradictions.py
  - helixpay/query/consensus.py
  - helixpay/query/engine.py
  - helixpay/query/prompts/ask_synthesis.md
  - test/unit/query/**
touches_checklist_items: [surface-chunk-citation, surface-link-citation, surface-consensus-dissent, surface-contradiction-typing, surface-verbatim-cites]
---

# SP_012: Provenance Surface + Answer UX (query side)

> **Depends on SP_009** (consumes `get_link_sources`/`get_chunk_sources`, the typed
> `Contradiction` link refs, and `Claim.evidence`). Benefits from SP_011 populating the
> data, but is independently testable against fakes. Branch from the post-SP_009 commit.
> Does **not** edit contracts, schema, or `db/repository.py`.

## Sprint Goal

Turn the now-captured provenance into what the user/agent actually sees, closing the
answer-layer gaps from `research/provenance-evidence-and-ux-pipeline-design.md` (gap 5
+ the surface half of gaps 1, 3, 4) and `research/query-design-and-best-practices.md`
(chunk-citation hole, contradiction typing):

1. **Close the chunk-citation hole.** `[S#]`-grounded answer sentences currently fall
   back to a non-`Citation` string because only claims had a provenance path. Route them
   through `Repository.get_chunk_sources` (SP_009) so every grounded sentence becomes a
   real `Citation`.
2. **Link citations.** When an answer rests on a relationship (`reports_to`/`owns`),
   attach link citations via `get_link_sources` instead of leaving relationship answers
   uncited (gap 3, surface half).
3. **Consensus / dissent rollup** (gap 5). Group claims by canonical predicate +
   normalized value (shared `helixpay.ingest.normalize`); present the consensus value
   with its corroborating-source count and freshest `as_of`, list genuine dissent
   separately. Turns "runway = 7 raw claims" into one clean, ranked answer.
4. **Type contradictions before synthesis.** Label each surfaced conflict
   `temporal | value | opinion/source_disagreement` and pass the type into the
   synthesis prompt (DRAGged-style, +5–9pp articulation per the query doc). Surface link
   contradictions (from SP_011) alongside value ones.
5. **Verbatim-span citations.** Now that `Claim.evidence` is persisted, emit the exact
   supporting substring per cited claim (FRONT/LongCite pattern) so citations *quote the
   fact* instead of a chunk prefix.

## Current State

- `synthesis.py:15` — provenance is claims-only; `[S#]` chunk-grounded sentences drop to
  a fallback string. Contradictions are surfaced **untyped**. No consensus rollup; the
  answer can echo N near-duplicate claims. `Citation.snippet` is the chunk prefix.

## Desired End State

- Every grounded sentence (claim- or chunk- or link-derived) carries a real `Citation`;
  citations quote the verbatim evidence span where available; contradictions are typed
  and include relationship conflicts; one consensus answer with explicit dissent.
- Verified on the SP_010 replay tier + query unit fakes ($0; one Opus synth call only for
  a live `ask` smoke).

## Scope

In: `helixpay/query/**` + the synthesis prompt. Out: repository methods + schema
(SP_009), write-path persistence (SP_011), eval scoring of these (SP_013).

## Technical Approach

Pinned at Stage-3 review (decisions below are binding on the implementation):

- **Citations** — `enforce_citations` keeps its **4-tuple** `(answer, citations,
  cited_claim_ids, confidence)`; `cited_claim_ids` stays **claim-only** (the trace +
  confidence depend on it). Markers are resolved up-front to real `Citation`s
  (`get_sources` for `[C#]`, `get_chunk_sources` for `[S#]`, `get_link_sources` for
  `[L#]`); a sentence is kept **iff** ≥1 of its markers resolved to a real citation — so
  a chunk/link cite is no longer "uncited" (closes the hole) but an unresolved marker
  still cannot fabricate a citation (the malformed-output security test still holds).
  Combined citations are de-duped on `(claim_id, chunk_id, link_id, source_uri)`.
  `build_grounding` gains `links` + a `name_map` (kw-defaulted — old positional calls
  unchanged); `GroundingFact` gains a frozen `evidence` field set at construction, and
  `enforce_citations` overrides each claim `Citation.snippet` with `claim.evidence` via
  `model_copy` (verbatim-span, Feature 5). `[L#]` lines render `link_type: <from> →
  <to>` using `name_map`, falling back to `#<id>` (id→name Protocol friction, same
  stance as `graph.py`).
- **Consensus** — a pure, no-LLM grouping step in a **new** `helixpay/query/consensus.py`
  (added to `touches_paths`; keeps `build_grounding` from overloading). Group by
  `canonical_predicate(p)` first, then bucket members with `values_equal` (handles the
  numeric vs canonical-text split: `eighteen months`≡`18 months`). Consensus = largest
  bucket (deterministic tie-break: freshest `as_of`, then count, then min claim id);
  emit `{predicate, consensus_value, corroborating_count, freshest_as_of, member_ids,
  dissent[]}`. `freshest_as_of` uses `(as_of or date.min)` and is `None` when all undated.
  Rendered into the grounding text by a `synthesis.render_consensus` sibling, referencing
  the `[C#]` markers — dissent values stay present and individually citeable (never
  collapsed).
- **Typing** — `contradictions.label_for(c, claims_by_id)` (pure; no DB read): **trust
  `Contradiction.kind`** when set (`value_conflict`→"value", `temporal`→"temporal",
  `source_disagreement`→"source disagreement"); only when `kind is None` infer "temporal"
  (both sides dated and differ) else "value"; a link-pair conflict → "relationship".
  `engine` builds `claims_by_id` (it already gathers both sides) and threads the typed
  contradictions into a `synthesis.render_contradictions` block referencing the markers.
  Link-contradiction sides are made citeable by pulling their links into the `[L#]`
  grounding via `get_link_sources` (so both sides are attributed — H4).

## Testing Strategy

- `test/unit/query/test_synthesis.py` — `[S#]` sentence → real `Citation`; verbatim
  snippet equals the claim's evidence; no-uncited-claims guard still holds.
- `test/unit/query/test_contradictions.py` — conflicts carry a type label; link
  contradictions surface; `AnswerBundle.contradictions` present-and-empty when none.
- `test/unit/query/test_engine.py` — consensus rollup collapses 7 runway claims to one
  consensus + dissent; corroborating count + freshest `as_of` correct.
- Live smoke (1 synth call): `helixpay ask "what is the runway?"` → consensus answer,
  verbatim citation; `helixpay ask "when does Confluence GA?"` → typed temporal
  contradiction with both sides cited.

## Risks & Mitigations

- *Consensus rollup hides a real contradiction* → rollup groups by normalized value;
  genuine disagreement becomes `dissent[]`/a `Contradiction`, never collapsed (CLAUDE.md
  "never collapse conflicting facts").
- *Fakes drift from the real repository surface* → unit fakes implement exactly the new
  `get_chunk_sources`/`get_link_sources` signatures from SP_009.
- *Reranker temptation* → out of scope by decision (recall report: retrieval is not the
  bottleneck). Not in this sprint.

## Success Criteria

- Grounded sentences cite real sources incl. chunks + links; citations quote evidence;
  contradictions typed + include relationship conflicts; consensus/dissent answer shape.
- `uv run pytest test` green; `uv run mypy helixpay` clean; live `ask` smoke passes.

### Pre-Implementation Review

> Standard tier — floor = 2. Reviewers independent (architect-reviewer + code-reviewer),
> plan-over-code. Verdict: **GO-WITH-CHANGES**; all blocking findings folded into the
> Technical Approach above before any code.

- **Iteration 1** — architect-reviewer, plan-vs-code, verdict GO-WITH-CHANGES. Files reviewed: synthesis.py, contradictions.py, engine.py, prompts/ask_synthesis.md, contracts/{models,repository}.py, ingest/normalize.py, temporal.py, test/unit/query/*. CRITICAL: (C1) fakes lack `get_chunk_sources`/`get_link_sources` and `get_links(from_entity_id)` → extend `FakeRepository` first; (C2) `[L#]` grounding + id→name friction unspecified → pin (render via `name_map`, fall back to `#id`); (C3) Feature 1 inverts the chunk-only guard coherently (chunk cite = real source) but the synthesis docstring + prompt must be rewritten and `test_chunk_only_citation_is_not_accepted` intentionally replaced. HIGH: keep 4-tuple + `build_grounding(claims, chunks)` back-compat (H1); don't overload `build_grounding` — split renderers (H2); consensus in a new module, not engine (H3). MEDIUM: fix prompt path (M1); trust stored `kind`, infer only on `None`, align labels to the enum (M2); group on `(canonical_predicate, normalized_value)` + add a no-merge test (M3). Resolution: all accepted; `touches_paths` corrected to `helixpay/query/prompts/...` and `helixpay/query/consensus.py` added.
- **Iteration 2** — code-reviewer, correctness/edge-cases, verdict GO-WITH-CHANGES. Files reviewed: synthesis.py, contradictions.py, engine.py, prompts/ask_synthesis.md, contracts/{models,repository}.py, ingest/normalize.py, test/unit/query/{fakes,test_synthesis,test_engine,test_contradictions}.py. CRITICAL: (C1) keep `cited_claim_ids` claim-only, merge chunk/link cites only into element 2 so the trace + security test (`all(c.source_uri ...)`) stay green; (C2) add `evidence` to `GroundingFact` (frozen → set at construction) and `model_copy` the snippet; (C3) fix the fake signatures before feature tests. HIGH: bucket via `values_equal` not a raw dict key (H1); link-contradiction sides (`claim_*_id` None) must be cited via `get_link_sources` or they surface uncited (H4); typing needs the claim map, do it where the map exists (H3). MEDIUM: guard `freshest_as_of` against `None` `as_of` via a `date.min` sentinel (M1); append consensus/contradiction blocks into `{grounding}` rather than add a placeholder, avoiding the silent-unexpanded trap (M2); de-dup mixed citations (M3); expose the rollup as a standalone function + assert the grounding text carries the summary (M4). Resolution: all accepted and folded in; confirmed out-of-scope — `test/golden` uses its own self-contained `FakeRepo.ask`, never instantiates `HelixQueryEngine`, so no `touches_paths` widening needed.

> **Isolation note (Rule 7 reconciliation):** declared `git-worktree` reconciled to
> `branch-only` — no parallel sprint is active (SP_011/013/014 are Planning), matching
> the immediately-preceding Standard sprint (SP_010) which worked branch-only in the main
> checkout. WI-1/WI-2 satisfied (distinct sprint-id branch, no peer collision).

### Post-Implementation Review

> Standard tier — floor = 2. Both reviewers plan-blind (given only the changed code +
> tests, never this plan). Tests green (351 passed, 36 skipped) and `mypy` clean after
> the fixes below.

- **Iteration 1** — code-reviewer, plan-blind, correctness/edge-cases. Files reviewed: helixpay/query/{synthesis,consensus,contradictions,engine}.py, helixpay/query/prompts/ask_synthesis.md, test/unit/query/{fakes,test_synthesis,test_consensus,test_contradictions,test_engine}.py. HIGH: (H1) the `_MAX_CLAIM_FACTS` cap could drop a contradiction side, making the conflict unattributable in grounding — a silent half-resolution; (H2) `render_contradictions` could emit an unattributed conflict line when neither side has a marker. MEDIUM/LOW: (M3) `label_for` should pass an unknown stored `kind` through rather than re-derive; (M4) tests should assert `[C#]` markers appear in the consensus/contradiction prompt blocks; (L1) consensus representative could be a null value. Verified clean: `model_copy` snippet override (pydantic v2), import layering (no cycle), tie-break determinism, `_valid_markers` malformed-output guards. **Resolution:** H1 fixed (contradiction sides retained in full; cap bounds only the remainder + a regression test on `_gather_claim_facts`); H2 fixed (skip unattributable lines — the conflict still rides on `AnswerBundle.contradictions`); M3/L1 fixed; M4 assertions added.
- **Iteration 2** — security-auditor, plan-blind, LLM trust-boundary (OWASP LLM01/LLM05). Files reviewed: helixpay/query/{synthesis,consensus,contradictions,engine}.py, helixpay/query/prompts/ask_synthesis.md. Verdict: the four guarantees hold — no path fabricates a citation, malformed/adversarial model output never crashes `enforce_citations`, the degraded `synthesize` path logs only the route enum (no prompt/secret leak), single-pass `render_prompt` keeps attacker-controlled grounding from smuggling a placeholder, and resource use is capped (O(N²) bucketing bounded by the 50-claim cap). MEDIUM: model-controlled `confidence` was parsed but not clamped — `NaN`/`inf`/out-of-range propagated to `AnswerBundle.confidence` (improper output handling). LOW (advisory, not taken): defensive `isinstance` on evidence, note-length truncation. **Resolution:** MEDIUM fixed — `confidence` now rejects non-finite and clamps to `[0,1]`, `SYNTH_SCHEMA` gains `minimum/maximum`, covered by adversarial tests (`inf`, `99.0`, `"high"`).

## Close-out

- **Verification (Stage 13):** `uv run pytest test` → 351 passed, 36 skipped; `uv run
  mypy helixpay` → clean; `uv run python scripts/dev-gateway.py . --stage ci` → all checks
  PASS (run under `uv` so the gateway's `sys.executable` is the project venv — system
  python lacks `psycopg`/`mcp`). All five features land on the **$0 unit/fakes tier**; the
  fakes implement the exact SP_009 `get_chunk_sources`/`get_link_sources`/`get_links(from_entity_id)`
  surface.
- **Live `ask` smoke — PENDING operator smoke** (no `DATABASE_URL`/API keys in this
  environment; the smoke needs an ingested DB + one Opus call). Exact steps once a seeded
  DB is available: `helixpay ask "what is the runway?"` → expect one consensus value with
  corroborating count + a verbatim citation; `helixpay ask "when does Confluence GA?"` →
  expect a typed temporal contradiction with both sides cited. No `fix_type`, so Rule 21
  behavioral-closure does not gate completion; the answer-shape logic is fully covered by
  unit tests.
- **Doc note:** `FEATURE_LIST.md` `last-reconciled` advanced to `2026-06-11` — a same-day
  reconciliation artifact (SP_010 already consumed `2026-06-10` at this branch's base, and
  F-4 enforces a strictly-increasing marker). The validator's corrective-reset path can
  realign it on the next sprint.

## Hand-off (to SP_013)

- New answer shape (typed contradictions, consensus/dissent, verbatim citations) is the
  target the eval upgrades assert against. The pure `consensus.rollup` and
  `contradictions.label_for` are reusable by the eval matcher.
