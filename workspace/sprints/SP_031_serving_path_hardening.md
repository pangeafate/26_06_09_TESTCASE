---
sprint_id: SP_031
tier: Standard
features: [gateway-project-interpreter, assert-to-raise-guards, n1-resolve-cache, cte-docstring-fix, org-root-sql-compose, audit-layer-doc, ask-branch-unit-coverage, combined-coverage-gate, xfail-debt-resolution]
user_stories: []
schema_touched: false
structure_touched: false
status: In Progress
isolation: branch-only
branch: sprint/SP_031-serving-path-hardening
worktree: ""
agent_owner: "Agent (serving-path hardening)"
fix_type: ""
dependencies: [SP_011, SP_019, SP_022, SP_023, SP_025, SP_029, SP_030]
dev_dependencies: []
touches_paths:
  - scripts/dev-gateway.py
  - test/unit/scripts/test_dev_gateway_interpreter.py
  - helixpay/db/repository.py
  - helixpay/db/audit_queries.py
  - helixpay/contracts/repository.py
  - helixpay/contracts/models.py
  - helixpay/query/engine.py
  - test/unit/query/test_engine_branches.py
  - helixpay/audit/run.py
  - .github/workflows/dev-rules-ci.yml
  - test/integration/query/test_query_integration.py
  - test/integration/db/test_repository_integration.py
  - test/golden/test_contradiction_recall.py
  - workspace/CLAUDE_GOTCHAS.md
  - CLAUDE.md
touches_checklist_items: [gateway-project-python, gateway-interpreter-test, repo-assert-to-raise, audit-assert-to-raise, n1-resolve-cache, n1-cache-test, cte-docstring-repository, cte-docstring-models, org-root-sql-compose, audit-layer-accept-doc, ask-branch-multi-entity, ask-branch-route-both, ask-branch-contradictions, ask-branch-synth-fail, org-chart-unit-test, coverage-combine-ci-advisory, xfail-org-chart-asof, xfail-org-subtree-asof, xfail-live-detector-skip, gotcha-audit-layer]
---

# SP_031: Serving-Path Production Hardening

> Sequenced **after** the SP_030 serving-path CI gate landed on `main` (PR #4, merge
> `6bb36c4`), so every production refactor here lands on a real `db`-integration safety
> net rather than blind (this build env has **no local Postgres**). This sprint pays
> down the five verified production-code smells the TTD review surfaced, fills the
> *unit-level* serving-path holes the gate cannot fill DB-free, retires the
> 15-entry gateway bypass log at its root cause, and resolves the three pre-existing
> `db`-test failures SP_030's gate newly exposed (currently `xfail`).

## Sprint Goal

Pay down the five verified production-code smells the TTD review surfaced, retire the
15-entry gateway bypass log at its root cause (the gateway must run the project
interpreter), add the DB-free unit branch coverage of `ask()` that the SP_030 `db`-gate
cannot fill, make the 80% coverage gate real by combining the two CI jobs, and resolve the
three pre-existing `xfail`ed `db` failures — all landing on the SP_030 integration gate as
their safety net, with **no schema and no frozen-contract surface change**.

## Corrections folded in (from the post-SP_030 re-assessment)

The original Tier-1/2/3 improvement list was written against pre-SP_030 numbers and is
~25% stale. This spec corrects three assumptions before committing scope:

1. **"Serving layer is untested" is half-done.** SP_030's `integration` CI job already
   exercises `api/engine.py`, `mcp/server.py`, and the real `ask()` path through
   `PostgresRepository`. The low unit-only numbers (`api/engine.py` 0%, `mcp/server.py`
   0%) are the *fake-coverage illusion by design* — the `db` tests auto-skip locally.
   The genuine remaining gap is **DB-free unit branch coverage of `ask()`**, which is
   what I7 adds. The "cover the 8 MCP tools in `api/engine.py`" bullet is **dropped** —
   it repeats the SP_030-corrected misattribution (`api/engine.py` is the
   `ExposureEngine` adapter seam + `MockQueryEngine`, not the tool dispatch) and is
   already integration-covered.
2. **Coverage now lives in two CI jobs.** Any single coverage number lies unless the
   unit job and the `integration` job are `coverage combine`d (I8). The 80% `validate_tdd`
   gate is also **not currently enforced** (`coverage.require_report` defaults false), so
   "the validator already gates on 80%" is aspirational — I8 makes it real.
