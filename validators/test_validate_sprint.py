"""
Tests for validate_sprint.py

Validator contract (7 stages, subset enforced):
- Stage 1: Sprint plan file exists in the sprints directory
- Stage 2: Sprint plan has required sections (Sprint Goal, Scope, Technical Approach,
           Testing Strategy, Success Criteria)
- Stage 3: Review Log has at least 2 entries, each with issue count + severity + files reviewed
           Rubber-stamp "Looks good" entries are rejected
- Stage 5: Post-Implementation Review Log has at least 2 entries
- Stage 7: PROGRESS.md updated (git-based check, advisory)
- When no active sprint is found in PROGRESS.md, exits 1 unless --allow-no-sprint or
  SDA_ALLOW_NO_SPRINT=1 is set (in which case exits 0 with advisory)
- Returns 0 on pass, 1 on failure
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

VALIDATOR = Path(__file__).parent / "validate_sprint.py"

REQUIRED_SECTIONS = [
    "## Sprint Goal",
    "## Scope",
    "## Technical Approach",
    "## Testing Strategy",
    "## Success Criteria",
]

VALID_REVIEW_LOG = """
## Review Log

### Pre-Implementation Review
- **Iteration 1** (2026-01-01): Architect found 2 HIGH, 1 MEDIUM. Files reviewed: src/lib/service.py, src/models/entity.py
- **Iteration 2** (2026-01-02): Code-reviewer found 0 CRITICAL/HIGH. Files reviewed: src/lib/service.py

### Post-Implementation Review
- **Iteration 1** (2026-01-03): Found 1 HIGH issue. Files reviewed: src/lib/service.py, test/unit/test_service.py
- **Iteration 2** (2026-01-04): Found 0 issues. Files reviewed: src/lib/service.py
"""


def run_validator(project_root: Path, *extra_args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(project_root), *extra_args],
        capture_output=True,
        text=True,
    )


def make_sprints_dir(root: Path) -> Path:
    sprints = root / "00_IMPLEMENTATION" / "SPRINTS"
    sprints.mkdir(parents=True, exist_ok=True)
    return sprints


def make_full_sprint_plan(sprints_dir: Path, sprint_id: str, review_log: str = "") -> Path:
    """Write a sprint plan that passes all stage checks."""
    content = f"""# Sprint Plan: {sprint_id}

## Sprint Information
**Sprint ID:** {sprint_id}
**Duration:** 3 days
**Start Date:** 2026-01-01

## Sprint Goal
Deliver the feature completely.

## Scope

### Features to Implement
- **F-001:** Core functionality
  - [ ] Task A
  - [ ] Task B

### Out of Scope
Nothing explicit.

## Technical Approach

### New Files
| File | Purpose |
|---|---|
| `src/lib/new_module.py` | Business logic |

### Modified Files
| File | Changes |
|---|---|
| `src/lib/existing.py` | Added new method |

### Key Design Decisions
1. Use existing patterns.

## Testing Strategy
Unit tests for all new functions, 80% line coverage target.

### Test Plan
- [ ] Unit tests for new_module
- [ ] Edge cases: empty input, None values

## Success Criteria
- [ ] All features implemented
- [ ] All tests passing
- [ ] Coverage >= 80%
- [ ] Documentation updated

## Dependencies
None.

## Rollback Plan
Revert the git commit.
"""
    if review_log:
        content += "\n" + review_log

    plan = sprints_dir / f"{sprint_id}.md"
    plan.write_text(content)
    return plan


def set_active_sprint(root: Path, sprint_id: str) -> None:
    (root / "PROGRESS.md").write_text(
        f"## Active Sprint\n**Current:** {sprint_id}\n\n## Sprint History\n"
    )


def make_tiered_sprint_plan(
    sprints_dir: Path, sprint_id: str, tier: str, review_log: str = ""
) -> Path:
    """Write a sprint plan that passes structural checks AND carries a `tier`
    frontmatter block (so validate_sprint can resolve the review floor)."""
    plan = make_full_sprint_plan(sprints_dir, sprint_id, review_log=review_log)
    body = plan.read_text()
    plan.write_text(
        f"---\nsprint_id: {sprint_id}\ntier: {tier}\nstatus: In Progress\n---\n\n{body}"
    )
    return plan


# A Micro-tier review log: one iteration per stage, each naming its reviewer.
MICRO_SINGLE_WITH_REVIEWER = """
## Review Log

### Pre-Implementation Review
- **Iteration 1** (2026-06-09): architect-reviewer found 0 CRITICAL/HIGH, 1 LOW. Files reviewed: src/lib/service.py. Reviewer: architect-reviewer

