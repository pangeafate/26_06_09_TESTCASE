---
sprint_id: SP_030
tier: Standard
features: [ci-db-integration-gate, fake-real-conformance, serving-path-coverage, seam-redundancy-removal, tdd-gate-wiring]
user_stories: []
schema_touched: false
structure_touched: false
status: In Progress
isolation: branch-only
branch: sprint/SP_030-serving-path-coverage
worktree: ""
agent_owner: "Agent (serving-path coverage)"
fix_type: ""
dependencies: [SP_017, SP_022, SP_023, SP_028b]
dev_dependencies: []
touches_paths:
  - .github/workflows/dev-rules-ci.yml
  - test/conftest.py
  - test/unit/test_db_required_guard.py
  - test/unit/query/test_repository_conformance.py
  - test/integration/db/test_mcp_tools_integration.py
  - test/integration/query/test_query_integration.py
  - test/unit/ingest/test_contradict.py
  - test/unit/ingest/test_normalize.py
  - test/golden/test_harness.py
  - test/unit/ingest/test_schemas.py
  - validators/validate_tdd.py
  - test/unit/scripts/test_validate_tdd_layout.py
touches_checklist_items: [ci-pgvector-service, ci-db-required-guard, conftest-require-db-flag, conformance-fake-vs-real, integration-mcp-tools-e2e, integration-serving-branches, redundancy-contradict-normalize, redundancy-harness-valuematch, redundancy-schemas-default, gatewire-validate-tdd-srcdir, gatewire-mirror-map]
---

# SP_030: Serving-Path Coverage — Make the Real Query Path a Gate

> The headline 85% line coverage is a **fake-backed illusion for the serving
> layer.** It is carried almost entirely by `FakeRepository`-based unit tests.
> Strip the fakes and count only the tests that exercise the real wiring
> (`ExposureEngine` MCP tools → `QueryEngine` → `PostgresRepository` SQL) and the
> serving path is ~22–28% covered (`api/engine.py` **0%**). Worse, the only tests
> that exercise the real path are `db`-marked and **auto-skip in CI** — the CI
> workflow provisions no Postgres — so a regression in the real SQL, the
> engine↔repo wiring, or MCP tool exposure ships green through CI and deploy.
> This sprint makes the real serving path an actual gate, stops the fake from
> drifting, fills the serving-path holes, and folds in the leftover SP_017
> tooling/redundancy items. No production `helixpay/` behavior changes.

## Sprint Goal

Convert the serving layer from "green by skipping" to "gated for real":

1. **CI runs the integration suite against real pgvector** + a fail-loud guard so
   the `db` tests can never silently skip in CI again. (49 perpetually-skipped
   tests → real gates.)
2. **Fake↔real conformance** — the query read assertions run against both
   `FakeRepository` and `PostgresRepository`, so the hand-written fake cannot
   drift from the real read contract.
3. **Serving-path coverage backfill** — exercise the 8 `ExposureEngine` MCP tools
   end-to-end against the real repo + the missing real-path branches.
4. **Redundancy cleanup** — the leftover normalize-semantics duplicates SP_017 did
   not reach.
5. **TDD gate-wiring** — finish the `validate_tdd.py --src-dir helixpay` fix SP_017
   logged as "a future tooling sprint."

## Current State

- Suite: 849 collected, 796 pass, 0 fail, 53 skip (~1s). 51 skips are `db`-gated
  (no `DATABASE_URL`), 2 API-key-gated.
- **CI provisions no Postgres** (`.github/workflows/dev-rules-ci.yml` runs
  `dev-gateway.py --stage ci` → `pytest`, no `services:` block, no `DATABASE_URL`),
  so the entire integration layer (49 tests) skips in CI exactly as it does
  locally. The serving path is never exercised by any automated gate.
