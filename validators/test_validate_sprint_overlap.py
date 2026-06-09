"""
SP_205 — tests for validate_sprint_overlap.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

VALIDATOR = Path(__file__).parent / "validate_sprint_overlap.py"


def _write_plan(sprints: Path, sprint_id: str, status: str,
                touches_paths: list[str] | None = None,
                touches_checklist_items: list[str] | None = None) -> None:
    paths_line = (
        f"touches_paths: [{', '.join(repr(p) for p in touches_paths)}]\n"
        if touches_paths is not None else ""
    )
    items_line = (
        f"touches_checklist_items: [{', '.join(repr(p) for p in touches_checklist_items)}]\n"
        if touches_checklist_items is not None else ""
    )
    body = (
        "---\n"
        f"sprint_id: {sprint_id}\n"
        "tier: Standard\n"
        f"status: {status}\n"
        f"{paths_line}"
        f"{items_line}"
        "---\n\n"
        f"# {sprint_id} stub\n"
    )
    (sprints / f"{sprint_id}_stub.md").write_text(body, encoding="utf-8")


def _run(project_root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(project_root)],
        capture_output=True, text=True,
    )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "workspace" / "sprints").mkdir(parents=True)
    return tmp_path


def test_no_in_progress_plans_passes(project: Path) -> None:
    _write_plan(project / "workspace" / "sprints", "SP_001", "Complete",
                touches_paths=["src/x/"])
    r = _run(project)
    assert r.returncode == 0
    assert "no In Progress sprint plans" in r.stdout


def test_checklist_item_overlap_fails(project: Path) -> None:
    sprints = project / "workspace" / "sprints"
    _write_plan(sprints, "SP_010", "In Progress",
                touches_checklist_items=["§17.4"])
    _write_plan(sprints, "SP_011", "In Progress",
                touches_checklist_items=["§17.4", "§9.6"])
    r = _run(project)
    assert r.returncode == 1
    assert "SP_010" in r.stderr and "SP_011" in r.stderr
    assert "§17.4" in r.stderr


def test_path_prefix_overlap_warns_does_not_fail(project: Path) -> None:
    sprints = project / "workspace" / "sprints"
    _write_plan(sprints, "SP_020", "In Progress",
                touches_paths=["src/orchestrator/"])
    _write_plan(sprints, "SP_021", "In Progress",
                touches_paths=["src/orchestrator/runtime.ts"])
    r = _run(project)
    assert r.returncode == 0  # warn-only, not fail
    assert "WARN" in r.stdout


def test_overlap_ignore_paths_excluded(project: Path) -> None:
    sprints = project / "workspace" / "sprints"
    # PROGRESS.md is in OVERLAP_IGNORE_PATHS; two sprints touching it must NOT warn.
    _write_plan(sprints, "SP_030", "In Progress",
                touches_paths=["PROGRESS.md", "src/a/"])
    _write_plan(sprints, "SP_031", "In Progress",
                touches_paths=["PROGRESS.md", "src/b/"])
    r = _run(project)
    assert r.returncode == 0
    assert "WARN" not in r.stdout


def test_disjoint_plans_pass_clean(project: Path) -> None:
    sprints = project / "workspace" / "sprints"
    _write_plan(sprints, "SP_040", "In Progress",
                touches_paths=["src/dashboard/"],
                touches_checklist_items=["§42.1"])
    _write_plan(sprints, "SP_041", "In Progress",
                touches_paths=["src/orchestrator/"],
                touches_checklist_items=["§17.4"])
    r = _run(project)
    assert r.returncode == 0
    assert "PASS" in r.stdout


def test_block_list_yaml_parsed_for_overlap_check(project: Path) -> None:
    """Stage-5 H-2 — block-list YAML must be parsed; previously silently dropped."""
    sprints = project / "workspace" / "sprints"
    block_a = (
        "---\n"
        "sprint_id: SP_050\n"
        "status: In Progress\n"
        "touches_checklist_items:\n"
        "  - §17.4\n"
        "  - §9.6\n"
        "---\n\nstub\n"
    )
    block_b = (
        "---\n"
        "sprint_id: SP_051\n"
        "status: In Progress\n"
        "touches_checklist_items:\n"
        "  - §17.4\n"
        "---\n\nstub\n"
    )
    (sprints / "SP_050_block.md").write_text(block_a, encoding="utf-8")
    (sprints / "SP_051_block.md").write_text(block_b, encoding="utf-8")
    r = _run(project)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "§17.4" in r.stderr


def test_single_in_progress_plan_passes(project: Path) -> None:
    """No pairwise comparison possible → trivial PASS."""
    sprints = project / "workspace" / "sprints"
    _write_plan(sprints, "SP_060", "In Progress",
                touches_paths=["src/x/"],
                touches_checklist_items=["§1.1"])
    r = _run(project)
    assert r.returncode == 0
    assert "PASS" in r.stdout


def test_filename_fallback_when_sprint_id_missing(project: Path) -> None:
    """Stage-5 M-1 — fallback uses first TWO underscore-segments (SP_NNN)."""
    sprints = project / "workspace" / "sprints"
    # Two plans without sprint_id frontmatter; filename-derived ids.
    a = (
        "---\nstatus: In Progress\n"
        "touches_checklist_items: ['§99.1']\n---\nstub\n"
    )
    b = (
        "---\nstatus: In Progress\n"
        "touches_checklist_items: ['§99.1']\n---\nstub\n"
    )
    (sprints / "SP_070_a.md").write_text(a, encoding="utf-8")
    (sprints / "SP_071_b.md").write_text(b, encoding="utf-8")
    r = _run(project)
    assert r.returncode == 1
    # Fallback must produce SP_070 / SP_071 (not just "SP").
    assert "SP_070" in r.stderr and "SP_071" in r.stderr