### Post-Implementation Review
- **Iteration 1** (2026-06-09): Found 0 issues. Files reviewed: src/lib/service.py. Reviewer: code-reviewer
"""

# Same single-iteration shape, but the pre-impl entry omits the Reviewer:
# annotation — the compensating guard must reject it.
MICRO_SINGLE_NO_REVIEWER = """
## Review Log

### Pre-Implementation Review
- **Iteration 1** (2026-06-09): Found 1 HIGH. Files reviewed: src/lib/service.py

### Post-Implementation Review
- **Iteration 1** (2026-06-09): Found 0 issues. Files reviewed: src/lib/service.py. Reviewer: code-reviewer
"""


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


def test_passes_complete_sprint(tmp_path: Path) -> None:
    """A sprint plan with all required sections and a valid Review Log exits 0."""
    sprints = make_sprints_dir(tmp_path)
    make_full_sprint_plan(sprints, "SP_010_Complete", review_log=VALID_REVIEW_LOG)
    set_active_sprint(tmp_path, "SP_010_Complete")

    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stderr


def test_detects_active_sprint_from_progress_md(tmp_path: Path) -> None:
    """The validator reads the active sprint ID from PROGRESS.md."""
    sprints = make_sprints_dir(tmp_path)
    make_full_sprint_plan(sprints, "SP_042_Detection", review_log=VALID_REVIEW_LOG)
    set_active_sprint(tmp_path, "SP_042_Detection")

    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# Stage 1: Sprint plan file exists
# ---------------------------------------------------------------------------


def test_fails_no_sprint_plan(tmp_path: Path) -> None:
    """When PROGRESS.md names an active sprint but the plan file is missing, fail."""
    make_sprints_dir(tmp_path)
    set_active_sprint(tmp_path, "SP_099_Missing")
    # Sprint plan file deliberately not created

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


# ---------------------------------------------------------------------------
# Stage 2: Required sections
# ---------------------------------------------------------------------------


def test_fails_sprint_plan_missing_sprint_goal(tmp_path: Path) -> None:
    """Sprint plan without '## Sprint Goal' section fails."""
    sprints = make_sprints_dir(tmp_path)
    plan = make_full_sprint_plan(sprints, "SP_020_NoGoal", review_log=VALID_REVIEW_LOG)
    content = plan.read_text()
    plan.write_text(content.replace("## Sprint Goal\n", "## REMOVED\n"))
    set_active_sprint(tmp_path, "SP_020_NoGoal")

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


def test_fails_sprint_plan_missing_testing_strategy(tmp_path: Path) -> None:
    """Sprint plan without '## Testing Strategy' section fails."""
    sprints = make_sprints_dir(tmp_path)
    plan = make_full_sprint_plan(sprints, "SP_021_NoTest", review_log=VALID_REVIEW_LOG)
    content = plan.read_text()
    plan.write_text(content.replace("## Testing Strategy\n", "## REMOVED\n"))
    set_active_sprint(tmp_path, "SP_021_NoTest")

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


def test_fails_sprint_plan_missing_sections(tmp_path: Path) -> None:
    """Sprint plan with multiple missing sections fails."""
    sprints = make_sprints_dir(tmp_path)
    plan = sprints / "SP_022_Incomplete.md"
    plan.write_text("# Sprint Plan: SP_022_Incomplete\n\nSome random notes.\n")
    set_active_sprint(tmp_path, "SP_022_Incomplete")

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


# ---------------------------------------------------------------------------
# Stage 3: Pre-Implementation Review Log
# ---------------------------------------------------------------------------


def test_fails_review_log_less_than_2_entries(tmp_path: Path) -> None:
    """Pre-implementation review log with only 1 entry fails."""
    sprints = make_sprints_dir(tmp_path)
    thin_log = """
## Review Log

### Pre-Implementation Review
- **Iteration 1** (2026-01-01): Found 1 HIGH. Files reviewed: src/lib/service.py

### Post-Implementation Review
- **Iteration 1** (2026-01-03): Found 1 issue. Files reviewed: src/lib/service.py
- **Iteration 2** (2026-01-04): 0 issues. Files reviewed: src/lib/service.py
"""
    make_full_sprint_plan(sprints, "SP_030_ThinReview", review_log=thin_log)
    set_active_sprint(tmp_path, "SP_030_ThinReview")

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


def test_fails_review_log_empty_findings_rubber_stamp(tmp_path: Path) -> None:
    """Review entries that say 'Looks good' without issue counts are rejected."""
    sprints = make_sprints_dir(tmp_path)
    rubber_stamp_log = """