- Real-path coverage (integration+golden only, db-skipped) vs headline (with fakes):
  `query/engine.py` 22% vs 95%; `ingest/pipeline.py` 28% vs 88%; `db/repository.py`
  17%; TOTAL 28% vs 85%. **Correction (plan-review C2):** `helixpay/api/engine.py`
  is **not** "the 8 MCP tools" — it is the `ExposureEngine` Protocol +
  `MockQueryEngine` (canned data, `engine.py:85`) + `get_engine`/`set_engine`. The
  **real tool dispatch** is `helixpay/mcp/server.py` (`_retrieval` → `get_engine()` →
  `{available:false}`); the **real serving engine** is `query/engine.py::HelixQueryEngine`.
  The coverage holes this sprint targets are therefore `query/engine.py`,
  `db/repository.py`, and the MCP dispatch *run against the real engine* — not
  `api/engine.py` (which is mostly mock; the real path bypasses it).
- The query unit suite is wired to `test/unit/query/fakes.py::FakeRepository`
  ("only the reads the query layer uses"); the adjudication unit suite
  **hand-mirrors** the DB's partial-unique-index dedup — that mirror can rot.
- `test/unit/api/test_mcp.py` already drives all 12 tools via `build_mcp()` +
  `call_tool` and asserts `{available:false}` for the 8 optional tools — but **only
  against `MockQueryEngine` (canned data)**. The wiring/shape is proven; the real
  `HelixQueryEngine`→`PostgresRepository` behavior **behind** the tools is not (the
  precise gap Item 3 fills).
- Leftover from SP_017: (a) `validate_tdd.py` defaults `--src-dir src` (nonexistent
  here) so the gateway's TDD step never runs the file-mapping check and its
  structural check emits ~35 false positives against the flattened layout;
  (b) normalize-semantics duplicates in `test_contradict.py` / `test_harness.py`
  that SP_017's extractor/ledger trims did not cover.

## Desired End State

- CI starts a `pgvector/pgvector:pg16` service, sets `DATABASE_URL`, and runs the
  full suite **including** the `db` integration tests; a `HELIXPAY_REQUIRE_DB`
  guard turns a silent db-skip into a hard CI failure.
- A repository conformance test asserts identical read results from
  `FakeRepository` and `PostgresRepository` (the real one gated on `DATABASE_URL`).
- New db-gated integration tests drive all 8 `ExposureEngine` MCP tools and the
  previously-uncovered real-path branches in `query/engine.py` / `pipeline.py`.
- ~12–13 redundant normalize/trivial test functions removed (owner cited).
- The gateway/CI TDD step runs `validate_tdd.py` against `helixpay/` with a
  layout-aware mirror map; `validators/test_validate_tdd.py` stays green.
- Non-DB local suite stays green (~1s); db-path tests skip cleanly without a DB.

## Scope

**In:** the CI workflow, `test/conftest.py` (the require-db guard), three new test
files (conformance, MCP-tools integration, guard unit test), an extension to
`test_query_integration.py`, redundancy trims in three existing test files, and
`validate_tdd.py` (auto-detect + advisory mirror-map) + its mirror-map unit test.

