---
sprint_id: SP_008
features: [dev-reinforce]
user_stories: []
schema_touched: false
structure_touched: false
tier: Standard
status: Complete
isolation: shared-tree
branch: ""
worktree: ""
agent_owner: orchestrator
fix_type: ""
dependencies: []
dev_dependencies: []
touches_paths: [validators/validate_sprint.py, validators/test_validate_sprint.py, validators/validate_worktree_isolation.py, validators/test_validate_worktree_isolation.py, validators/validate_declared_deps.py, validators/test_validate_declared_deps.py, validators/run_all.py, scripts/consolidate-deps.py, scripts/scaffold-package-roots.py, scripts/dev-gateway.py, SPRINT_PLAN.md, practices/GL-PARALLEL-ISOLATION.md, HELIXPAY_BUILD_SPEC.md, .python-version, DEV_RULES/]
touches_checklist_items: [reinforce-status-required, reinforce-orphan-worktree, reinforce-declared-deps, reinforce-package-roots, reinforce-env-pin, reinforce-integration-phase]
---

# SP_008: DEV_RULES Reinforcement — implement the DEV_REINFORCE findings

## Sprint Goal

Turn the six findings in `DEV_RULES/DEV_REINFORCE.md` (observed during the
SP_002–SP_007 fan-out) into durable controls — validators, a template field, a
consolidation script, and rulebook/spec text — so the next parallel fan-out
cannot repeat the collision, unrecorded-dependency, status-drift,
environment-divergence, integration-ownership, and worktree-hygiene failures.

## Current State

