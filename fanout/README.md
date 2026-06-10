# Fan-out — Phase 1 build briefs

The Phase 0 gate is frozen and on `main`. This folder holds one **self-contained
scope-of-work** per build agent. Hand each file to a fresh Claude Code agent in its
own worktree. They build in parallel against the frozen contracts; the orchestrator
compares and merges at integration.

> Authoritative sources every agent must read first: `CLAUDE.md` (governance + §7
> conventions), `AGENTS.md` (coding-agent adapter), `HELIXPAY_BUILD_SPEC.md` (what to
> build, §5/§6/§8). On any overlap, the **stricter** rule wins.

## The agents

| File | Agent | SP | Tier | Owns (writes only here) | Codes against |
|------|-------|----|----|--------------------------|---------------|
| `AGENT_1_loaders.md` | Loaders | SP_002 | Standard | `helixpay/ingest/loaders/**`, `test/unit/loaders/**` | contracts |
| `AGENT_2_extraction.md` | Extraction & ontology *(critical path)* | SP_003 | **Foundational** | `helixpay/ingest/extract/**`, `helixpay/ingest/pipeline.py`, `helixpay/ingest/embed.py`, `prompts/**`, `test/unit/ingest/**`, `test/integration/ingest/**` | contracts, Repository, Chunk |
| `AGENT_3_query.md` | Query brain | SP_004 | **Foundational** | `helixpay/query/**`, `test/unit/query/**`, `test/integration/query/**` | Repository (+ seeded fixture) |
| `AGENT_4_exposure.md` | Exposure (MCP/API/CLI) | SP_005 | Standard | `helixpay/mcp/**`, `helixpay/api/**`, `helixpay/cli.py`, `test/unit/api/**` | QueryEngine Protocol (mock) |
| `AGENT_5_infra.md` | Infra & deploy | SP_006 | **Foundational** | `deploy/**`, `Dockerfile`, `docker-compose.yml`, `Makefile`, `.env.example` | gate entrypoints |
| `AGENT_6_eval.md` | Eval & ground truth *(author-independent)* | SP_007 | Standard | `eval/**`, `test/golden/**`, refines `.claude/agents/verifier.md` | contracts + raw `data/` |

Ownership is **disjoint by construction** (spec §6). No two agents write the same
file. Agents 1↔2 meet only through the `Chunk` contract; 2↔3 only through
`Repository`; 4 builds against the `QueryEngine` stub; 6 derives from raw data +
contracts and owes nothing to the builders.

## Critical path & dependencies

```
Gate (done) ──┬─► Agent 1 loaders ─┐
              ├─► Agent 2 extraction (LONGEST POLE) ──► integration
              ├─► Agent 3 query (builds on seeded fixture)
              ├─► Agent 4 exposure (mocks QueryEngine until 3 lands)
              ├─► Agent 5 infra (needs only entrypoint names, frozen below)
              └─► Agent 6 eval (starts immediately; grades at the end)
```

Everyone can start now. Agent 2 is the long pole. Agent 4 mocks `QueryEngine` until
Agent 3 lands. Agent 3 builds against the **seeded fixture DB**, not real extracted
data. Agent 6 authors ground truth from raw `data/` with no sight of build code.

## Isolation protocol (mandatory — parallel safety)

Each agent, first thing:

1. Create a worktree + branch off `main`:
   ```bash
   git worktree add .claude/worktrees/SP_00X -b sprint/SP_00X-<slug> main
   ```
2. Write its sprint plan to `workspace/sprints/SP_00X_<slug>.md` with frontmatter:
   `tier`, disjoint `touches_paths`, `isolation: git-worktree`,
   `branch: sprint/SP_00X-<slug>`, `worktree: .claude/worktrees/SP_00X`, `status: In Progress`.
3. Run the lifecycle **proportionate to tier** (this is just DEV_RULES):
   - **Foundational (Agents 2, 3, 5):** pre-impl gate + 2 plan-review iterations,
     TDD, 2 plan-blind post-impl iterations.
   - **Standard (Agents 1, 4, 6):** pre-impl gate + ≥2 iterations, TDD, post-impl review.
   - Gate command: `python3 validators/validate_sprint.py . --gate pre-impl`.
4. Validators that keep you honest while parallel:
   `validators/validate_worktree_isolation.py` and `validators/validate_sprint_overlap.py`
   reject overlapping non-isolated sprints — declare `git-worktree` and stay in your
   `touches_paths`.

## Shared files — DO NOT edit in a worktree (they collide; merge handles them)

| File | Rule |
|------|------|
| `pyproject.toml` | **Do not edit `[project].dependencies`.** List the packages you need in your sprint plan under a `## Dependencies` heading; the orchestrator consolidates them at merge. (Pre-seeded deps: `psycopg`, `pydantic`, `pyyaml`, `pytest`, `mypy`.) |
| `CLAUDE.md` | Don't edit. Put new "Gotchas" in your delivery report; orchestrator appends. |
| `helixpay/contracts/**` | **Frozen.** If you genuinely need a contract change, STOP and flag it in your sprint plan — do not fork the type. A contract change re-freezes the gate. |
| Meta-docs (`PROGRESS.md`, `FEATURE_LIST.md`, `ARCHITECTURE.md`, `DATA_SCHEMA.md`, `CODEBASE_STRUCTURE.md`, `USER_STORIES.md`, `PROJECT_ROADMAP.md`) | Don't touch. Orchestrator reconciles at integration. |
| `test/conftest.py` | Already provides the `db` mark + `pg_repo` fixture (skips without `DATABASE_URL`). Reuse it; don't redefine. |

## Environment (every agent)

```bash
uv venv --python 3.12 && uv pip install -e '.[dev]'   # + your sprint-declared deps
# local Postgres for DB-touching tests:
docker run -d --name helix-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=helixpay \
  -p 55432:5432 pgvector/pgvector:pg16
export DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:55432/helixpay"
export ANTHROPIC_API_KEY=...   VOYAGE_API_KEY=...      # only the LLM/embedding slices
uv run python -m helixpay.db.migrate && uv run python -m helixpay.seed.run_seed
```

Secrets **only** from env. Never hardcode or log them.

## The frozen substrate you build ON (already on `main`)

- `helixpay/contracts/` — models + 4 Protocols (see each brief for the exact surface).
- `helixpay/db/` — `schema.sql` (8 tables), `migrate.py`, `PostgresRepository` (the one
  `Repository` impl), `connection.py`.
- `helixpay/config.py` — `load_config()`, `database_url()`, pinned models:
  `EXTRACTION_MODEL=claude-sonnet-4-6`, `SYNTHESIS_MODEL=claude-opus-4-8`,
  `EMBEDDING_MODEL=voyage-3`, `EMBEDDING_DIM=1024`.
- `helixpay/seed/` — roster + `metric_vocab` + query fixture, already loaded by `run_seed`.

## Done condition (`/goal`)

`make test` green · `make demo` answers every eval question with `as_of`-stamped
citations and surfaces ≥1 real contradiction · MCP reachable over streamable-HTTP at
the live URL. Each slice is additionally checked by Agent 6 against §1 + §8.

## Merge (orchestrator, when you return)

I diff each worktree, run the worktree-isolation + overlap validators, consolidate
`pyproject.toml` deps, integrate onto `main`, run Agent 6's adversarial pass +
`make test`/`make demo`, reconcile meta-docs, and do the doc + deploy gates.
