"""
Tests for validate_rdd.py

Validator contract:
- Directories containing .py files must have a README.md (or equivalent doc file)
- ARCHITECTURE.md must exist and be non-empty at the project root (or configured location)
- CODEBASE_STRUCTURE.md must exist and be non-empty
- Sprint plan must exist for the active sprint declared in PROGRESS.md
- src_dir is configurable via .validators.yml (key: src_dir)
- Returns 0 on pass, 1 on failure
- Missing git is not a hard failure (git-based checks are advisory)
"""
import subprocess
import sys
from pathlib import Path

import pytest

VALIDATOR = Path(__file__).parent / "validate_rdd.py"


def run_validator(project_root: Path, *extra_args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(project_root), *extra_args],
        capture_output=True,
        text=True,
    )


def write_config(project_root: Path, src_dir: str) -> None:
    """Write a minimal .validators.yml with only the src_dir key."""
    config_path = project_root / ".validators.yml"
    config_path.write_text(f"src_dir: {src_dir}\n")


def make_minimal_sprint_plan(sprints_dir: Path, sprint_id: str) -> None:
    """Write a minimal valid sprint plan for the given sprint ID."""
    plan = sprints_dir / f"{sprint_id}.md"
    plan.write_text(
        f"# Sprint Plan: {sprint_id}\n\n"
        "## Sprint Goal\nBuild something.\n\n"
        "## Scope\nFeatures.\n\n"
        "## Technical Approach\nDescription.\n\n"
        "## Testing Strategy\nAll paths tested.\n\n"
        "## Success Criteria\n- [ ] All tests passing\n"
    )


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


def test_passes_with_complete_docs(tmp_path: Path) -> None:
    """All required docs present, src has README.md, active sprint plan exists."""
    # Required root docs
    (tmp_path / "ARCHITECTURE.md").write_text("# Architecture\nDetails here.\n")
    (tmp_path / "CODEBASE_STRUCTURE.md").write_text("# Codebase\nDetails here.\n")

    # Source directory with a README
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text("pass\n")
    (src / "README.md").write_text("# Source\nDescription.\n")

    # PROGRESS.md with active sprint
    sprints_dir = tmp_path / "00_IMPLEMENTATION" / "SPRINTS"
    sprints_dir.mkdir(parents=True)
    make_minimal_sprint_plan(sprints_dir, "SP_001_Foundation")
    (tmp_path / "PROGRESS.md").write_text(
        "## Active Sprint\n**Current:** SP_001_Foundation\n"
    )

    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stderr


def test_passes_with_config_src_dir(tmp_path: Path) -> None:
    """Custom src_dir from .validators.yml is used instead of default 'src'."""
    write_config(tmp_path, "app")

    (tmp_path / "ARCHITECTURE.md").write_text("# Architecture\nContent.\n")
    (tmp_path / "CODEBASE_STRUCTURE.md").write_text("# Structure\nContent.\n")

    custom_src = tmp_path / "app"
    custom_src.mkdir()
    (custom_src / "core.py").write_text("pass\n")
    (custom_src / "README.md").write_text("# App\nDoc.\n")

    (tmp_path / "PROGRESS.md").write_text("## Active Sprint\n**Current:** SP_002_Core\n")
    sprints_dir = tmp_path / "00_IMPLEMENTATION" / "SPRINTS"
    sprints_dir.mkdir(parents=True)
    make_minimal_sprint_plan(sprints_dir, "SP_002_Core")

    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stderr


def test_passes_when_no_active_sprint_in_progress_md(tmp_path: Path) -> None:
    """When PROGRESS.md has no active sprint, sprint-plan check is skipped (advisory)."""
    (tmp_path / "ARCHITECTURE.md").write_text("# Architecture\nContent.\n")
    (tmp_path / "CODEBASE_STRUCTURE.md").write_text("# Structure\nContent.\n")

    src = tmp_path / "src"
    src.mkdir()
    (src / "README.md").write_text("# Src\nDoc.\n")

    # PROGRESS.md exists but has no active sprint section
    (tmp_path / "PROGRESS.md").write_text("## Sprint History\nAll done.\n")

    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# Failure-path tests
# ---------------------------------------------------------------------------


def test_fails_missing_architecture_md(tmp_path: Path) -> None:
    """Missing ARCHITECTURE.md causes a validation failure."""
    # ARCHITECTURE.md deliberately not created
    (tmp_path / "CODEBASE_STRUCTURE.md").write_text("# Structure\nContent.\n")

    src = tmp_path / "src"
    src.mkdir()
    (src / "README.md").write_text("# Src\nDoc.\n")

    (tmp_path / "PROGRESS.md").write_text("## Sprint History\nDone.\n")

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


