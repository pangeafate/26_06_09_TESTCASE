# Agent 2 — Extraction & ontology (SP_003, FOUNDATIONAL — critical path, longest pole)

You are Agent 2. You are the heart of the project: per chunk, an LLM emits **claims +
relations** under a strict structured-output schema with a validate-and-repair loop;
you resolve entities against the seeded roster, canonicalize predicates, detect
contradictions, and own the end-to-end **ingestion pipeline**. This is the
highest-blast-radius slice — run the **full Foundational lifecycle**. Read `CLAUDE.md`
(esp. §7 ontology rules), `AGENTS.md`, `HELIXPAY_BUILD_SPEC.md` §5 (Agent 2) + §2, and
`fanout/README.md`.

## Setup
- Worktree: `git worktree add .claude/worktrees/SP_003 -b sprint/SP_003-extraction main`
- Sprint plan `workspace/sprints/SP_003_extraction.md` — `tier: Foundational`,
  `isolation: git-worktree`,
  `touches_paths: [helixpay/ingest/extract/**, helixpay/ingest/pipeline.py, helixpay/ingest/embed.py, prompts/**, test/unit/ingest/**, test/integration/ingest/**]`.
- Foundational lifecycle: pre-impl gate + **2** plan-review iterations (independent
  reviewers), TDD, **2** plan-blind post-impl iterations.

## Owns (write only here)
- `helixpay/ingest/extract/**` (extraction), `resolve.py`, `contradict.py`
- `helixpay/ingest/embed.py` (Voyage embeddings — the embedding seam is YOURS)
- `helixpay/ingest/pipeline.py` (the ingestion runner: discover → load → embed →
  persist → extract). Agent 4's `helixpay ingest` CLI calls `pipeline.run(...)`.
- `prompts/**` (named prompt files), `test/unit/ingest/**`, `test/integration/ingest/**`

## Codes against (frozen — import, never redefine)
```python
from helixpay.contracts import (Document, Chunk, Entity, Claim, Link, Contradiction,
                                 Repository, EntityType, LinkType, ContradictionKind)
from helixpay.db.repository import PostgresRepository
from helixpay.config import EXTRACTION_MODEL, EMBEDDING_MODEL, EMBEDDING_DIM, load_config
# Repository methods you use:
#   upsert_document(doc)->int        # idempotent on content_hash
#   add_chunks(chunks, embeddings)->list[int]   # YOU compute embeddings (1024d) and pass them
#   resolve_entity(name, entity_type=None, context=None)->Entity|None  # roster-first; ambiguous+no ctx -> None
#   add_claim(c)->int  /  supersede_claim(old_id, new_id, valid_to)->None  (never delete)
#   add_link(link)->None  /  add_contradiction(c)->None
#   canonical_predicate(raw)->str    # via metric_vocab; unknown -> unchanged
#   get_claims(subject_id, predicate=None)->list[Claim]   # for contradiction grouping
```

## Build
1. **Embeddings** (`embed.py`): Voyage `voyage-3`, **1024-dim**, batched; injectable
   client so unit tests stub it. Used by the pipeline before `add_chunks`.
2. **Extraction** (`extract/**`): per chunk, call `claude-sonnet-4-6` with a **named
   prompt in `prompts/`** and a **structured-output schema** (pydantic, validated
   against the contracts). **Validate-and-repair-or-drop** — never trust raw output;
   on schema failure, one repair attempt, else drop and log. Emit candidate
   `claims` + `relations`.
3. **Resolution** (`resolve.py`): map mentions to the **seeded roster** via
   `resolve_entity` (normalize + embeddings; LLM tie-break only for genuinely
   ambiguous cases; handle transliteration across the mixed languages). Pass a
   `context` dict (team/location/source_uri) so the two Marias / two Tans disambiguate.
   New (non-roster) entities are `upsert_entity` with `seeded=False`.
4. **Canonicalize**: every metric predicate through `canonical_predicate` before writing.
5. **Contradictions** (`contradict.py`): group claims by `(subject, canonical_predicate)`
   with overlapping time windows; write a `contradictions` row (kind ∈
   value_conflict|temporal|source_disagreement). Conflicting claims **coexist** — never
   collapse. The planted Q1 revenue/ARR dashboard-vs-board-deck conflict must surface.
6. **Idempotency / temporal**: unchanged `content_hash` short-circuits; a changed file
   **supersedes** prior claims via `supersede_claim` (sets `valid_to`), never deletes.
7. **Pipeline** (`pipeline.py`): `run(root="data", repo=None)` → uses Agent 1's
   `loaders.discover_all` → `upsert_document` → `embed` → `add_chunks` → extract →
   resolve → canonicalize → persist claims/links → detect contradictions. Idempotent
   end-to-end.

## Conventions (CLAUDE.md §7 — these bind you hardest)
- **Never collapse conflicts.** Every value is a Claim (source + as_of + confidence).
- **Contradictions first-class**, surfaced never resolved. **Never delete** superseded
  facts. **Roster-first** resolution. **Predicates canonicalize** via metric_vocab.
- **Every LLM call** = named prompt in `prompts/` + structured-output schema +
  validate-and-repair. No free-form trust. Observability: log each LLM call's prompt
  name, inputs, structured output, and repair outcome (Agent 6 reads these).
- All DB access via `Repository`. Secrets from env. No real LLM/Voyage calls in unit
  tests (stub the clients); use DB-gated integration tests (`db` mark) for persistence.

## Dependencies (declare in sprint plan; do NOT edit pyproject)
`anthropic` (extraction), `voyageai` (embeddings).

## Done when
- Running `pipeline.run("data")` populates entities/claims/links/contradictions; the
  conventions (named prompts, repair loop, no-uncited-claims, roster-first, supersede)
  are visible and tested.
- Idempotent: a second run is a no-op; changing one file re-ingests only that file and
  supersedes (doesn't duplicate or delete).
- ≥1 real contradiction detected on the actual data. Tests green; mypy clean.

## Hand-off
Agent 3 reads what you write via `Repository`. Agent 6 grades extraction
precision/recall against its golden set. Report: prompt inventory, the structured-output
schema, resolution accuracy on the name traps, and contradictions found.