**Out:** all production code under `helixpay/` (no behavior changes — this is a
test/CI sprint); the `contradictions.yaml` 1/8→2/8 baseline sync (needs a live
prod-DB run — deferred); a Faker/factory layer and broad negative-path expansion
(separate effort); enforcing a *hard* coverage threshold (stays report-don't-block
per SP_017's operator decision).

## Environment Constraint (load-bearing — read before reviewing)

**This build environment has no Docker and no Postgres.** Therefore every
`db`-gated artifact in this sprint (Items 1-real-run, 2, 3) is **authored and
verified to skip cleanly locally + syntactically/inspection-validated**, and its
**green run is delegated to CI** — which is the very gate this sprint creates. The
DB-free parts (the guard logic via a simulated unit test, the redundancy trims,
the gate-wiring + its unit test, the non-DB suite staying green, YAML lint) **are**
verified locally. The post-impl review states explicitly which assertions ran here
vs which are CI-delegated; the operator's first CI run on the pushed branch is the
real green/red signal for the db path. This circularity is acknowledged and
bounded: the guard ensures that if CI's DB is misconfigured the db tests **fail
loud** rather than skip, so a broken CI DB cannot masquerade as success.

## Technical Approach

**Item 1 — CI db gate + required-db guard (ci-pgvector-service, ci-db-required-guard, conftest-require-db-flag)**
- `.github/workflows/dev-rules-ci.yml`: add a `services: db:` block on the
  `gateway` job using `pgvector/pgvector:pg16`, with **explicit port mapping and a
  health check** (plan-review M2 — both are mandatory for a runner-hosted job to
  reach the service via `localhost`):
  ```yaml
  services:
    db:
      image: pgvector/pgvector:pg16
      env:
        POSTGRES_PASSWORD: postgres
        POSTGRES_DB: postgres
      ports: ["5432:5432"]
      options: >-
        --health-cmd pg_isready --health-interval 10s
        --health-timeout 5s --health-retries 10
  ```
  Set **job-level** `env:` (sufficient — `pg_repo`/`connect()` read `DATABASE_URL`
  via `helixpay.config.database_url()`): `DATABASE_URL:
  postgres://postgres:postgres@localhost:5432/postgres` and `HELIXPAY_REQUIRE_DB: "1"`.
  The `pg_repo` fixture self-runs `apply_schema` (`CREATE EXTENSION vector` + schema)
  and truncates; `seed_all` is called by the tests that need a seeded fixture — **no
  separate migrate/seed CI step is required** (confirmed against
  `test/conftest.py::pg_repo` and `test_query_integration.py::seeded_repo`).
- `test/conftest.py`: add a single pure helper
  `_require_db_violation(env: Mapping[str, str]) -> str | None` (returns a message
  when `HELIXPAY_REQUIRE_DB` is truthy **and** `DATABASE_URL` is unset, else `None`)
  and **one** `pytest_configure(config)` hook that raises
  `pytest.UsageError(msg)` when the helper returns a message. (Plan-review M1: adopt
  ONLY the `pytest_configure` design — there is no existing `pytest_configure` in
  `test/conftest.py` to collide with; delete the alternative
  `pytest_collection_modifyitems`-flag variant.) This converts a misconfigured CI DB
  from a silent skip of 49 tests into a loud, early run failure. The existing
  `pytest_collection_modifyitems` skip path is untouched for the normal local case
  (no flag, no url → skip as today).
- `test/unit/test_db_required_guard.py` (DB-free): unit-test `_require_db_violation`:
  (absent url, no flag) → `None` (skip path preserved); (absent url, flag set) →
  message (fail path); (url present, flag set) → `None`. The locally-verifiable proof
  of Item 1's logic.

**Item 2 — Fake↔real conformance (conformance-fake-vs-real)**
- **Location decision (plan-review H3): co-locate under `test/unit/query/`** as
  `test/unit/query/test_repository_conformance.py`, NOT under `test/integration/`.
  Reason: `FakeRepository` is a **bare top-level module** (`from fakes import …`,
  resolvable only because `test/unit/query/` is on `sys.path` under prepend mode with
  no `__init__.py`). A cross-dir import from `test/integration/query/` is order-
  dependent and fragile, and lifting to a `test/_fakes/` package would add `__init__.py`
  files (a structure change). Co-locating with the fake gives a native `from fakes
  import FakeRepository`, **no import hazard, no structure change** (`structure_touched`
  stays false). The real-repo cases are individually `@pytest.mark.db`-marked (using
  the root `pg_repo`/`seeded_repo` fixtures, available everywhere) so they skip
  locally and run in CI; the fake-only cases always run.
- A parametrized test builds the **same** small data shape in a `FakeRepository`
  (always runs) and a `PostgresRepository` (`db`-marked → CI only) and asserts
  identical results through **one shared assertion body** so divergence is a failure.
- **Method set (plan-review M3) — include ONLY deterministic structural reads that
  `FakeRepository` actually implements:** `get_links`, `get_contradictions`,
  `get_claims_by_predicate`, `list_documents`, `list_entities`, `list_metrics`,
  `resolve_entity`, `canonical_predicate`. **Explicitly EXCLUDE `search_semantic` /
  `search_lexical`** — the fake returns canned slices independent of the query vector
  and does not rank, so comparing them to real pgvector search would assert false
  divergence. (Enumerated from `test/unit/query/fakes.py:99-223`.)
- The fake-only half is the locally-verifiable smoke; the real half is CI-delegated.

**Item 3 — Serving-path integration backfill (integration-mcp-tools-e2e, integration-serving-branches)**
- **Rewritten per plan-review C1/C2.** The 8 optional MCP tools do NOT live on a
  callable `ExposureEngine` instance — they are `@mcp.tool()` functions in
  `helixpay/mcp/server.py` that dispatch through `_retrieval(method, …)` →
  module-global `get_engine()` → `{available:false}` when the engine lacks the
  surface. So drive them the way `test/unit/api/test_mcp.py` does: `build_mcp()` +
  `asyncio.run(mcp.call_tool(name, args))`. The genuine gap (the existing
  `test_mcp.py` already drives all 12 tools + asserts `{available:false}` against
  `MockQueryEngine`) is that nothing drives the dispatch against the **real engine
  over a real repo**.
- `test/integration/db/test_mcp_tools_integration.py` (`db`-marked): in a fixture,
  `set_engine(HelixQueryEngine(seeded_repo, embedder=_FakeEmbedder(),
  synthesizer=_FakeSynthesizer(...)))` (stub ONLY the LLM/embedding seams — never a
  paid call; mirror `test_query_integration.py`), restore the prior engine in
  teardown (mirror `test_mcp.py`'s save/restore of `get_engine()`), then drive each
  tool via `mcp.call_tool(...)` and assert `available is True` + a known **seeded**
  value flows tool→`HelixQueryEngine`→`PostgresRepository`. This exercises the real
  dispatch path the mock-backed `test_mcp.py` cannot. (The `{available:false}`
  degrade branch is already owned by `test_mcp.py::test_retrieval_degrades_…` — do
  NOT re-test it here; cite it instead.)
- Extend `test/integration/query/test_query_integration.py` to cover the real-path
  branches the fake suite misses in `query/engine.py` / `ingest/pipeline.py`. Confirm
  the exact missing lines at impl time by reading the branches (the env has no DB to
  re-run integration-only coverage); target them with thin, structural assertions
  over the seeded fixture. The real coverage movers are `query/engine.py` and
  `db/repository.py` — NOT `api/engine.py` (mock; the real path bypasses it).

**Item 4 — Redundancy cleanup (redundancy-contradict-normalize, redundancy-harness-valuematch, redundancy-schemas-default)**
- `test/unit/ingest/test_contradict.py:127-184`: delete ONLY the functions whose
  assertion is **literally on `normalize_value` output** and is duplicated in
  `test/unit/ingest/test_normalize.py`. **Plan-review M4 (tightened): KEEP every
  `values_conflict(...)` assertion** — `values_conflict` is `contradict`'s **own**
  function, not `normalize`'s, so its tests are NOT owned elsewhere and could regress
  with `normalize` green (e.g. `test_eighteen_months_is_not_eighteen_million`,
  `test_values_conflict_with_a_missing_value_is_not_a_conflict`,
  `test_word_form_numbers_are_not_false_conflicts`). Before each deletion, confirm the
  exact `normalize_value` case exists in `test_normalize.py` and cite it in the diff
  (Rule 5). This likely reduces the deletion count below the original ~7–8 estimate —
  conservative is correct. Leave `test_contradict.py` focused on
  `detect`/`classify`/`detect_link_conflicts` + its own `values_conflict` cases.
- `test/golden/test_harness.py:106` `test_normalize_value_matches_equivalent_forms`:
  delete (4 param cases, 1 function) — subsumed by `test/golden/test_rigor.py:110-130`
  `_values_match` (which adds unicode-minus, commas, percent, mismatch rejection,
  substring-false-positive). Keep the boolean `surfaces_contradiction`/
  `no_false_contradiction` checks (distinct check-evaluator layer).
- `test/unit/ingest/test_schemas.py:68` `test_hypothetical_defaults_false`: delete —
  re-asserts a pydantic field default guaranteed by the model definition.

**Item 5 — TDD gate-wiring (gatewire-validate-tdd-srcdir, gatewire-mirror-map)**
- **Mechanism (plan-review H1 — corrected):** the gateway does NOT invoke
  `validate_tdd.py` directly. `dev-gateway.py:242-248` shells `validators/run_all.py .`,
  and `run_all.py:62-65` runs every validator as `[python, script, project_root]`
  with **no extra args** — so there is no gateway command to add `--src-dir` to.
  Therefore make `validate_tdd.py` **auto-detect** its source dir: when the given
  `--src-dir` (default `src`) does not exist, fall back to `helixpay/` (the project's
  actual package). This makes the gateway's no-flag `run_all` invocation point at
  `helixpay/` automatically, with **no change to `run_all.py` or `dev-gateway.py`**
  (both dropped from `touches_paths`). Keep coverage `require_report: false`.
- **De-risk (plan-review H2 — load-bearing):** today the structural check **never
  runs** (early-returns on absent `src/`), so it cannot fail CI. Pointing it at
  `helixpay/` must NOT turn it into a deploy-gate-reddening failure. So the structural
  "no test file found" result is emitted **ADVISORY (warn, exit 0)** — it never
  contributes to the exit code; only the existing coverage gate (line/branch)
  enforces. This is strictly better than today (the check goes from silent-no-op to a
  visible advisory report) and cannot red the `workflow_call` deploy gate.
- `validators/validate_tdd.py`: add **layout-aware mirroring** so the advisory check
  tolerates this repo's flattened map (`helixpay/ingest/extract/coerce.py` →
  `test/unit/ingest/test_coerce.py`; behavior-named files like
  `test_health.py`/`test_rest.py` covering `api/app.py`). Match `test_<basename>.py`
  anywhere under `test/unit/**` in addition to the exact nested path, so the ~35 false
  positives clear while a module with **no** `test_<name>.py` anywhere still appears in
  the advisory list. **Verify locally** (no DB needed): run `uv run python
  validators/validate_tdd.py . ` after the change, enumerate the residual advisory
  gaps against `helixpay/`, and record them in the post-impl review (grandfather any
  genuine gap explicitly — do not let the change imply false completeness).
- `test/unit/scripts/test_validate_tdd_layout.py` (DB-free): unit-test the new
  mirror-matching + auto-detect — a flattened-path source resolves to its test; a
  genuinely test-less module still reports a gap; absent `src/` falls back to
  `helixpay/`. Read `validators/test_validate_tdd.py` first and keep it green (extend,
  don't break).

## Testing Strategy

- **Locally verifiable (run here):** non-DB suite stays green
  (`uv run pytest test -o addopts="" -q`); the require-db guard helper unit test; the
  redundancy trims (suite green, coverage.xml line/branch must not drop for the
  non-db total); the validate_tdd mirror-map unit test + `validators/test_validate_tdd.py`;
  `uv run mypy helixpay` clean (no production code touched); YAML lint of the workflow
  (`python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/dev-rules-ci.yml'))"`).
- **CI-delegated (cannot run here — no DB):** the green run of the db integration
  suite, the real half of the conformance test, the MCP-tools-e2e file, and the
  query-integration branch additions. These are authored to **skip cleanly** without
  a DB and are inspection-verified against the existing passing integration tests'
  fixture/stub patterns. The post-impl review labels each assertion local vs CI.
- Every redundancy deletion cites its owning test before removal (Rule 5); coverage
  is the backstop (non-db line/branch must not regress).
- New db tests follow the existing integration pattern: real repo via `pg_repo`/
  `seeded_repo`, LLM/embedding seams stubbed, **no paid API calls** in the suite.

## Risks & Mitigations

- **CI workflow blast radius** (the workflow gates deploy via `workflow_call`). A
  malformed `services:` block or wrong `DATABASE_URL` could red the gateway and block
  deploys. Mitigation: minimal additive change (service + env only, no step
  reordering); YAML-lint locally; the require-db guard makes a DB misconfig fail
  *loud and early* rather than corrupt results; push to the **sprint branch** and
  watch the branch's CI run before any merge to main — do not merge on a red gate.
- **CI db tests fail green-here-but-red-there** (env constraint). Mitigation: author
  strictly to the proven `test_query_integration.py` fixture/stub pattern; the first
  CI run is the acceptance signal; if red, iterate on the branch (this is exactly why
  the gate exists). Behavioral closure is **pending-CI** until the operator/CI runs it.
- **Lifting `FakeRepository` to a shared module** could disturb the query unit suite.
  Mitigation: re-export from `test/unit/query/fakes.py` so existing imports are
  unchanged; run the query unit suite after the move.
- **Conformance test over-asserts** on methods the fake doesn't implement → false
  divergence. Mitigation: restrict the shared assertion body to the read methods
  `FakeRepository` actually implements (enumerate them from `fakes.py` first).
- **validate_tdd mirror-map weakens a real gate.** Mitigation: the relaxed match only
  *adds* an alternative resolution path; a module with no `test_<name>.py` anywhere
  still flags. Unit-tested both directions; keep advisory.
- **Path overlap with stale "In Progress" sprints** (SP_001/015/016 have stale
  `status: In Progress` frontmatter but are long complete; the project is at SP_029
  deployed). None overlap these test/CI paths. `branch-only` isolation; single writer.
  Do not stage the unrelated working-tree changes (`SOLUTION.md`,
  `workspace/git-bypass-log.txt`, the sibling's untracked `scripts/retrieval_*` /
  `workspace/acceptance/retrieval_*`) — stage explicit paths only.

## Success Criteria

- `.github/workflows/dev-rules-ci.yml` starts a pgvector service, sets `DATABASE_URL`
  + `HELIXPAY_REQUIRE_DB`, and the gateway runs the db integration tests (verified by
  the first CI run on the pushed branch).
- The require-db guard: db-skip with the flag set is a hard failure; guard helper
  unit-tested DB-free and green.
- Conformance test present; fake-half green locally, real-half CI-delegated.
- MCP-tools-e2e integration file drives all 8 tools; query-integration branch
  additions present.
- ~12–13 redundant test functions removed with owner cited; non-db suite green; non-db
  coverage does not regress.
- Gateway runs `validate_tdd.py --src-dir helixpay`; mirror-map clears the ~35 false
  positives while still flagging genuine gaps; `validators/test_validate_tdd.py` +
  new layout test green.
- `uv run pytest test -o addopts=""` green locally; `uv run mypy helixpay` clean.

### Pre-Implementation Review

> Standard tier — floor = 2 iterations. (CI workflow change + the validate_tdd gate
> are high-blast-radius; Items 1 and 5 reviewed with Foundational-level care per
> plan-review L1.)

- **Iteration 1** — independent `architect-reviewer` (plan-blind). Files reviewed: the SP_030 plan + `dev-rules-ci.yml`, `dev-gateway.py`, `validate_tdd.py`/`test_validate_tdd.py`, `conftest.py`, `test_query_integration.py`, `api/engine.py`, `query/engine.py`, `mcp/server.py`, `fakes.py`. Verdict **approve-with-changes** — 2 CRITICAL, 3 HIGH, 4 MEDIUM, 3 LOW. Findings:
  - **C1 (CRITICAL):** Item 3 targeted the wrong layer — the 8 MCP tools dispatch via
    `mcp/server.py::_retrieval` → global `get_engine()`, not a callable `ExposureEngine`;
    and `test/unit/api/test_mcp.py` already drives all 12 tools + the `{available:false}`
    degrade against the mock. Real gap = drive the dispatch against the **real engine+repo**.
  - **C2 (CRITICAL):** `api/engine.py` is `MockQueryEngine`+Protocol+`get_engine`/`set_engine`,
    not "the 8 MCP tools"; the "0%→upward" coverage claim was false. Real movers are
    `query/engine.py` + `db/repository.py` + the MCP dispatch run against the real engine.
  - **H1 (HIGH):** the gateway runs `run_all.py` (no per-validator flags) — there is no
    `validate_tdd` invocation to add `--src-dir helixpay` to.
  - **H2 (HIGH):** `validate_tdd` is advisory-no-op today (absent `src/`); pointing it at
    `helixpay/` could create a failing gate that reds the deploy-gating gateway.
  - **H3 (HIGH):** cross-dir import of the bare `fakes` module from `test/integration/` is
    a prepend-mode hazard; the `test/_fakes/` lift adds structure.
  - **M1–M4 (MEDIUM):** dual guard design; under-specified CI service block (needs `ports`
    + `options`); conformance method set includes non-deterministic semantic/lexical search;
    `contradict.py` deletion over-reaches into `values_conflict` (owned by `contradict`, not
    `normalize`).
  - L1 (tier), L2 (`structure_touched`), L3 (`touches_paths`) noted.
- **Iteration 2** — author reconciliation. Files reviewed: the same plan + frontmatter. **All CRITICAL + HIGH + MEDIUM findings folded into Technical Approach + frontmatter above (no CRITICAL/HIGH left open):**
  - C1/C2 → Item 3 rewritten to `build_mcp()` + `set_engine(HelixQueryEngine(seeded_repo,…))`
    + `call_tool`, scoped to the real-engine delta; coverage prose retargeted to
    `query/engine.py`/`db/repository.py`; Current-State corrected.
  - H1 → Item 5 mechanism changed to `validate_tdd` **auto-detect** `helixpay/` when `src/`
    absent (no `run_all.py`/`dev-gateway.py` change); both dropped from `touches_paths`.
  - H2 → structural check made **ADVISORY (exit 0)**; residual gaps to be enumerated
    locally + grandfathered in post-impl. Cannot red the deploy gate.
  - H3 → conformance test **co-located under `test/unit/query/`** (native `from fakes import`),
    real cases `@pytest.mark.db`; no `test/_fakes/` package, `structure_touched: false` holds.
  - M1 → single `pytest_configure` + `_require_db_violation` helper. M2 → full service block
    with `ports`/`options` spelled out. M3 → conformance include/exclude set pinned (excludes
    semantic/lexical search). M4 → deletions tightened to literal `normalize_value` cases only.
  - L3 → `touches_paths` updated (conformance under `unit/query`, gateway files removed).
  No CRITICAL/HIGH findings remain open; no frozen-contract violations (no `helixpay/contracts/`
  types touched, no raw SQL added). Cleared to implement.

### Post-Implementation Review

- **Iteration 1** — independent plan-blind `code-reviewer`. Files reviewed: the working-tree diff + new files (`dev-rules-ci.yml`, `conftest.py`, `validate_tdd.py`, `.validators.yml`, the 4 new test files, the 4 trimmed/extended test files) cross-checked against `repository.py`, `fakes.py`, `mcp/server.py`, `query/engine.py`, `test_normalize.py`, `test_rigor.py`. Verdict **APPROVE-WITH-NITS** — zero BLOCKING, zero HIGH; 3 MEDIUM + nits applied. Verified: CI service
  block correct (image/ports/health/env scope/URL all consistent); require-db guard
  correct + the local skip path intact; every deleted test's behavior confirmed owned
  elsewhere; conformance fake/real populate paths build equivalent data and the reads
  hold under real SQL semantics; MCP e2e saves/restores the global engine and its
  seeded assertions (Wei Chen/Priya Raman/Revenue/`value_conflict`) match
  `seed_all(with_fixture=True)`; `validate_tdd` advisory mode preserves strict behavior
  when `structure_advisory` is false. Three MEDIUM nits **applied**: (a) the one genuine
  coverage gap from the deletion — `normalize_value("v1.0")` non-numeric — re-pinned in
  `test_normalize.py::test_version_string_not_numeric`; (b) DATA-path comment in the MCP
  e2e file; (c) `get_relationships` tool now asserts non-empty `results`. NIT applied:
  `POSTGRES_USER` default documented in the workflow.
- **Iteration 2** — author runtime-evidence re-verification. Files reviewed: the full changed set re-run end-to-end (0 CRITICAL/HIGH; the 3 MEDIUM nits applied and re-tested):
  - `uv run pytest test -o addopts="" -q` → **814 passed, 77 skipped, 0 failed** (~1.2s).
    Skips are env-gated (db + 2 API-key); +24 db-gated added (conformance real-half 11,
    MCP e2e 11, query-integration +2) all skip cleanly without a DB.
  - Guard fires loud under CI flag: `HELIXPAY_REQUIRE_DB=1` + no `DATABASE_URL` →
    `pytest.UsageError` (run aborts); without the flag, db tests skip as before.
  - `uv run mypy helixpay` → clean (74 files; confirms no production code altered).
  - `validate_tdd.py .` → auto-detects `helixpay`, reports 15 ADVISORY gaps, **exits 0**
    (cannot red the deploy gate); mirror-map cleared ~20 of the old ~35 false positives.
    Genuine residual advisory gaps (visible debt, out of scope): `audit/run.py`,
    `config.py`, `query/clients.py`, `seed/fixtures.py`, `audit/__main__.py`.
  - Redundancy: net non-db count 796 → 794 (−7 deleted owner-cited, +5 guard) before the
    db-gated additions; no coverage regression.

## Outcome

Complete (pending the CI green run of the db path — see below). Delivered all five items:
(1) CI provisions pgvector + sets `HELIXPAY_REQUIRE_DB`, converting 49 perpetually-
skipped integration tests into real gates, with a fail-loud guard so a misconfigured CI
DB can never silently skip again. (2) Fake↔real repository conformance test pins the
`FakeRepository` read contract against `PostgresRepository`. (3) Serving-path backfill —
a new MCP-tools-e2e file drives all 12 tools (incl. the 8 retrieval tools) through the
**real** `HelixQueryEngine`→`PostgresRepository`, plus the synth-failure degrade and
search→fetch real-path branches. (4) ~7 redundant normalize/trivial test functions
removed (owner-cited; `values_conflict` tests deliberately KEPT). (5) `validate_tdd`
auto-detects `helixpay` + a layout-tolerant mirror-map, advisory so it reports gaps
without reddening the deploy gate. Author-blind review APPROVE-WITH-NITS (all applied);
local runtime evidence green; mypy clean.

**Behavioral closure (db path): PENDING-CI.** This build env has no Docker/Postgres, so
the db-gated tests (conformance real-half, MCP e2e, query-integration additions) are
authored + verified to skip cleanly locally and inspection-checked against the proven
integration patterns; their first green run is the CI run on the pushed branch. The
require-db guard guarantees a DB misconfig fails loud rather than masquerading as green.

## Hand-off

_Pending implementation._

### Follow-on: SP_031 — serving-path production hardening (sequenced AFTER this gate lands)

Operator-approved (2026-06-12) to run **after** SP_030's integration gate is live
and green, so the production refactors land on a real safety net (and not blind —
this build env has no local DB). Five verified production-code smells, severity-ordered:

1. **`assert row is not None` as runtime guards** (`db/repository.py:135,162,184,312`;
   also `db/audit_queries.py:57,67`) — stripped under `python -O`. Replace the
   real-dereference guards with explicit `if row is None: raise`. Cheap, low-risk.
2. **Inaccurate "recursive CTE" docstrings** (`contracts/repository.py:119`,
   `contracts/models.py:131`) — the org subtree is Python-side recursive `build()`
   over flat edge-map queries (`db/repository.py:528-542`), not a SQL recursive CTE.
   Trivial doc fix.
3. **Layer break: audit bypasses `Repository`** (`audit/run.py:26,31-47,92` → direct
   `db.audit_queries`). Decision required: accept-and-document (audit is read-only
   census; the frozen `Repository` Protocol exposes no census reads) **vs** propose a
   Protocol contract change to add census reads (propose-don't-fork).
4. **N+1: up to `_MAX_TERMS` serial `resolve_entity` per `ask()`**
   (`query/engine.py::_resolve_subjects`, ~417) — self-documented as "Protocol
   friction." Needs a batched `resolve_entities` (frozen-contract change) or a
   per-ask resolution cache.
5. **f-string SQL fragment in `_org_root_id`** (`db/repository.py:544-566`) — smell
   only; the interpolated `date_filter` is a constant literal and all values go
   through `%s` params (injection-safe today). Refactor to a composed-clause helper.

These are NOT in SP_030 (test/CI-only). SP_031's safety net is precisely the `db`
integration suite + MCP-tools-e2e file this sprint makes runnable in CI.
