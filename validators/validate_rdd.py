#!/usr/bin/env python3
"""Validate RDD (README-Driven Development) compliance.

Checks:
1. ARCHITECTURE.md exists and is non-empty at project root.
2. CODEBASE_STRUCTURE.md exists and is non-empty at project root.
3. Every directory under src_dir that contains .py files has a README.md.
4. If PROGRESS.md declares an active sprint (``**Current:** SP_XXX``), the
   corresponding sprint plan file exists under 00_IMPLEMENTATION/SPRINTS/
   (or workspace/sprints/ as a fallback).
5. Git-based documentation freshness check (advisory only — skipped when
   git is unavailable).

Usage:
    python validate_rdd.py <project_root> [--src-dir SRC]

Configuration:
    .validators.yml at project_root may set ``src_dir`` (key).  CLI flags
    override config values; config overrides built-in defaults.

Exit codes:
    0 — all checks pass
    1 — one or more checks failed
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _load_config(project_root: Path) -> dict:
    """Load .validators.yml from project_root. Return empty dict if absent."""
    config_path = project_root / ".validators.yml"
    if not config_path.exists():
        return {}
    if yaml is None:
        return {}
    try:
        with config_path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, yaml.YAMLError):
        return {}


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_required_doc(project_root: Path, filename: str) -> str | None:
    """Return a failure message if *filename* is missing or empty, else None."""
    path = project_root / filename
    if not path.exists():
        return f"FAIL: {filename} is missing at project root"
    if not path.read_text(encoding="utf-8").strip():
        return f"FAIL: {filename} exists but is empty"
    return None


def _dirs_with_py_files(src_dir: Path) -> list[Path]:
    """Return all directories under src_dir (inclusive) that contain .py files."""
    if not src_dir.exists():
        return []
    dirs: set[Path] = set()
    for py_file in src_dir.rglob("*.py"):
        if py_file.is_file():
            dirs.add(py_file.parent)
    return sorted(dirs)


def _check_readme_coverage(src_dir: Path) -> list[str]:
    """Return failure messages for directories missing README.md."""
    failures: list[str] = []
    for directory in _dirs_with_py_files(src_dir):
        if not (directory / "README.md").exists():
            failures.append(
                f"FAIL: {directory} contains .py files but has no README.md"
            )
    return failures


def _parse_active_sprint(project_root: Path) -> str | None:
    """Extract the active sprint ID from PROGRESS.md.

    Looks for the pattern ``**Current:** SP_XXX`` (case-insensitive prefix).
    Returns the sprint identifier (e.g. ``SP_001_Foundation``) or None.
    """
    progress_path = project_root / "PROGRESS.md"
    if not progress_path.exists():
        return None
    content = progress_path.read_text(encoding="utf-8")
    match = re.search(r"\*\*Current:\*\*\s+(SP_\S+)", content)
    return match.group(1) if match else None


def _find_sprint_plan(project_root: Path, sprint_id: str) -> Path | None:
    """Locate a sprint plan file for sprint_id in known sprint directories.

    Supports exact match (SP_042.md) and slug match (SP_042_Goal_Name.md).
    """
    search_dirs = [
        project_root / "00_IMPLEMENTATION" / "SPRINTS",
        project_root / "workspace" / "sprints",
    ]
    for sprints_dir in search_dirs:
        if not sprints_dir.exists():
            continue
        exact = sprints_dir / f"{sprint_id}.md"
        if exact.exists():
            return exact
        matches = list(sprints_dir.glob(f"{sprint_id}_*.md"))
        if matches:
            return matches[0]
        subfolder = sprints_dir / sprint_id
        if subfolder.is_dir():
            exact_sub = subfolder / f"{sprint_id}.md"
            if exact_sub.exists():
                return exact_sub
            sub_matches = list(subfolder.glob(f"{sprint_id}_*.md"))
            if sub_matches:
                return sub_matches[0]
    return None


def _check_sprint_plan(project_root: Path) -> str | None:
    """Return a failure message if the active sprint plan file is missing.

    Returns None if:
    - No active sprint is declared (advisory — skip).
    - The sprint plan file exists.
    """
    sprint_id = _parse_active_sprint(project_root)
    if sprint_id is None:
        return None  # advisory: no active sprint declared
    plan = _find_sprint_plan(project_root, sprint_id)
    if plan is None:
        return (
            f"FAIL: Active sprint {sprint_id!r} declared in PROGRESS.md "
            "but no plan file found in 00_IMPLEMENTATION/SPRINTS/ "
            "or workspace/sprints/"
        )
    return None


# ---------------------------------------------------------------------------
# Advisory git check
# ---------------------------------------------------------------------------

def _check_git_freshness(project_root: Path) -> list[str]:
    """Advisory check: git-based doc freshness.  Returns warnings only.

    Silently skipped when git is unavailable or the directory is not a repo.
    """
    warnings: list[str] = []
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return []
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    # Placeholder: add real freshness logic here when needed.
    return warnings


# ---------------------------------------------------------------------------
# Main validation entry-point
# ---------------------------------------------------------------------------

def validate(
    project_root: Path,
    src_dir_name: str = "src",
) -> tuple[int, list[str]]:
    """Run all RDD checks.  Returns (exit_code, messages)."""
    messages: list[str] = []
    failures: list[str] = []

    # --- Required root documents ---
    for doc in ("ARCHITECTURE.md", "CODEBASE_STRUCTURE.md"):
        failure = _check_required_doc(project_root, doc)
        if failure:
            failures.append(failure)
        else:
            messages.append(f"OK: {doc} present and non-empty")

    # --- README coverage ---
    src_dir = project_root / src_dir_name
    readme_failures = _check_readme_coverage(src_dir)
    if readme_failures:
        failures.extend(readme_failures)
    else:
        messages.append(f"OK: all Python directories in {src_dir_name}/ have README.md")

    # --- Sprint plan ---
    sprint_failure = _check_sprint_plan(project_root)
    if sprint_failure:
        failures.append(sprint_failure)
    else:
        sprint_id = _parse_active_sprint(project_root)
        if sprint_id:
            messages.append(f"OK: sprint plan for {sprint_id} exists")
        else:
            messages.append("OK: no active sprint declared — sprint plan check skipped")

    # --- Advisory git check ---
    for warning in _check_git_freshness(project_root):
        messages.append(f"WARNING: {warning}")

    if failures:
        return 1, failures + messages
    return 0, messages


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Validate RDD compliance")
    parser.add_argument("project_root", type=Path, help="Project root directory")
    parser.add_argument(
        "--src-dir",
        default=None,
        help="Source directory to check for README coverage (default: src)",
    )
    args = parser.parse_args()

    project_root: Path = args.project_root.resolve()

    # Resolve src_dir: CLI > config > default
    config = _load_config(project_root)
    if args.src_dir is not None:
        src_dir_name: str = args.src_dir
    elif "src_dir" in config:
        src_dir_name = str(config["src_dir"])
    else:
        src_dir_name = "src"

    exit_code, messages = validate(project_root, src_dir_name)

    for msg in messages:
        print(msg)

    if exit_code == 0:
        print("\nRDD validation passed.")
    else:
        print("\nRDD validation FAILED.", file=sys.stderr)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
