---
sprint_id: SP_017
tier: Standard
features: [coverage-gate-wiring, seam-redundancy-removal, antipattern-fixes, dbfree-coverage-gaps]
user_stories: []
schema_touched: false
structure_touched: false
status: Complete
isolation: branch-only
branch: sprint/SP_017-test-hygiene-and-coverage
worktree: ""
agent_owner: "Agent (test hygiene + coverage)"
fix_type: ""
dependencies: []
dev_dependencies: [pytest-cov]
touches_paths:
  - pyproject.toml
  - test/unit/ingest/test_extractor.py
  - test/unit/eval/test_ledger_seam.py
  - test/unit/ingest/test_coerce.py
  - test/unit/scripts/test_prod_seed.py
  - test/unit/scripts/test_verify_mcp.py
  - test/golden/test_harness.py
  - test/unit/audit/test_traps.py
  - test/unit/audit/test_report.py
  - test/unit/db/test_migrate.py
  - test/unit/api/test_dates.py
touches_checklist_items: [cov-wire-pytest-cov, cov-emit-coverage-xml, cov-validate-tdd-report, redundancy-extractor-trim, redundancy-ledger-seam-trim, antipattern-coerce-split, antipattern-prod-seed-regex, antipattern-verify-mcp-deadmock, antipattern-split-fused-tests, gap-audit-report-test, gap-db-migrate-test, gap-api-dates-test]
---

# SP_017: Test Hygiene + Coverage-Gate Wiring

> Hygiene pass over the existing 559-test suite (0 failing, 523 passing, 36
> environment-gated skips). No production code changes — only dev tooling
> (`pytest-cov`), test edits, and three new DB-free unit-test files. Operates
> sequentially on the materialized tree; no concurrent writer. Prior sprints'
> test files (SP_014 `test_coerce.py`/`test_extractor.py`) are on disk and are
> edited here for hygiene, not re-developed.

## Sprint Goal

Turn the suite from "green but unmeasured + redundant at the seams" into a
**measured, lean, anti-pattern-free** suite, per `GL-TDD.md`:

1. **Make the coverage gate real.** `pytest-cov` is not installed and no
   `coverage.xml` has ever been produced, so `validators/validate_tdd.py`'s
   line≥80%/branch≥75% gate runs in advisory no-op mode. Wire it and report the
   real numbers (report-don't-block: `require_report` stays `false`).
2. **Remove seam redundancy** — the extractor re-tests coerce/ledger behavior
   those modules already own; `test_ledger_seam.py` re-runs `test_check_smoke.py`'s
   verdict matrix.
3. **Fix GL-TDD anti-patterns** — conditional logic in tests, loop-with-`raise`,
   dead mock scaffolding, fused multi-behavior tests.
4. **Fill three DB-free coverage gaps** — `audit/report.py`, `db/migrate.py`
   statement-split (flagged fragile in CLAUDE.md gotchas), `api/_dates.py`.

## Current State

- Suite: 559 collected, 523 pass, 0 fail, 36 skip (34 DB-gated, 2 API-key-gated),
  ~1s runtime. No coverage measurement wired anywhere.
- Redundancy: `test_extractor.py` re-asserts the ledger probe contract and coerce
  math; `test_ledger_seam.py` re-runs the `doc_verdict` matrix owned by
  `test_check_smoke.py`.
- Anti-patterns: `test_coerce.py` branches inside parametrized tests;
  `test_prod_seed.py` uses loop-with-`raise`; `test_verify_mcp.py` carries ~50
  lines of inert async-mock scaffolding (dead patch target — `probe()` imports
  the client inside the function body); fused two-scenario tests in
  `test_harness.py` (×3) and `test_traps.py` (×1).
- Gaps (DB-free, untested): `audit/report.py` (`format_report`, `report_to_dict`),
  `db/migrate.py` (`_statements` split), `api/_dates.py` (`parse_as_of`).

## Desired End State

- `uv run pytest test --cov=helixpay --cov-report=xml` emits `coverage.xml`;
  `validate_tdd.py` reports real line/branch coverage (advisory, non-blocking).
- Extractor and ledger-seam tests assert only the behavior they own; the verdict
  matrix and coerce math live in exactly one place each.
- No conditional/loop logic in test bodies; no dead mock scaffolding; one behavior
  per test function.
- Three new DB-free test files cover the named gaps. Suite stays green; net test
  count roughly flat (redundant cases removed, gap + split cases added).

## Scope

In: `pyproject.toml` (dev dep + cov config), the named test files, three new test
files. Out: all production code under `helixpay/` (no behavior changes); the
DB-gated integration tests (unchanged); enforcing a hard coverage threshold
(deferred — report-don't-block per operator decision).

## Technical Approach

**Phase 1 — Coverage gate (cov-*)**
- Add `pytest-cov` to `[project.optional-dependencies] dev` in `pyproject.toml`
  (there is **no** `[dependency-groups]` table — the dev extras live under
  `[project.optional-dependencies]`). Do **not** add a global `--cov` to `addopts`
  (it would slow the inner-loop unit runs and break `-p no:cacheprovider`
  ergonomics); instead document the coverage invocation and use it in the
  gateway/CI test step.
- Run `uv run pytest test -o addopts="" --cov=helixpay --cov-branch --cov-report=xml`
  to emit `coverage.xml`; then run
  `uv run python validators/validate_tdd.py . --src-dir helixpay` and record the
  reported line/branch numbers in the post-impl review. **`--src-dir helixpay` is
  mandatory** — `validate_tdd.py` defaults `--src-dir` to `src/`, which does not
  exist here, so the default invocation returns early ("no source files") and
  never parses `coverage.xml` (plan-review B1). **`--cov-branch` is also mandatory**
  — without it `coverage.xml` records `branch-rate=0`, which spuriously fails the
  validator's branch gate (impl finding). `require_report` stays `false` in
  `.validators.yml` (already false — no edit).
- **Measured result (post-Phase-4):** line **83.7%** (≥80% ✓), branch **76.5%**
  (≥75% ✓). The three new DB-free test files lifted both metrics over the GL-TDD
  thresholds — the coverage gate, which is the machine-enforced part of GL-TDD, now
  **passes** (the operator's report-don't-block guard is therefore moot for coverage).
  Baseline before this sprint was line 81.3% / branch 73.3%.
- **Known advisory:** `validate_tdd --src-dir helixpay` still exits FAILED on its
  *structural* "no test file found" check for ~35 modules (e.g. `ingest/extract/coerce.py`,
  `api/_dates.py`). This is a **pre-existing validator/layout mismatch**, not a real gap:
  the validator expects a test at the nested source path (`test/unit/ingest/extract/…`)
  while this repo mirrors tests at `test/unit/<package>/…` — the tests exist, the path
  map doesn't. It is why the project runs this validator advisory (`require_report:false`)
  and does not gate on it. Out of scope to fix here; logged for a future tooling sprint.

**Phase 2 — Redundancy (redundancy-*)**
- `test_extractor.py`: replace `test_ledger_probe_has_frozen_shape` with a single
  **end-to-end** test that drives the real `ChunkExtractor.extract → ledger →
  probe()` path and asserts the frozen three-key probe shape — preserving the only
  extractor-level proof that the probe shape holds through the real path (the
  isolated shape is owned by `test_ledger.py`, but no other extractor test reaches
  `ex.ledger.probe()`; plan-review N1). Reduce
  `test_q1_as_of_claim_is_retained_after_coerce` /
  `test_unmappable_subject_type_is_dropped_and_counted` to a single wiring test
  that retains exactly the **ledger-counting** assertions (`items_dropped`,
  `dropped_by_reason["unmappable_enum"]`) which `test_coerce.py` does NOT cover,
  and drops the re-verification of coerce math (owned by `test_coerce.py`). Drop
  the duplicate `manages`-inversion assertion (owned by `test_coerce.py`).
- `test_ledger_seam.py`: keep `test_real_ledger_probe_shape_matches_check_smoke_contract`
  + one PASS + one unseen-URI→INCOMPLETE case (shape-compatibility proof); remove
  the verdict-matrix duplicates (empty→FAIL, truncated→FAIL, drop→INCOMPLETE) that
  `test_check_smoke.py` already owns.

**Phase 3 — Anti-patterns (antipattern-*)**
- `test_coerce.py`: split the `if expected is None …` branching parametrized tests
  into two single-path parametrized tests (one for value mapping, one for the
  `coercions`-recorded flag).
- `test_prod_seed.py`: replace the line-loop-with-`raise` secret-leak checks with a
  single `re.search` assertion that matches the **`$`-expansion** form adjacent to
  `echo` (`re.search(r"echo[^#\n]*\$(DATABASE_URL|LOCAL_DB_URL|POSTGRES_PASSWORD)", text)`)
  and **must not** match the placeholder usage-hint line `prod_seed.sh:165`
  (`echo "  REMOTE_DATABASE_URL=postgres://user:pass@host:..."`) nor `#`-comment
  lines — a naive `echo.*DATABASE_URL` would false-fail a green script
  (plan-review B2). Verify the assertion still passes against the current script.
- `test_verify_mcp.py`: remove the inert `_fake_streamable`/`_fake_session`/
  `patch.dict`/`patch(...)` scaffolding in **both** dead-mock tests —
  `test_probe_uses_streamable_http_not_stdio` (the patch target is dead because
  `probe()` imports the client inside its body) **and**
  `test_full_probe_roundtrip_with_mocked_session` (builds `session_mock`/`tool`/
  `tools_result`/`call_result` that `_fake_anyio_run` ignores; plan-review N3).
  Keep the real AST/source guard and the observable `anyio.run` behavior as each
  test's content.
- Split fused two-scenario tests into one-behavior-each: `test_harness.py`
  (`test_link_fact_found_and_reversed`, `test_check_surfaces_and_no_false_contradiction`,
  `test_goal_verdict_green_only_when_all_three`, and — for consistency with the
  one-behavior criterion — `test_check_cites_source_and_as_of`; plan-review N8) and
  `test_traps.py` (`test_two_marias_distinct_pass_and_fail`).

**Phase 4 — Gaps (gap-*)**
- `test/unit/audit/test_report.py`: assemble an `AuditReport(total_claims, counts,
  violations, sample, traps, evidence_columns_present)` (`audit/models.py:90-97`)
  from scratch — incl. `Violation` and `TrapResult` — and assert `format_report`
  rendering + `report_to_dict` shape. There is no reusable `AuditReport` factory
  (`test_invariants.py` only has a `ClaimRecord` `_rec` builder; plan-review N4).
  All frozen dataclasses, no DB.
- `test/unit/db/test_migrate.py`: table-driven tests for `migrate._statements`
  (comment-strip + `;`-split correctness, the CLAUDE.md-flagged fragile seam),
  driving a raw SQL string — no DB. Testing the `_statements` seam directly is the
  documented fragility unit; noted as an intentional exception to the
  no-private-method rule.
- `test/unit/api/test_dates.py`: table-driven coverage for `parse_as_of`
  (valid ISO → `date`; `None`/`""` → `None`; malformed → `pytest.raises(ValueError)`
  per `api/_dates.py:16-23`; plan-review N5). Pure function.

## Testing Strategy

- Every claim of redundancy/staleness is re-verified by reading the target file
  before deletion or rewrite (CLAUDE.md Rule 5). A removed assertion must be
  provably covered elsewhere (cite the owning test) before it is deleted.
- After each phase: `uv run pytest test -o addopts="" -q` stays green; the final
  run adds `--cov=helixpay --cov-report=xml`.
- New gap tests are written RED-first against the existing (already-passing)
  source — i.e. confirm they exercise real behavior by mutating an assertion to
  fail, then correcting (characterization tests over stable code).

## Risks & Mitigations

- *Deleting a "redundant" assertion that was actually the only cover* → before any
  deletion, grep the suite for the behavior and cite the owning test in the diff;
  coverage.xml from Phase 1 is the backstop (line/branch must not drop).
- *Path overlap with materialized SP_014 test files* (`test_coerce.py`,
  `test_extractor.py`) → sequential single-writer session, no concurrent agent;
  edits are hygiene-only and preserve every behavioral assertion's coverage.
- *Splitting fused tests changes counts* → expected and benign; the post-impl
  review records the before/after count and confirms net behavior coverage is
  preserved or increased.
- *`pytest-cov` slows the suite* → not added to `addopts`; coverage is an explicit
  opt-in invocation, inner-loop runs stay ~1s.

## Success Criteria

- `coverage.xml` is produced and `validate_tdd.py . --src-dir helixpay` reports real
  line/branch numbers (advisory, non-blocking).
- No conditional logic, loops, or dead mock scaffolding remain in the edited files;
  one behavior per test function in the split files.
- Redundant extractor/ledger-seam assertions removed with the owning test cited.
- Three new DB-free test files pass and exercise `format_report`/`report_to_dict`,
  `_statements`, and `parse_as_of`.
- `uv run pytest test -o addopts=""` green (0 failing); `uv run mypy helixpay` clean
  (no production code touched, so this should be unchanged).

### Pre-Implementation Review

> Standard tier — floor = 2.

- Iteration 1 — independent architect-reviewer (plan-blind to author intent); verdict
  **approve-with-changes**. Verified every redundancy/anti-pattern claim file-by-file
  against source. BLOCKING: B1 (`validate_tdd.py` no-ops without `--src-dir helixpay`),
  B2 (prod_seed regex false-positives on the `prod_seed.sh:165` usage hint unless it
  matches `$`-expansion and skips comments). NON-BLOCKING: N1 (retain extractor-level
  end-to-end probe-shape + ledger-counting assertions), N3 (strip dead mocks in the
  second verify_mcp test too), N4 (no reusable `AuditReport` factory — build from
  scratch), N5 (`parse_as_of` malformed → `ValueError`), N7 (`[project.optional-dependencies]
  dev`, no `[dependency-groups]`), N8 (also split `test_check_cites_source_and_as_of`).
- Iteration 2 — author reconciliation: all BLOCKING (B1, B2) and NON-BLOCKING (N1, N3,
  N4, N5, N7, N8) findings folded into Technical Approach + Success Criteria above. No
  CRITICAL/HIGH findings remain open; no architectural concerns (test-only, no production
  code). Cleared to implement.

### Post-Implementation Review

- Iteration 1 — independent plan-blind `code-reviewer` over the working-tree test diff +
  new files. Verdict **Approve**: no BLOCKING findings, **no coverage loss** (every removed
  extractor/ledger_seam assertion confirmed owned by `test_coerce.py` / `test_ledger.py` /
  `test_check_smoke.py`); conftest marker fix confirmed correct (all db-marked tests still
  skip); prod_seed regex confirmed to catch real `$`-expansion leaks and not the
  `prod_seed.sh:158/163/165` diagnostic lines; new files single-behavior, AAA, no
  conditional/loop logic. One non-blocking suggestion (clearer `pytest.fail` form in
  `test_prod_seed.py`) — **applied**.
- Iteration 2 — author re-verification of runtime evidence:
  - `uv run pytest test -o addopts=""` → **596 passed, 36 skipped, 0 failed**.
  - Coverage gate (`--cov=helixpay --cov-branch`): **line 83.7% ≥80% ✓, branch 76.5% ≥75% ✓**
    (up from 81.3% / 73.3% baseline; gap-fill crossed the branch threshold).
  - `uv run mypy helixpay` → clean (70 files; confirms no production code altered).
  - `validate_doc_reality`, `validate_doc_freshness`, `validate_worktree_isolation`
    (WI-3 cleared after `isolation: branch-only`), `validate_declared_deps`,
    `reconcile-sprint-frontmatter` → PASS.
  - Pre-existing/out-of-scope, not introduced here: dev-gateway's lifecycle stages fail on
    the **separate** active sprint SP_016 (empty review sections — untouched by this sprint);
    `validate_tdd`'s structural "no test file found" check (validator/layout path mismatch,
    advisory). Both logged above.

## Outcome

Complete. Coverage gate is now real and **passing both thresholds**; seam redundancy and
the named GL-TDD anti-patterns removed; three DB-free gaps filled; a latent `conftest.py`
false-skip bug (any test under a `db/`-named path) fixed. Net test count change (no-DB):
523 → 596 passing (+ the previously false-skipped `test/unit/db` now runs). Author-blind
review approved; runtime evidence green.

## Hand-off

- `coverage.xml` becomes the standing artifact for the line/branch gate; future
  sprints run the cov invocation in the gateway test step. The leaner seam tests
  define the single owner for the ledger-probe contract (`test_ledger.py`), the
  coerce math (`test_coerce.py`), and the `doc_verdict` matrix (`test_check_smoke.py`).