## Review Log

### Pre-Implementation Review
- **Iteration 1** (2026-01-01): Looks good. Files reviewed: src/lib/service.py
- **Iteration 2** (2026-01-02): Looks good, no concerns. Files reviewed: src/lib/service.py

### Post-Implementation Review
- **Iteration 1** (2026-01-03): Found 1 HIGH. Files reviewed: src/lib/service.py
- **Iteration 2** (2026-01-04): 0 issues. Files reviewed: src/lib/service.py
"""
    make_full_sprint_plan(sprints, "SP_031_RubberStamp", review_log=rubber_stamp_log)
    set_active_sprint(tmp_path, "SP_031_RubberStamp")

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


def test_fails_review_log_missing_files_reviewed(tmp_path: Path) -> None:
    """Review entries without 'Files reviewed:' annotation fail."""
    sprints = make_sprints_dir(tmp_path)
    no_files_log = """
## Review Log

### Pre-Implementation Review
- **Iteration 1** (2026-01-01): Found 2 HIGH, 1 MEDIUM.
- **Iteration 2** (2026-01-02): Found 0 CRITICAL/HIGH.

### Post-Implementation Review
- **Iteration 1** (2026-01-03): Found 1 HIGH issue. Files reviewed: src/lib/service.py
- **Iteration 2** (2026-01-04): 0 issues. Files reviewed: src/lib/service.py
"""
    make_full_sprint_plan(sprints, "SP_032_NoFiles", review_log=no_files_log)
    set_active_sprint(tmp_path, "SP_032_NoFiles")

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


def test_fails_review_log_absent_entirely(tmp_path: Path) -> None:
    """A sprint plan with no Review Log section at all fails."""
    sprints = make_sprints_dir(tmp_path)
    make_full_sprint_plan(sprints, "SP_033_NoLog", review_log="")  # no review log
    set_active_sprint(tmp_path, "SP_033_NoLog")

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


# ---------------------------------------------------------------------------
# Stage 5: Post-Implementation Review Log
# ---------------------------------------------------------------------------


def test_fails_no_post_implementation_review(tmp_path: Path) -> None:
    """Sprint plan with pre-implementation review but no post-implementation review fails."""
    sprints = make_sprints_dir(tmp_path)
    pre_only_log = """
## Review Log

### Pre-Implementation Review
- **Iteration 1** (2026-01-01): Found 1 HIGH. Files reviewed: src/lib/service.py
- **Iteration 2** (2026-01-02): Found 0 CRITICAL/HIGH. Files reviewed: src/lib/service.py
"""
    make_full_sprint_plan(sprints, "SP_050_NoPostReview", review_log=pre_only_log)
    set_active_sprint(tmp_path, "SP_050_NoPostReview")

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


def test_fails_post_implementation_review_has_only_one_entry(tmp_path: Path) -> None:
    """Post-implementation review with fewer than 2 entries fails."""
    sprints = make_sprints_dir(tmp_path)
    one_post_log = """
## Review Log

### Pre-Implementation Review
- **Iteration 1** (2026-01-01): Found 1 HIGH. Files reviewed: src/lib/service.py
- **Iteration 2** (2026-01-02): 0 issues. Files reviewed: src/lib/service.py