def test_fails_empty_architecture_md(tmp_path: Path) -> None:
    """An empty ARCHITECTURE.md is treated as missing and causes failure."""
    (tmp_path / "ARCHITECTURE.md").write_text("")  # empty
    (tmp_path / "CODEBASE_STRUCTURE.md").write_text("# Structure\nContent.\n")

    src = tmp_path / "src"
    src.mkdir()
    (src / "README.md").write_text("# Src\nDoc.\n")
    (tmp_path / "PROGRESS.md").write_text("## Sprint History\nDone.\n")

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


def test_fails_missing_codebase_structure(tmp_path: Path) -> None:
    """Missing CODEBASE_STRUCTURE.md causes a validation failure."""
    (tmp_path / "ARCHITECTURE.md").write_text("# Architecture\nContent.\n")
    # CODEBASE_STRUCTURE.md deliberately not created

    src = tmp_path / "src"
    src.mkdir()
    (src / "README.md").write_text("# Src\nDoc.\n")
    (tmp_path / "PROGRESS.md").write_text("## Sprint History\nDone.\n")

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


def test_fails_empty_codebase_structure(tmp_path: Path) -> None:
    """An empty CODEBASE_STRUCTURE.md is treated as missing."""
    (tmp_path / "ARCHITECTURE.md").write_text("# Architecture\nContent.\n")
    (tmp_path / "CODEBASE_STRUCTURE.md").write_text("")  # empty

    src = tmp_path / "src"
    src.mkdir()
    (src / "README.md").write_text("# Src\nDoc.\n")
    (tmp_path / "PROGRESS.md").write_text("## Sprint History\nDone.\n")

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


def test_fails_when_src_dir_has_py_files_but_no_readme(tmp_path: Path) -> None:
    """A directory with .py files but no README.md causes failure."""
    (tmp_path / "ARCHITECTURE.md").write_text("# Architecture\nContent.\n")
    (tmp_path / "CODEBASE_STRUCTURE.md").write_text("# Structure\nContent.\n")

    src = tmp_path / "src"
    src.mkdir()
    (src / "service.py").write_text("pass\n")
    # No README.md in src/

    (tmp_path / "PROGRESS.md").write_text("## Sprint History\nDone.\n")

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


def test_fails_when_active_sprint_plan_missing(tmp_path: Path) -> None:
    """When PROGRESS.md declares an active sprint but the plan file is absent, fail."""
    (tmp_path / "ARCHITECTURE.md").write_text("# Architecture\nContent.\n")
    (tmp_path / "CODEBASE_STRUCTURE.md").write_text("# Structure\nContent.\n")

    src = tmp_path / "src"
    src.mkdir()
    (src / "README.md").write_text("# Src\nDoc.\n")

    (tmp_path / "PROGRESS.md").write_text(
        "## Active Sprint\n**Current:** SP_003_Missing\n"
    )
    # Sprint plan file deliberately not created

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


# ---------------------------------------------------------------------------
# Advisory / git-unavailable tests
# ---------------------------------------------------------------------------


def test_warns_when_git_unavailable(tmp_path: Path) -> None:
    """When git is not available, git-based checks degrade to warnings, not failures."""
    (tmp_path / "ARCHITECTURE.md").write_text("# Architecture\nContent.\n")
    (tmp_path / "CODEBASE_STRUCTURE.md").write_text("# Structure\nContent.\n")

    src = tmp_path / "src"
    src.mkdir()
    (src / "README.md").write_text("# Src\nDoc.\n")
    (tmp_path / "PROGRESS.md").write_text("## Sprint History\nDone.\n")

    # Inject a PATH with no git binary so subprocess cannot find it
    import os
    env = {**os.environ, "PATH": "/nonexistent_dir"}
    result = subprocess.run(
        [sys.executable, str(VALIDATOR), str(tmp_path)],
        capture_output=True,
        text=True,
        env=env,
    )
    # Should still exit 0 — git checks are advisory
    assert result.returncode == 0, result.stderr


def test_passes_when_src_dir_is_empty(tmp_path: Path) -> None:
    """An src directory with no .py files does not require a README.md."""
    (tmp_path / "ARCHITECTURE.md").write_text("# Architecture\nContent.\n")
    (tmp_path / "CODEBASE_STRUCTURE.md").write_text("# Structure\nContent.\n")

    src = tmp_path / "src"
    src.mkdir()
    # No .py files — only a markdown file
    (src / "notes.md").write_text("Just notes.\n")

    (tmp_path / "PROGRESS.md").write_text("## Sprint History\nDone.\n")

    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stderr
