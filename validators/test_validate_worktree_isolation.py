"""
Tests for validate_worktree_isolation.py — parallel-agent isolation validator.

Contract under test:
  * read-only sprints are exempt from collision checks
  * an omitted `isolation` field behaves as shared-tree (backward compatible)
  * unknown isolation value / incomplete git-worktree|branch-only → FAIL
  * duplicate branch or worktree across active sprints → FAIL
  * two non-isolated sprints with overlapping paths → FAIL when a strict tier is
    involved, WARN when both are Micro
  * properly isolated parallel sprints (distinct worktree+branch) pass even with
    overlapping paths — the validator REFINES Rule 6, it does not contradict it
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

VALIDATOR = Path(__file__).parent / "validate_worktree_isolation.py"


def _write_plan(
    sprints: Path,
    sprint_id: str,
    *,
    status: str = "In Progress",
    tier: str | None = "Standard",
    isolation: str | None = None,
    branch: str | None = None,
    worktree: str | None = None,
    touches_paths: list[str] | None = None,
) -> None:
    lines = ["---", f"sprint_id: {sprint_id}", f"status: {status}"]
    if tier is not None:
        lines.append(f"tier: {tier}")
    if isolation is not None:
        lines.append(f"isolation: {isolation}")
    if branch is not None:
        lines.append(f"branch: {branch}")
    if worktree is not None:
        lines.append(f"worktree: {worktree}")
    if touches_paths is not None:
        rendered = ", ".join(repr(p) for p in touches_paths)
        lines.append(f"touches_paths: [{rendered}]")
    lines += ["---", "", f"# {sprint_id} stub", ""]
    (sprints / f"{sprint_id}_stub.md").write_text("\n".join(lines), encoding="utf-8")


def _run(project_root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(project_root)],
        capture_output=True, text=True,
    )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "workspace" / "sprints").mkdir(parents=True)
    return tmp_path


def _sprints(project: Path) -> Path:
    return project / "workspace" / "sprints"


# --------------------------------------------------------------------------- #
# Baseline / backward compatibility
# --------------------------------------------------------------------------- #

def test_no_in_progress_plans_passes(project: Path) -> None:
    _write_plan(_sprints(project), "SP_001", status="Complete")
    r = _run(project)
    assert r.returncode == 0
    assert "no In Progress" in r.stdout


def test_solo_plan_without_isolation_field_passes(project: Path) -> None:
    """An omitted isolation field == shared-tree; a solo sprint has no peers."""
    _write_plan(_sprints(project), "SP_002", touches_paths=["src/a/"])
    r = _run(project)
    assert r.returncode == 0, r.stderr
    assert "PASS" in r.stdout


def test_two_disjoint_shared_tree_standard_pass_with_nudge(project: Path) -> None:
    """Disjoint paths are legitimate (Rule 6) — no FAIL, but a WI-3c advisory."""
    s = _sprints(project)
    _write_plan(s, "SP_003", touches_paths=["src/a/"])
    _write_plan(s, "SP_004", touches_paths=["src/b/"])
    r = _run(project)
    assert r.returncode == 0, r.stderr
    assert "WARN" in r.stdout  # nudge to isolate


# --------------------------------------------------------------------------- #
# WI-1 declaration validity
# --------------------------------------------------------------------------- #

def test_unknown_isolation_value_fails(project: Path) -> None:
    _write_plan(_sprints(project), "SP_010", isolation="sandbox")
    r = _run(project)
    assert r.returncode == 1
    assert "unknown isolation" in r.stderr


def test_git_worktree_without_worktree_path_fails(project: Path) -> None:
    _write_plan(_sprints(project), "SP_011", isolation="git-worktree",
                branch="sprint/SP_011-x")
    r = _run(project)
    assert r.returncode == 1
    assert "no `worktree`" in r.stderr


def test_git_worktree_without_branch_fails(project: Path) -> None:
    _write_plan(_sprints(project), "SP_012", isolation="git-worktree",
                worktree=".claude/worktrees/SP_012")
    r = _run(project)
    assert r.returncode == 1
    assert "no `branch`" in r.stderr


def test_branch_only_without_branch_fails(project: Path) -> None:
    _write_plan(_sprints(project), "SP_013", isolation="branch-only")
    r = _run(project)
    assert r.returncode == 1
    assert "no `branch`" in r.stderr


def test_branch_not_referencing_sprint_id_warns(project: Path) -> None:
    _write_plan(_sprints(project), "SP_014", isolation="branch-only",
                branch="feature/random-name")
    r = _run(project)
    assert r.returncode == 0, r.stderr
    assert "does not reference the sprint id" in r.stdout


def test_complete_git_worktree_declaration_passes(project: Path) -> None:
    _write_plan(_sprints(project), "SP_015", isolation="git-worktree",
                branch="sprint/SP_015-x", worktree=".claude/worktrees/SP_015")
    r = _run(project)
    assert r.returncode == 0, r.stderr


# --------------------------------------------------------------------------- #
# WI-2 uniqueness
# --------------------------------------------------------------------------- #

def test_duplicate_branch_fails(project: Path) -> None:
    s = _sprints(project)
    _write_plan(s, "SP_020", isolation="branch-only", branch="sprint/shared")
    _write_plan(s, "SP_021", isolation="branch-only", branch="sprint/shared")
    r = _run(project)
    assert r.returncode == 1
    assert "branch 'sprint/shared'" in r.stderr
    assert "SP_020" in r.stderr and "SP_021" in r.stderr


def test_duplicate_worktree_fails(project: Path) -> None:
    s = _sprints(project)
    _write_plan(s, "SP_022", isolation="git-worktree",
                branch="sprint/SP_022-x", worktree=".claude/worktrees/shared")
    _write_plan(s, "SP_023", isolation="git-worktree",
                branch="sprint/SP_023-x", worktree=".claude/worktrees/shared")
    r = _run(project)
    assert r.returncode == 1
    assert "worktree '.claude/worktrees/shared'" in r.stderr


# --------------------------------------------------------------------------- #
# WI-3 shared-tree collision (the C-6 resolution)
# --------------------------------------------------------------------------- #

def test_two_shared_tree_standard_overlapping_paths_fails(project: Path) -> None:
    s = _sprints(project)
    _write_plan(s, "SP_030", tier="Standard", touches_paths=["src/orchestrator/"])
    _write_plan(s, "SP_031", tier="Standard",
                touches_paths=["src/orchestrator/runtime.py"])
    r = _run(project)
    assert r.returncode == 1
    assert "share the main working tree" in r.stderr
    assert "SP_030" in r.stderr and "SP_031" in r.stderr


def test_two_shared_tree_micro_overlapping_paths_warns(project: Path) -> None:
    """Micro+Micro keeps the fast path: overlap is a WARN, not a FAIL."""
    s = _sprints(project)
    _write_plan(s, "SP_032", tier="Micro", touches_paths=["src/a/"])
    _write_plan(s, "SP_033", tier="Micro", touches_paths=["src/a/widget.py"])
    r = _run(project)
    assert r.returncode == 0, r.stderr
    assert "WARN" in r.stdout
    assert "both Micro" in r.stdout


def test_unspecified_tier_treated_as_strict(project: Path) -> None:
    """No tier == strict floor (matches the review-iteration fail-safe)."""
    s = _sprints(project)
    _write_plan(s, "SP_034", tier=None, touches_paths=["src/a/"])
    _write_plan(s, "SP_035", tier=None, touches_paths=["src/a/x.py"])
    r = _run(project)
    assert r.returncode == 1
    assert "share the main working tree" in r.stderr


def test_isolated_sprints_overlapping_paths_pass(project: Path) -> None:
    """Properly isolated parallel sprints pass even with overlapping paths —
    the validator refines Rule 6 rather than contradicting it."""
    s = _sprints(project)
    _write_plan(s, "SP_036", tier="Standard", isolation="git-worktree",
                branch="sprint/SP_036-x", worktree=".claude/worktrees/SP_036",
                touches_paths=["src/orchestrator/"])
    _write_plan(s, "SP_037", tier="Standard", isolation="git-worktree",
                branch="sprint/SP_037-x", worktree=".claude/worktrees/SP_037",
                touches_paths=["src/orchestrator/runtime.py"])
    r = _run(project)
    assert r.returncode == 0, r.stderr + r.stdout


def test_read_only_sprint_is_exempt(project: Path) -> None:
    """A read-only (analysis) sprint does not collide with a code sprint."""
    s = _sprints(project)
    _write_plan(s, "SP_038", tier="Standard", isolation="read-only",
                touches_paths=["src/orchestrator/"])
    _write_plan(s, "SP_039", tier="Standard",
                touches_paths=["src/orchestrator/runtime.py"])
    r = _run(project)
    # SP_039 is the only code sprint → no pairwise collision, no WI-3c nudge.
    assert r.returncode == 0, r.stderr
    assert "FAIL" not in r.stderr


def test_branch_only_overlapping_paths_pass(project: Path) -> None:
    """branch-only with distinct branches is isolated → overlap is fine."""
    s = _sprints(project)
    _write_plan(s, "SP_040", tier="Standard", isolation="branch-only",
                branch="sprint/SP_040-x", touches_paths=["src/a/"])
    _write_plan(s, "SP_041", tier="Standard", isolation="branch-only",
                branch="sprint/SP_041-x", touches_paths=["src/a/y.py"])
    r = _run(project)
    assert r.returncode == 0, r.stderr + r.stdout


def test_scalar_touches_paths_still_detects_overlap(project: Path) -> None:
    """C-1 regression: touches_paths written as a bare scalar (no list brackets)
    must not explode into a character-tuple and void the overlap check."""
    s = _sprints(project)
    # Bare scalar values, identical path → must still FAIL as an overlap.
    (s / "SP_060_a.md").write_text(
        "---\nsprint_id: SP_060\nstatus: In Progress\ntier: Standard\n"
        "touches_paths: src/orchestrator/\n---\n\nstub\n",
        encoding="utf-8",
    )
    (s / "SP_061_b.md").write_text(
        "---\nsprint_id: SP_061\nstatus: In Progress\ntier: Standard\n"
        "touches_paths: src/orchestrator/runtime.py\n---\n\nstub\n",
        encoding="utf-8",
    )
    r = _run(project)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "share the main working tree" in r.stderr


def test_empty_isolation_value_fails(project: Path) -> None:
    """H-1: a present-but-empty `isolation:` key must be flagged, not silently
    downgraded to shared-tree."""
    s = _sprints(project)
    (s / "SP_062_x.md").write_text(
        "---\nsprint_id: SP_062\nstatus: In Progress\ntier: Standard\n"
        "isolation:\n---\n\nstub\n",
        encoding="utf-8",
    )
    r = _run(project)
    assert r.returncode == 1
    assert "unknown isolation" in r.stderr and "(empty)" in r.stderr


def test_three_way_branch_collision_all_reported(project: Path) -> None:
    s = _sprints(project)
    for sid in ("SP_063", "SP_064", "SP_065"):
        _write_plan(s, sid, isolation="branch-only", branch="sprint/dup")
    r = _run(project)
    assert r.returncode == 1
    # Every colliding sprint must appear in the failure output.
    assert "SP_063" in r.stderr and "SP_064" in r.stderr and "SP_065" in r.stderr


def test_git_worktree_missing_both_fields_reports_both(project: Path) -> None:
    _write_plan(_sprints(project), "SP_066", isolation="git-worktree")
    r = _run(project)
    assert r.returncode == 1
    assert "no `worktree`" in r.stderr and "no `branch`" in r.stderr


def test_micro_tier_case_and_whitespace_normalized(project: Path) -> None:
    """`tier:  MICRO ` must relax just like `Micro` (overlap → WARN, not FAIL)."""
    s = _sprints(project)
    _write_plan(s, "SP_067", tier=" MICRO ", touches_paths=["src/a/"])
    _write_plan(s, "SP_068", tier="micro", touches_paths=["src/a/x.py"])
    r = _run(project)
    assert r.returncode == 0, r.stderr
    assert "both Micro" in r.stdout


def test_unrecognized_tier_warns(project: Path) -> None:
    _write_plan(_sprints(project), "SP_069", tier="Macro", touches_paths=["src/a/"])
    r = _run(project)
    assert r.returncode == 0, r.stderr
    assert "unrecognized tier" in r.stdout


def test_isolated_peer_does_not_trigger_advisory(project: Path) -> None:
    """H-4: a shared-tree sprint whose only peer is properly isolated must not
    get the WI-3c 'alongside other active sprints' advisory."""
    s = _sprints(project)
    _write_plan(s, "SP_070", tier="Standard", isolation="git-worktree",
                branch="sprint/SP_070-x", worktree=".claude/worktrees/SP_070",
                touches_paths=["src/a/"])
    _write_plan(s, "SP_071", tier="Standard", touches_paths=["src/b/"])
    r = _run(project)
    assert r.returncode == 0, r.stderr
    assert "alongside other active sprints" not in r.stdout


def test_precedent_clone_tier_is_strict(project: Path) -> None:
    """Precedent-Clone is a known tier but not relaxed → shared-tree overlap fails."""
    s = _sprints(project)
    _write_plan(s, "SP_072", tier="Precedent-Clone", touches_paths=["src/a/"])
    _write_plan(s, "SP_073", tier="Precedent-Clone", touches_paths=["src/a/x.py"])
    r = _run(project)
    assert r.returncode == 1
    assert "share the main working tree" in r.stderr
    assert "unrecognized tier" not in r.stdout  # it IS recognized


def test_malformed_plan_does_not_crash(project: Path) -> None:
    """A single bad-YAML archived plan is warn-skipped, not a crash."""
    s = _sprints(project)
    # Unclosed inline list → FrontmatterParseError, skipped with a warning.
    (s / "SP_050_bad.md").write_text(
        "---\nsprint_id: SP_050\nstatus: In Progress\n"
        "touches_paths: [src/a/\n---\n\nstub\n",
        encoding="utf-8",
    )
    _write_plan(s, "SP_051", touches_paths=["src/b/"])
    r = _run(project)
    assert r.returncode == 0, r.stderr
