"""
Tests for validate_declared_deps.py (DEV_REINFORCE F-2).

Contract:
  * an active (In Progress) plan that owns code but declares no `dependencies`
    frontmatter → ADVISORY (exit 0) by default, FAIL (exit 1) under --strict
  * a plan declaring `dependencies: []` (or any value) → satisfied
  * a docs-only plan (no code in touches_paths) → exempt
  * a non-active plan (Complete/Planning) → not checked
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

VALIDATOR = Path(__file__).parent / "validate_declared_deps.py"


def _write_plan(
    sprints: Path,
    sprint_id: str,
    *,
    status: str = "In Progress",
    touches_paths: list[str] | None = None,
    deps_line: str | None = None,
) -> None:
    lines = ["---", f"sprint_id: {sprint_id}", f"status: {status}"]
    if touches_paths is not None:
        rendered = ", ".join(repr(p) for p in touches_paths)
        lines.append(f"touches_paths: [{rendered}]")
    if deps_line is not None:
        lines.append(deps_line)
    lines += ["---", "", f"# {sprint_id} stub", ""]
    (sprints / f"{sprint_id}_stub.md").write_text("\n".join(lines), encoding="utf-8")


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "workspace" / "sprints").mkdir(parents=True)
    return tmp_path


def _sprints(p: Path) -> Path:
    return p / "workspace" / "sprints"


def _run(project: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(project), *extra],
        capture_output=True, text=True,
    )


def test_code_plan_without_deps_is_advisory_by_default(project: Path) -> None:
    _write_plan(_sprints(project), "SP_010", touches_paths=["helixpay/ingest/**"])
    r = _run(project)
    assert r.returncode == 0, r.stderr          # advisory must not block
    assert "ADVISORY" in r.stdout
    assert "SP_010" in r.stdout


def test_code_plan_without_deps_fails_under_strict(project: Path) -> None:
    _write_plan(_sprints(project), "SP_011", touches_paths=["helixpay/x.py"])
    r = _run(project, "--strict")
    assert r.returncode == 1
    assert "FAIL" in r.stderr
    assert "SP_011" in r.stderr


def test_empty_deps_list_satisfies(project: Path) -> None:
    _write_plan(
        _sprints(project), "SP_012",
        touches_paths=["helixpay/x.py"], deps_line="dependencies: []",
    )
    r = _run(project, "--strict")
    assert r.returncode == 0, r.stderr
    assert "PASS" in r.stdout


def test_declared_deps_satisfies(project: Path) -> None:
    _write_plan(
        _sprints(project), "SP_013",
        touches_paths=["helixpay/x.py"],
        deps_line="dependencies: [anthropic>=0.40, voyageai>=0.3]",
    )
    r = _run(project, "--strict")
    assert r.returncode == 0, r.stderr


def test_docs_only_plan_is_exempt(project: Path) -> None:
    _write_plan(_sprints(project), "SP_014", touches_paths=["README.md", "docs.md"])
    r = _run(project, "--strict")
    assert r.returncode == 0, r.stderr
    assert "PASS" in r.stdout


def test_non_active_plan_not_checked(project: Path) -> None:
    _write_plan(
        _sprints(project), "SP_015",
        status="Complete", touches_paths=["helixpay/x.py"],
    )
    r = _run(project, "--strict")
    assert r.returncode == 0, r.stderr