3. **FakeRepo consolidation is largely a no-op and is descoped to a documented decision
   (I10).** Query-side tests already share `test/unit/query/fakes.py:FakeRepository`. The
   six ingest-side fakes are *intentionally minimal per-test stubs*; forcing them onto one
   shared fake over-couples them for no real drift reduction (the suite would fail loudly
   if a fake lacked a called method). I10 records this rationale rather than churning six
   files.

## Tier & isolation

- **Tier: Standard.** Touches a runtime seam (`query/engine.py` per-ask cache) and the db
  layer (`db/repository.py`), but **no schema change** and **no frozen-contract surface
  change**: the N+1 fix is a per-`ask()` resolution *cache* (D2), not a new
  `resolve_entities` Protocol method; the `contracts/*` edits are **docstring-only**; the
  assert→raise and SQL-compose edits are behavior-preserving. Standard review floor: **2
  Pre-Impl iterations + plan-blind Post-Impl** (`practices/GL-SELF-CRITIQUE.md`).
- **Isolation: branch-only.** Dedicated branch `sprint/SP_031-serving-path-hardening` off
  `origin/main`. A sibling agent's untracked work (`Makefile`, `SOLUTION.md`,
  `scripts/retrieval_*`, `workspace/snapshots/*.dump`) is present in the tree and is left
  **untouched** — no sweep staging (Commit Discipline).

## Environment constraint (carried from SP_030)

This build env has **no local Docker / Postgres**. Items that exercise real SQL
(I2 assert→raise, I5 SQL-compose, I9 xfail removals) are **verified by the CI
`integration` job** against `pgvector/pgvector:pg16`, not locally. DB-free items
(I1 gateway, I4 N+1 cache, I7 `ask()` branches) are TDD'd and run locally before push.

---

## Scope

In scope (one checklist item group each): I1 gateway project-interpreter; I2 assert→raise
(6 sites); I3 CTE docstring fixes; I4 N+1 per-`ask()` resolve cache; I5 `_org_root_id` SQL
compose; I6/D1 audit layer-break accept-and-document; I7 DB-free `ask()` branch tests; I8
combined two-job coverage gate; I9 three xfail resolutions; I10 FakeRepo-dedup documented
decision (no churn); I11 Hypothesis property tests (stretch, only if dep already present).

Out of scope: any schema change; any frozen `Repository`/`QueryEngine` Protocol **surface**
change (the N+1 fix is a cache, not a new method — D2); adding a `hypothesis` dependency;
touching the sibling agent's untracked work.

## Technical Approach

### I1 — Gateway runs the project interpreter (retires the bypass log at root cause)
**Smell #0 / highest ROI.** `scripts/dev-gateway.py` shells `sys.executable` for every
Python child step (pytest, `validate_module_size.py`, `run_all.py` — lines 217, 219, 238,
246). All 15 bypass-log entries share one root cause: the gateway was invoked under a
**system `python3` lacking `bs4`/`psycopg`**, so the child steps `ImportError`ed and were
waived. A gate that runs is worth infinitely more than a 15-entry bypass log.
- Add pure helper `_project_python(project_root) -> str`: prefer `$VIRTUAL_ENV/bin/python`,
  then `<root>/.venv/bin/python`, else fall back to `sys.executable`. Use it for all Python
  child steps.
- **TDD (local):** `test/unit/scripts/test_dev_gateway_interpreter.py` — tmp root with a
  fake `.venv/bin/python` → detected; without → `sys.executable`; `$VIRTUAL_ENV` precedence.

### I2 — `assert row is not None` → explicit raise (6 sites)
Stripped under `python -O`; these guard real dereferences / infra post-conditions.
`db/repository.py:135,162,184,312` + `db/audit_queries.py:57,67` → `if row is None: raise
RuntimeError(<context>)`. Behavior-preserving under normal `-O`-free runs; **CI-verified**
by the `integration` job. _Process note (Stage-3 LOW): these guards sit on
count(*)/hash-exists paths the existing `db` suite exercises; the change is a safer error
type on an already-covered line, so CI green is meaningful even though the `None` branch
itself is not separately forced._

### I3 — Fix the inaccurate "recursive CTE" docstrings (doc-only)
`contracts/repository.py:119` and `contracts/models.py:131` claim the org subtree is
"queried via recursive CTE"; `db/repository.py:528-542` assembles it Python-side over flat
edge-map queries. Correct the docstrings to describe the real Python-side recursion. No
test (doc-only).