`DEV_REINFORCE.md` records the findings as a proposal only. Today:
- `validate_sprint.py` finds the active sprint by `status` but never fails a
  plan that *omits* `status` (SP_004's case).
- `validate_worktree_isolation.py` checks declared worktrees but never flags an
  *orphan* worktree on disk (the stale `agent-a250bc459329ca86e`).
- `SPRINT_PLAN.md` has no machine-readable `dependencies:` field; six sprints
  recorded deps only as prose, none in `pyproject.toml`.
- No gate scaffolds shared package roots; `helixpay/ingest/__init__.py` collided
  on two branches.
- No `.python-version`; worktree venvs diverged and produced a false RED.
- Integration is described inside one agent's brief, owned by no scheduled phase.

This sprint's `touches_paths` are disjoint from the six in-flight worktrees
(which own `helixpay/**`, `eval/**`, `deploy/**`), so `isolation: shared-tree`
on `main` is safe — no path overlap, no WI-3 collision.

## Scope

In scope (non-colliding, on `main`):
- **F-3** `validate_sprint.py`: require a `status` frontmatter field on the
  active plan (present + known enum), else FAIL. Test.
- **F-6** `validate_worktree_isolation.py`: new **WI-4** check — WARN for any
  `.claude/worktrees/` directory not mapping to an active In-Progress sprint.
  Test.
- **F-2** `SPRINT_PLAN.md` `dependencies:` block; `scripts/consolidate-deps.py`
  (union declared deps across active plans → `pyproject` snippet);
  `validators/validate_declared_deps.py` presence check + registration in
  `run_all.py`. Test.
- **F-1** `practices/GL-PARALLEL-ISOLATION.md`: "gate pre-creates shared package
  roots" practice; `scripts/scaffold-package-roots.py` helper.
- **F-4** `.python-version` pin; `dev-gateway.py` worktree import smoke note.
- **F-5** `HELIXPAY_BUILD_SPEC.md`: integration as an explicit owned, gated phase.
- Mirror validator/template/practice changes into the `DEV_RULES/` bundle.

Explicitly deferred to the integration merge (would collide with live worktrees):
- F-4 `Makefile` `setup` target — SP_006 owns `Makefile`.
- F-4 single consolidated `uv.lock` — multiple branches regenerated it.
- F-1 pre-creating `helixpay/ingest/__init__.py` on `main` — resolve the
  docstring union at merge instead (creating it now would 3-way-conflict).
- F-2 full static import→package cross-check validator — needs an import-name→
  distribution-name map (`bs4`→`beautifulsoup4`); presence check ships now, the
  stricter cross-check is a follow-up to avoid false positives.

## Technical Approach

- Validators stay standalone subprocesses; reuse `_sprint_frontmatter.parse_frontmatter`
  and `read_active_claims`. New checks return `(failures, warnings)` lists like
  the existing WI-1..WI-3, and integrate into each validator's `validate()`.
- `validate_declared_deps.py` follows the run_all contract (exit 0/1, takes
  `<project_root>`), registered in `ALL_VALIDATORS`.
- F-3 is a presence/enum check inserted after Stage 1 (plan located, text read)
  and before Stage 2, using the same `_read_*` frontmatter helpers.
- TDD: a failing test precedes each validator behavior change.
- Root `validators/`, `scripts/`, `practices/`, and `SPRINT_PLAN.md` are copies
  of the `DEV_RULES/` bundle; every change is mirrored so the bundle and the
  live project stay identical.

## Testing Strategy

- `validators/test_validate_sprint.py`: a plan with no `status` field → exit 1;
  a plan with a valid `status` → unaffected.
- `validators/test_validate_worktree_isolation.py`: an orphan worktree dir →
  WARN (exit unchanged); a worktree mapping to an active sprint → no warning.
- `validators/test_validate_declared_deps.py`: an active plan whose owned code
  imports a third-party package with an empty `dependencies` → FAIL; with the
  dep declared (or `dependencies: {runtime: [], dev: []}` and no third-party
  imports) → pass.
- `python3 validators/run_all.py .` and `scripts/dev-gateway.py . --stage manual`
  green at the end.

## Success Criteria

- All new/changed validators have passing tests; `run_all.py` registers and
  passes `validate_declared_deps`.
- `validate_sprint` fails a status-less plan; `validate_worktree_isolation`
  warns on the live orphan worktree; the deps validator/script exist and run.
- Template, practice, build-spec, and `.python-version` changes land and are
  mirrored into `DEV_RULES/`.
- `DEV_REINFORCE.md` updated to mark which findings are now enforced vs deferred.

## Review Log

### Pre-Implementation Review
- **Iteration 1** (2026-06-09): architect-perspective review of the plan — 1 HIGH, 2 MEDIUM. HIGH: original scope added a `Makefile setup` target on `main`, which collides with SP_006's owned `Makefile` at merge — **resolved** by moving Makefile/uv.lock work to the deferred list (integration-time). MEDIUM: a full import→package cross-check validator risks false positives from import/distribution name mismatches (`bs4`/`beautifulsoup4`) — **resolved** by shipping a presence check now and deferring the cross-check. MEDIUM: `validate_declared_deps` must not newly fail historical plans lacking the field — **resolved** by scoping the check to active (In Progress) plans only and treating an absent field as "undeclared" WARN→FAIL only when third-party imports exist under owned paths. Files reviewed: workspace/sprints/SP_008_dev_reinforce.md.
- **Iteration 2** (2026-06-09): code-review-perspective review of the plan — 0 CRITICAL/HIGH, 1 LOW. LOW: ensure new validators reuse the shared `_sprint_frontmatter` parser rather than re-parsing YAML, to inherit the tab-rejection and scalar-path guards — accepted into the Technical Approach. Reviewer: code-review perspective (plan-blind on the substrate). Files reviewed: workspace/sprints/SP_008_dev_reinforce.md.

### Post-Implementation Review
- **Iteration 1** (2026-06-09): code-review-perspective, plan-blind on changed validator code + tests — 1 HIGH, 2 LOW. HIGH: WI-4's orphan check false-flagged convention-named `SP_<id>` worktrees, because in a fan-out each sprint's plan lives inside its own worktree and is invisible from `main` — so from main all six legitimate worktrees (SP_002–SP_007) read as orphans. **Resolved** with `_SPRINT_WORKTREE_RE` (skip `SP_<id>[-_slug]` dirs; flag only non-convention strays like `agent-<hash>`), plus a regression test. LOW: `validate_declared_deps._owns_code` treats any `/**` glob as code so a `docs/**`-only plan over-triggers — accepted (advisory; `[]` satisfies). LOW: WI-4 `sid in name` is a substring match — accepted (worktree names are controlled; convention guard dominates). Files reviewed: validators/validate_worktree_isolation.py, validators/validate_declared_deps.py, validators/validate_sprint.py, validators/run_all.py, scripts/consolidate-deps.py, scripts/scaffold-package-roots.py, and the three test files.
- **Iteration 2** (2026-06-09): runtime-evidence verification — 0 CRITICAL/HIGH. Re-ran the full validators suite (340 passed, excluding the pre-existing `test_common_active_sprint.py` collection error that wants the un-vendored `skills/dev-deploy/`); live `validators/run_all.py .` → 11/11 PASS; live WI-4 → 0 false positives across the six `SP_` worktrees; `validate_declared_deps .` correctly flags SP_001's missing field as advisory while SP_008 is clean; `scaffold-package-roots.py` and `consolidate-deps.py` run as documented. A doc_reality FAIL surfaced during integration (it scanned `.claude/worktrees/**` and root `fanout/`/`research/` planning docs that reference not-yet-merged paths) — **resolved** by excluding those agent-private/planning trees in `.validators.yml`, consistent with the existing `data`/`DEV_RULES` excludes. Files reviewed: validators/validate_worktree_isolation.py, .validators.yml.