### Post-Implementation Review
- **Iteration 1** (2026-01-03): Found 0 issues. Files reviewed: src/lib/service.py
"""
    make_full_sprint_plan(sprints, "SP_051_OnePost", review_log=one_post_log)
    set_active_sprint(tmp_path, "SP_051_OnePost")

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


# ---------------------------------------------------------------------------
# Advisory / no-active-sprint behaviour
# ---------------------------------------------------------------------------


def test_skips_gracefully_when_no_active_sprint(tmp_path: Path) -> None:
    """When PROGRESS.md has no active sprint and no escape hatch, validator exits 1."""
    (tmp_path / "PROGRESS.md").write_text(
        "## Sprint History\nAll complete.\n"
    )
    make_sprints_dir(tmp_path)

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stderr


def test_skips_gracefully_when_progress_md_missing(tmp_path: Path) -> None:
    """When PROGRESS.md does not exist and no escape hatch, validator exits 1."""
    make_sprints_dir(tmp_path)
    # PROGRESS.md deliberately not created

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stderr


def test_sprint_plan_in_subfolder_is_found(tmp_path: Path) -> None:
    """Sprint plan inside a SP_XXX_Description/ subfolder is also discovered."""
    sprints = make_sprints_dir(tmp_path)
    subfolder = sprints / "SP_060_Subfolder"
    subfolder.mkdir()
    make_full_sprint_plan(subfolder, "SP_060_Subfolder", review_log=VALID_REVIEW_LOG)
    set_active_sprint(tmp_path, "SP_060_Subfolder")

    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# Escape hatches — SDA_ALLOW_NO_SPRINT env var and --allow-no-sprint flag
# ---------------------------------------------------------------------------


def test_allow_no_sprint_env_var_restores_advisory(tmp_path: Path) -> None:
    """SDA_ALLOW_NO_SPRINT=1 env var causes exit 0 with advisory when no active sprint."""
    (tmp_path / "PROGRESS.md").write_text("## Sprint History\nAll complete.\n")
    make_sprints_dir(tmp_path)

    env = {**os.environ, "SDA_ALLOW_NO_SPRINT": "1"}
    result = subprocess.run(
        [sys.executable, str(VALIDATOR), str(tmp_path)],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "Advisory" in result.stderr or "advisory" in result.stderr.lower()


def test_allow_no_sprint_cli_flag_restores_advisory(tmp_path: Path) -> None:
    """--allow-no-sprint flag causes exit 0 with advisory when no active sprint."""
    (tmp_path / "PROGRESS.md").write_text("## Sprint History\nAll complete.\n")
    make_sprints_dir(tmp_path)

    result = run_validator(tmp_path, "--allow-no-sprint")
    assert result.returncode == 0, result.stderr
    assert "Advisory" in result.stderr or "advisory" in result.stderr.lower()


def test_fails_when_no_active_sprint(tmp_path: Path) -> None:
    """Without escape hatch, validator exits 1 when PROGRESS.md has no active sprint."""
    (tmp_path / "PROGRESS.md").write_text("## Sprint History\nAll complete.\n")
    make_sprints_dir(tmp_path)

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stderr


def test_missing_progress_md_fails(tmp_path: Path) -> None:
    """Without escape hatch, validator exits 1 when PROGRESS.md is missing."""
    make_sprints_dir(tmp_path)
    # PROGRESS.md deliberately not created

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stderr


# ---------------------------------------------------------------------------
# Lockfile — written on pre-impl gate pass, not on failure
# ---------------------------------------------------------------------------


def test_pre_impl_gate_writes_lockfile(tmp_path: Path) -> None:
    """When --gate pre-impl passes, .pre_impl_passed lockfile is written with sprint_id."""
    sprints = make_sprints_dir(tmp_path)
    make_full_sprint_plan(sprints, "SP_070_Lock", review_log=VALID_REVIEW_LOG)
    set_active_sprint(tmp_path, "SP_070_Lock")

    result = run_validator(tmp_path, "--gate", "pre-impl")
    assert result.returncode == 0, result.stderr

    lockfile = tmp_path / ".pre_impl_passed"
    assert lockfile.exists(), ".pre_impl_passed lockfile was not written"
    data = json.loads(lockfile.read_text())
    assert data["sprint_id"] == "SP_070_Lock"
    assert data["gate"] == "pre-impl"
    assert "passed_at" in data


def test_lockfile_not_written_on_gate_failure(tmp_path: Path) -> None:
    """When pre-impl gate fails (missing review log), lockfile is NOT written."""
    sprints = make_sprints_dir(tmp_path)
    # No review log — Stage 3 will fail
    make_full_sprint_plan(sprints, "SP_071_NoLock", review_log="")
    set_active_sprint(tmp_path, "SP_071_NoLock")

    result = run_validator(tmp_path, "--gate", "pre-impl")
    assert result.returncode == 1, result.stderr

    lockfile = tmp_path / ".pre_impl_passed"
    assert not lockfile.exists(), ".pre_impl_passed lockfile must NOT be written on failure"


# ---------------------------------------------------------------------------
# Deploy-gate scoping integration
# ---------------------------------------------------------------------------


def test_SP736_code_free_deploy_is_advisory(tmp_path: Path) -> None:
    """A provably code-free deploy (DEV_DEPLOY_CODE_CHANGED=false) must NOT
    fail on a structurally-malformed resolver-resolved sprint. This is the
    exact fleet-freeze the resolver's newest-open-plan pick caused: an
    unrelated WIP sibling skeleton plan blocking every docs-only deploy."""
    make_sprints_dir(tmp_path)
    # SP_950 is 'active' per PROGRESS but has NO plan file → Stage-1 would
    # normally FAIL (exit 1). The advisory short-circuit must pre-empt that.
    set_active_sprint(tmp_path, "SP_950_Malformed")

    env = {**os.environ, "DEV_DEPLOY_CODE_CHANGED": "false"}
    result = subprocess.run(
        [sys.executable, str(VALIDATOR), str(tmp_path)],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "ADVISORY" in result.stderr


def test_SP736_absent_env_unchanged_enforce(tmp_path: Path) -> None:
    """Env ABSENT (off-CI / local run_all.py) → fail-closed ENFORCE, i.e.
    pre-SP_736 behaviour preserved exactly (zero regression for the local
    gauntlet). Same malformed sprint must still exit 1."""
    make_sprints_dir(tmp_path)
    set_active_sprint(tmp_path, "SP_950_Malformed")

    env = {k: v for k, v in os.environ.items() if k != "DEV_DEPLOY_CODE_CHANGED"}
    result = subprocess.run(
        [sys.executable, str(VALIDATOR), str(tmp_path)],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 1, result.stderr


# ---------------------------------------------------------------------------
# Tier-aware review floor (D-1) — authoritative table in GL-SELF-CRITIQUE.md
# ---------------------------------------------------------------------------


def test_micro_tier_passes_single_iteration_with_reviewer(tmp_path: Path) -> None:
    """A Micro-tier sprint may pass with a single review iteration per stage,
    provided each lone iteration names its independent reviewer."""
    sprints = make_sprints_dir(tmp_path)
    make_tiered_sprint_plan(sprints, "SP_080_Micro", "Micro", review_log=MICRO_SINGLE_WITH_REVIEWER)
    set_active_sprint(tmp_path, "SP_080_Micro")

    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "floor: 1" in result.stderr


def test_micro_tier_fails_single_iteration_without_reviewer(tmp_path: Path) -> None:
    """A Micro single-iteration review without a 'Reviewer:' annotation is
    rejected — the compensating guard for the relaxed floor."""
    sprints = make_sprints_dir(tmp_path)
    make_tiered_sprint_plan(sprints, "SP_081_MicroNoRev", "Micro", review_log=MICRO_SINGLE_NO_REVIEWER)
    set_active_sprint(tmp_path, "SP_081_MicroNoRev")

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout
    assert "Reviewer:" in result.stderr


def test_micro_tier_is_case_insensitive(tmp_path: Path) -> None:
    """`tier: micro` (lowercased) resolves to the Micro floor of 1."""
    sprints = make_sprints_dir(tmp_path)
    make_tiered_sprint_plan(sprints, "SP_082_MicroLower", "micro", review_log=MICRO_SINGLE_WITH_REVIEWER)
    set_active_sprint(tmp_path, "SP_082_MicroLower")

    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "floor: 1" in result.stderr


def test_micro_tier_two_iterations_need_no_reviewer_annotation(tmp_path: Path) -> None:
    """When a Micro sprint runs the full 2 iterations, the second-context guard
    is already satisfied, so no 'Reviewer:' annotation is required."""
    sprints = make_sprints_dir(tmp_path)
    make_tiered_sprint_plan(sprints, "SP_083_MicroTwo", "Micro", review_log=VALID_REVIEW_LOG)
    set_active_sprint(tmp_path, "SP_083_MicroTwo")

    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stderr


def test_standard_tier_still_requires_two_iterations(tmp_path: Path) -> None:
    """A Standard-tier sprint with a single iteration fails — only Micro relaxes."""
    sprints = make_sprints_dir(tmp_path)
    make_tiered_sprint_plan(sprints, "SP_084_Standard", "Standard", review_log=MICRO_SINGLE_WITH_REVIEWER)
    set_active_sprint(tmp_path, "SP_084_Standard")

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout
    assert "floor: 2" in result.stderr


def test_unspecified_tier_defaults_to_floor_two(tmp_path: Path) -> None:
    """A sprint with no `tier` frontmatter is held to the fail-safe floor of 2."""
    sprints = make_sprints_dir(tmp_path)
    # make_full_sprint_plan writes no frontmatter at all.
    make_full_sprint_plan(sprints, "SP_085_NoTier", review_log=MICRO_SINGLE_WITH_REVIEWER)
    set_active_sprint(tmp_path, "SP_085_NoTier")

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout
    assert "floor: 2" in result.stderr


def test_unrecognized_tier_defaults_to_floor_two(tmp_path: Path) -> None:
    """An unrecognized tier value falls back to the strong floor of 2."""
    sprints = make_sprints_dir(tmp_path)
    make_tiered_sprint_plan(sprints, "SP_086_Bogus", "Gigantic", review_log=MICRO_SINGLE_WITH_REVIEWER)
    set_active_sprint(tmp_path, "SP_086_Bogus")

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout
    assert "floor: 2" in result.stderr