### I4 — N+1 resolve collapse via a per-`ask()` resolution cache (D2)
`query/engine.py:_resolve_subjects` (≈417) issues up to `_MAX_TERMS` (40) serial
`resolve_entity` round-trips per `ask()` — self-documented "Protocol friction." **D2: a
per-`ask()` cache, not a frozen-contract change** (adding `resolve_entities` to the frozen
`Repository` Protocol is Foundational/propose-don't-fork — out of scope).
- **The cache MUST be a fresh local dict per `ask()` call, NOT an instance attribute on
  `HelixQueryEngine`** (Stage-3 architect finding): an instance-level memo on a long-lived
  engine would leak a stale `None`/entity across requests after a concurrent ingest —
  turning a safe per-request memo into a correctness bug. Pass the dict into
  `_resolve_subjects` (or build it in `ask()` and thread it through). Key on the **raw term
  string** as passed by `_resolve_subjects` (the repo normalizes internally), so the memo
  collapses exactly what `resolve_entity` already treats as the same lookup.
- **TDD (local):** `test/unit/query/test_engine_branches.py` — a counting subclass of
  `FakeRepository` asserts (1) a question with a repeated term calls `resolve_entity` once
  per *distinct* term, not once per occurrence; (2) a cached `None` (ambiguous bare name)
  is not re-queried and never flips to a pick; (3) **two separate `ask()` calls each
  re-resolve** (proves per-call isolation, not instance leak).

### I5 — `_org_root_id` f-string SQL → composed parameterized fragment (smell-only)
`db/repository.py:544-566` builds `date_filter` via f-string. **Injection-safe today**
(interpolated text is a constant literal; all values via `%s`), but interpolating SQL text
is a smell. Refactor to a composed-clause helper that returns `(sql_fragment, params)` with
no interpolated SQL text. Behavior-identical; **CI-verified** by the `integration` job.

### I6 / D1 — Audit layer-break: **accept-and-document** (no code change)
`audit/run.py:26` reads via `helixpay.db.audit_queries` directly, bypassing the frozen
`Repository` Protocol. **D1: accept-and-document.** The audit subsystem (SP_029) is a
**read-only integrity census**; the frozen `Repository` Protocol exposes no census reads,
and adding them is a Foundational contract change (propose-don't-fork — do not fork the
frozen type for a census). Resolution: an explicit comment **at the import site**
(`audit/run.py:26`, not only module-top — Stage-3 finding) naming the **two invariants**
that bound the exception — (1) **read-only** and (2) **census/introspection, not domain
serving** — so a future reviewer can tell at a glance whether a new `audit_queries` call is
still in-bounds, plus a CLAUDE.md/gotcha entry. No Protocol change.

### I7 — DB-free unit branch coverage for `ask()` (the real remaining serving gap)
`test/unit/query/test_engine_branches.py` (shared with I4), all via
`query/fakes.py:FakeRepository` (no DB). **Branch names corrected per Stage-3 review** —
`ask()` reads only `plan.route` + `plan.wants_contradictions` and **never calls
`get_org_subtree`** (that's `get_org_chart`, a separate method). The genuine `ask()`
branches:
- **multi-entity** query → multiple distinct subjects resolved and their facts gathered;
- **route = `both`** (a retrieval+structured question) vs **structured-only** → asserts the
  retrieval leg runs (chunks gathered) only on the `both`/`retrieval` route, via the
  `last_trace["route"]` value, not a phantom temporal repo call;
- **contradictions always surfaced** → `AnswerBundle.contradictions` is present-and-empty
  even when synthesis cites none (the ontology invariant);
- **synthesis-failure degradation** (`engine.py:135` `ask.synthesis_failed`) → with an
  **inline one-line `FakeSynthesizer` subclass that raises** (avoids editing the unlisted
  `fakes.py`; Stage-3 finding), `ask()` still returns a bundle with `contradictions`
  present-and-empty and zero uncited claims.
- **PLUS** a separate `get_org_chart()` unit test (the real home of `get_org_subtree`) via
  the fake → covers the hierarchy-assembly serving surface DB-free.

### I8 — Combined coverage: **measure first, gate later** (revised per Stage-3 CRITICAL)
Stage-3 review flagged that (a) `coverage combine` across two **separate** `ubuntu-latest`
runners is impossible without artifact upload/download, and (b) flipping
`coverage.require_report: true` before the combined number is known/wired would **red every
PR and block deploy** (current combined coverage is unmeasured). Revised, de-risked plan:
- `.github/workflows/dev-rules-ci.yml`: add `--cov=helixpay --cov-report=` to **both** the
  `gateway` (unit) and `integration` (db) pytest invocations; each uploads its `.coverage`
  data file via `actions/upload-artifact`. Add a **third `coverage` job**
  (`needs: [gateway, integration]`) that downloads both, runs `coverage combine` +
  `coverage xml` + `coverage report`, and uploads `coverage.xml`. This **surfaces the real
  union number as an advisory artifact** — closing the measurement blind spot.
- **Do NOT flip `coverage.require_report: true` in this sprint.** The enforcing flip is
  explicitly **deferred**: it lands only once the combined number is observed ≥ 80% (a
  one-line follow-up commit, or a tracked SP_032 item if the measured number is below 80%
  and needs real coverage work first). Gating on an unverified threshold is the
  self-blocking trap the review caught. `.validators.yml` is left at `require_report: false`
  (advisory) this sprint; the plan records the measured number in the Outcome.

### I9 — Resolve the three xfailed pre-existing `db` failures
- **(a)(b) org-chart `as_of` (D3):** `test_get_org_chart_as_of_before_roster_is_empty`
  (`test_query_integration.py`) + `test_org_subtree_as_of_filters_reporting_lines`
  (`test_repository_integration.py`) assert an early `as_of` empties the chart. Per SP_011,
  seeded `reports_to`/`dotted_line_to` edges are **intentionally undated** (`as_of=None`) so
  the export-dated `org-chart.md` edge doesn't dedupe away. An undated edge has **no
  temporal bound** and *correctly* remains visible under any `as_of`. **D3: the test
  expectation is stale — fix the tests** to assert undated edges persist; do **not** make
  `get_org_subtree` filter undated edges (that would regress SP_011). Remove `xfail`.
  **Strengthened per Stage-3 architect:** the rewritten tests must pin **both** facts so the
  temporal-filter coverage isn't silently lost — (1) an **undated** edge persists under an
  early `as_of`, AND (2) a genuinely **dated** edge (explicit `as_of`/`valid_to`) IS
  correctly filtered out before its `as_of` / after its `valid_to`.
- **(c) live detector (D4):** `test_live_detector_meets_baseline`
  (`test_contradiction_recall.py`) errors on an empty CI pgvector. **D4: graceful skip.**
  Per Stage-3 architect, the failure is `relation "contradictions" does not exist`
  (**schema absent**), which raises *before* any row-count check — so the guard must detect
  the **missing relation** (`to_regclass('contradictions') IS NULL`, or catch the
  undefined-table error) and `pytest.skip`, not merely floor on claim count. Remove `xfail`.

### I10 — FakeRepo consolidation: documented decision (descoped, see correction #3)
Record in this plan + the post-impl notes that query tests already share
`query/fakes.py:FakeRepository` and the ingest-side stubs stay intentionally minimal. No
file churn.

### I11 — (stretch) Hypothesis property tests for `normalize.py` / `coerce.py`
Only if `hypothesis` is already importable in the toolchain; otherwise **deferred** to
avoid adding a dependency inside a Standard sprint (would itself need the full lifecycle).

---

## Testing Strategy

TDD per `practices/GL-TDD.md`. Split by what the no-local-DB env can verify:

- **DB-free, TDD'd and run locally before push** (failing test first): I1 gateway
  interpreter (`test_dev_gateway_interpreter.py`); I4 N+1 cache + I7 `ask()` branches
  (`test/unit/query/test_engine_branches.py`, all on `query/fakes.py:FakeRepository` — a
  counting fake asserts the cache collapses duplicate-term lookups; the four branch tests
  assert multi-entity / temporal / org-subtree / synthesis-failure behavior).
- **CI `integration`-job-verified** (real `pgvector/pgvector:pg16`, cannot run locally):
  I2 assert→raise and I5 SQL-compose are behavior-preserving and exercised by the existing
  db suite; I9 removes the three `xfail`s so the formerly-skipped tests must now pass green.
- **Non-code**: I3 docstring + I6/D1 audit-layer comment + I10 are doc/decision-only (no
  test); I8 is CI/config wiring validated by a green combined-coverage run.

Gate: `uv run pytest test` (DB-free subset locally) + `uv run mypy helixpay` clean + the
dev-gateway runs to completion **without a bypass**; full `db` suite green in CI.

### Pre-Implementation Review

- **Iteration 1** — Reviewer: architect-review agent (independent). Severity: MEDIUM (verdict APPROVE-WITH-CHANGES). Files reviewed: workspace/sprints/SP_031_serving_path_hardening.md, helixpay/query/engine.py, helixpay/db/repository.py, helixpay/audit/run.py, test/integration/query/test_query_integration.py, test/integration/db/test_repository_integration.py, test/golden/test_contradiction_recall.py.
  - All three load-bearing decisions verified sound against code: **D2** the per-`ask()` cache adds no frozen-contract surface (the serving path is fully read-only; `resolve_entity` is a pure name-keyed read, so memoizing by term is correctness-safe and even preserves ambiguous-→None); **D1** accept-and-document is proportionate (audit is read-only census; the frozen `Repository` exposes no census reads — adding them would be the fork-the-frozen-type anti-pattern); **D3** the code is correct and "fix the test" masks nothing (an undated SP_011 edge satisfies `as_of IS NULL` and must remain visible under any `as_of`). Tier **Standard** confirmed (one runtime seam, no schema/contract surface).
  - **Required changes folded in:** (MEDIUM/D2) pin the cache **fresh-per-`ask()`, not instance-level** + test two `ask()` calls each re-resolve → I4; (MEDIUM/D3) rewritten tests must also assert a **dated** edge IS filtered, not only that undated persists → I9(a)(b); (MEDIUM/D4) guard the **relation-missing** (schema-absent) case, not a row-count floor → I9(c); (LOW/D1) put the justification **at the import site** → I6.
- **Iteration 2** — Reviewer: code-review agent (independent). Severity: CRITICAL (verdict APPROVE-WITH-CHANGES). Files reviewed: scripts/dev-gateway.py, test/unit/query/fakes.py, helixpay/query/engine.py, .github/workflows/dev-rules-ci.yml, .validators.yml, validators/validate_tdd.py.
  - **(CRITICAL/I8)** `coverage combine` across two separate CI runners is impossible without artifact upload/download, and flipping `require_report: true` before the combined number is known would red every PR and block deploy → **resolved**: I8 revised to measure-first (third `coverage` job over uploaded artifacts, advisory) and the enforcing flip **deferred** until the number is observed ≥80%; `.validators.yml` stays `require_report: false` this sprint.
  - **(HIGH/I4-I7)** `FakeSynthesizer` has no raise mode and `fakes.py` is not in `touches_paths` → **resolved**: the synthesis-failure test uses an **inline** raising `FakeSynthesizer` subclass; `fakes.py` stays untouched. **(HIGH/I7)** "temporal"/"org-subtree" branch names were inaccurate (`ask()` never calls `get_org_subtree`) → **resolved**: I7 branches re-described to the genuine `ask()` routes + a separate `get_org_chart()` test. **(MEDIUM/I4)** cache-key normalization boundary → test includes a whitespace/case variant. **(MEDIUM/I1)** gateway interpreter precedence (`$VIRTUAL_ENV` → `.venv/bin/python` → `sys.executable`) confirmed correct; path-existence is the right gate; document the `run_all.py` propagation chain in the test docstring.

### Post-Implementation Review

- **Iteration 1** — Reviewer: code-review agent (sees only diff + tests, never this plan). Severity: TBD. Files reviewed: (all touches_paths).
  _(to be filled after tests pass; verify any CRITICAL against runtime/CI evidence per Core Rule 5)_

## Success Criteria

- DB-free locally: `_project_python` test, `ask()` branch tests, N+1 cache test green;
  `uv run mypy helixpay` clean; **the dev-gateway now runs to completion without a bypass.**
- CI `integration` job green with the three former-`xfail` tests now **passing** (xfail
  removed) and the assert→raise / SQL-compose edits exercised against real Postgres.
- Combined coverage report **produced and surfaced as an artifact** (the real union number
  recorded in the Outcome); the enforcing `require_report` flip is **deferred** until that
  number is observed ≥80% (not gated this sprint — Stage-3 CRITICAL).
- The I4 cache is **fresh-per-`ask()`** (test proves two `ask()` calls each re-resolve).
- `CLAUDE.md` + `workspace/CLAUDE_GOTCHAS.md` carry the audit-layer (D1) gotcha.

## Hand-off

_Pending implementation._
