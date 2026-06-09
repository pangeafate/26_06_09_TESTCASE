# Agent 3 — Query brain: retrieval + graph + reasoning (SP_004, FOUNDATIONAL)

You are Agent 3. You implement the `QueryEngine` — hybrid retrieval, recursive-CTE
hierarchy, temporal resolution, contradiction surfacing, and a grounded `ask()` where
**every claim is cited**. You build against the **seeded fixture DB** (already loaded
by the gate), NOT real extracted data, so you can start immediately. Run the full
Foundational lifecycle. Read `CLAUDE.md` §7, `AGENTS.md`, `HELIXPAY_BUILD_SPEC.md` §5
(Agent 3), and `fanout/README.md`.

## Setup
- Worktree: `git worktree add .claude/worktrees/SP_004 -b sprint/SP_004-query main`
- Sprint plan `workspace/sprints/SP_004_query.md` — `tier: Foundational`,
  `isolation: git-worktree`, `touches_paths: [helixpay/query/**, test/unit/query/**, test/integration/query/**]`.
- Before coding: `uv run python -m helixpay.db.migrate && uv run python -m helixpay.seed.run_seed`
  gives you a live DB with roster + metric_vocab + the planted-contradiction fixture.

## Owns (write only here)
- `helixpay/query/**` — retrieval, graph, temporal resolver, planner, `ask()`, and the
  concrete `QueryEngine` implementation.
- `test/unit/query/**`, `test/integration/query/**`.

## Codes against (frozen — import, never redefine)
```python
from helixpay.contracts import (QueryEngine, AnswerBundle, Citation, Contradiction,
                                 OrgNode, EntityDetail, Repository, Chunk, Claim, Link)
from helixpay.db.repository import PostgresRepository
from helixpay.config import SYNTHESIS_MODEL, EMBEDDING_MODEL   # ask() synthesis = claude-opus-4-8
# QueryEngine(Protocol) — you IMPLEMENT this:
#   ask(question)->AnswerBundle
#   get_entity(name)->EntityDetail
#   get_org_chart(as_of=None)->OrgNode
#   find_contradictions(topic=None)->list[Contradiction]
# Repository reads you lean on:
#   search_semantic(qvec,k)->list[(Chunk,float)]   search_lexical(q,k)->list[(Chunk,float)]
#   get_org_subtree(root_id=None, as_of=None)->OrgNode   # recursive CTE, cycle-guarded
#   get_claims(subject_id, predicate=None)   get_links(link_type=None)
#   get_contradictions(subject_id=None)   get_sources(claim_ids)->list[Citation]
#   resolve_entity(name, entity_type=None, context=None)   canonical_predicate(raw)
```

## Build
1. **Hybrid retrieval**: `search_semantic` (Voyage query embedding, 1024d) +
   `search_lexical` (FTS) → **reciprocal-rank fusion (RRF)**. (No trained reranker —
   explicit scope cut; RRF at this corpus size.)
2. **Hierarchy/ownership**: use `get_org_subtree` (recursive CTE, cycle guard, `as_of`
   filter). Surface dotted-line vs solid reporting distinctly (`OrgNode.dotted_reports`).
3. **Temporal resolver**: freshest-wins; flag staleness; populate
   `AnswerBundle.as_of_coverage`. The org-chart roster is dated `2026-04-15` — prefer
   later documents that disagree and say so.
4. **Contradiction surfacing**: `find_contradictions` + include relevant ones in `ask`'s
   `AnswerBundle.contradictions` (attribute each side; never silently pick).
5. **`ask()`**: a lightweight planner routing {structured | retrieval | both} — gather
   facts (claims/links) + chunks, then synthesize with `claude-opus-4-8` **grounded
   strictly in retrieved material, every claim cited** (`get_sources` → `Citation` with
   `source_uri` + `as_of`). Zero uncited claims. Log the plan route, what was retrieved,
   which claims were cited (Agent 6 reads this).

## Conventions
- All reads via `Repository`; no raw SQL. Synthesis via a named prompt; structured where
  it helps. Secrets from env; stub the LLM/embedding clients in unit tests; use the
  `db`-marked fixture DB for integration. `ask()` output has **zero uncited claims** —
  enforce it (a post-check that drops/flags any uncited sentence).

## Dependencies (declare in sprint plan; do NOT edit pyproject)
`anthropic` (synthesis), `voyageai` (query embeddings).

## Done when
- `ask(q)` returns a cited, time-aware `AnswerBundle` on the **fixture** for the §8
  question shapes (hierarchy, staleness, ARR contradiction, cross-doc synthesis,
  customer ownership). At least one answer surfaces the planted contradiction with both
  sides attributed.
- `get_org_chart()` resolves the roster hierarchy; `get_entity(name)` returns
  entity+aliases+claims. Tests green; mypy clean.

## Hand-off
Agent 4 builds MCP/API/CLI over your `QueryEngine` (it mocks the Protocol until you
land — keep the public surface exactly the Protocol). Report: the planner routes, the
RRF weighting, the no-uncited-claims enforcement mechanism, and any contract friction.
