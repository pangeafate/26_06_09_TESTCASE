"""
Tests for validate_structure.py

Validator contract:
- Required directories must exist (defaults: test/unit, test/integration)
- Required files must exist (defaults: PROJECT_CONTEXT.md, ARCHITECTURE.md,
  CODEBASE_STRUCTURE.md, PROGRESS.md, PROJECT_ROADMAP.md)
- Required directories and files are configurable via .validators.yml
- Layer boundary compliance is optional; defined under layer_rules in .validators.yml
- Returns 0 on pass, 1 on failure
"""
import subprocess
import sys
from pathlib import Path

import pytest

VALIDATOR = Path(__file__).parent / "validate_structure.py"


def run_validator(project_root: Path, *extra_args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(project_root), *extra_args],
        capture_output=True,
        text=True,
    )


def write_config(project_root: Path, config: dict) -> None:
    """Write .validators.yml as hand-crafted YAML from a simple dict structure.

    Supports str lists under required_dirs, required_files, and a nested
    layer_rules section with forbidden_imports lists. Avoids PyYAML dependency.
    """
    lines = []
    for key, value in config.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
        elif isinstance(value, dict):
            lines.append(f"{key}:")
            for sub_key, sub_value in value.items():
                lines.append(f"  {sub_key}:")
                if isinstance(sub_value, dict):
                    for inner_key, inner_value in sub_value.items():
                        if isinstance(inner_value, list):
                            lines.append(f"    {inner_key}:")
                            for item in inner_value:
                                lines.append(f"      - {item}")
                        else:
                            lines.append(f"    {inner_key}: {inner_value}")
                else:
                    lines.append(f"    {sub_value}")
        else:
            lines.append(f"{key}: {value}")
    (project_root / ".validators.yml").write_text("\n".join(lines) + "\n")


def make_complete_structure(root: Path) -> None:
    """Create a fully valid project structure with defaults."""
    # Required directories
    (root / "test" / "unit").mkdir(parents=True)
    (root / "test" / "integration").mkdir(parents=True)

    # Required files
    (root / "PROJECT_CONTEXT.md").write_text("# Context\nContent.\n")
    (root / "ARCHITECTURE.md").write_text("# Architecture\nContent.\n")
    (root / "CODEBASE_STRUCTURE.md").write_text("# Structure\nContent.\n")
    (root / "PROGRESS.md").write_text("# Progress\nContent.\n")
    (root / "PROJECT_ROADMAP.md").write_text("# Roadmap\nContent.\n")


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


def test_passes_with_complete_structure(tmp_path: Path) -> None:
    """All required directories and files present — validator exits 0."""
    make_complete_structure(tmp_path)
    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stderr


def test_uses_validators_yml_required_dirs(tmp_path: Path) -> None:
    """Custom required_dirs list from .validators.yml overrides defaults."""
    write_config(tmp_path, {"required_dirs": ["custom/tests", "custom/fixtures"]})

    # Create the custom dirs but NOT the default ones
    (tmp_path / "custom" / "tests").mkdir(parents=True)
    (tmp_path / "custom" / "fixtures").mkdir(parents=True)

    # Still need at least the default required files unless also overridden
    write_config(
        tmp_path,
        {
            "required_dirs": ["custom/tests", "custom/fixtures"],
            "required_files": ["ARCHITECTURE.md"],
        },
    )
    (tmp_path / "ARCHITECTURE.md").write_text("# Architecture\nContent.\n")

    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stderr


def test_uses_validators_yml_required_files(tmp_path: Path) -> None:
    """Custom required_files list from .validators.yml overrides defaults."""
    write_config(
        tmp_path,
        {
            "required_dirs": ["test/unit"],
            "required_files": ["MY_CUSTOM_DOC.md"],
        },
    )
    (tmp_path / "test" / "unit").mkdir(parents=True)
    (tmp_path / "MY_CUSTOM_DOC.md").write_text("# Custom\nContent.\n")

    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stderr


def test_extra_files_and_dirs_are_allowed(tmp_path: Path) -> None:
    """Having more dirs/files than required is not a failure."""
    make_complete_structure(tmp_path)
    # Add extras that are not in the required list
    (tmp_path / "test" / "e2e").mkdir(parents=True)
    (tmp_path / "EXTRA_DOC.md").write_text("Extra.\n")

    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# Failure-path tests
# ---------------------------------------------------------------------------


def test_fails_missing_test_unit_dir(tmp_path: Path) -> None:
    """Missing test/unit directory causes failure."""
    # Create integration but not unit
    (tmp_path / "test" / "integration").mkdir(parents=True)

    (tmp_path / "PROJECT_CONTEXT.md").write_text("# Context\n")
    (tmp_path / "ARCHITECTURE.md").write_text("# Architecture\n")
    (tmp_path / "CODEBASE_STRUCTURE.md").write_text("# Structure\n")
    (tmp_path / "PROGRESS.md").write_text("# Progress\n")
    (tmp_path / "PROJECT_ROADMAP.md").write_text("# Roadmap\n")

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


def test_fails_missing_test_integration_dir(tmp_path: Path) -> None:
    """Missing test/integration directory causes failure."""
    (tmp_path / "test" / "unit").mkdir(parents=True)
    # integration dir not created

    (tmp_path / "PROJECT_CONTEXT.md").write_text("# Context\n")
    (tmp_path / "ARCHITECTURE.md").write_text("# Architecture\n")
    (tmp_path / "CODEBASE_STRUCTURE.md").write_text("# Structure\n")
    (tmp_path / "PROGRESS.md").write_text("# Progress\n")
    (tmp_path / "PROJECT_ROADMAP.md").write_text("# Roadmap\n")

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


def test_fails_missing_both_test_dirs(tmp_path: Path) -> None:
    """Missing both test directories causes failure."""
    (tmp_path / "PROJECT_CONTEXT.md").write_text("# Context\n")
    (tmp_path / "ARCHITECTURE.md").write_text("# Architecture\n")
    (tmp_path / "CODEBASE_STRUCTURE.md").write_text("# Structure\n")
    (tmp_path / "PROGRESS.md").write_text("# Progress\n")
    (tmp_path / "PROJECT_ROADMAP.md").write_text("# Roadmap\n")

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


def test_fails_missing_required_file_project_context(tmp_path: Path) -> None:
    """Missing PROJECT_CONTEXT.md causes failure."""
    (tmp_path / "test" / "unit").mkdir(parents=True)
    (tmp_path / "test" / "integration").mkdir(parents=True)

    # PROJECT_CONTEXT.md deliberately absent
    (tmp_path / "ARCHITECTURE.md").write_text("# Architecture\n")
    (tmp_path / "CODEBASE_STRUCTURE.md").write_text("# Structure\n")
    (tmp_path / "PROGRESS.md").write_text("# Progress\n")
    (tmp_path / "PROJECT_ROADMAP.md").write_text("# Roadmap\n")

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


def test_fails_missing_required_file_progress_md(tmp_path: Path) -> None:
    """Missing PROGRESS.md causes failure."""
    (tmp_path / "test" / "unit").mkdir(parents=True)
    (tmp_path / "test" / "integration").mkdir(parents=True)

    (tmp_path / "PROJECT_CONTEXT.md").write_text("# Context\n")
    (tmp_path / "ARCHITECTURE.md").write_text("# Architecture\n")
    (tmp_path / "CODEBASE_STRUCTURE.md").write_text("# Structure\n")
    (tmp_path / "PROJECT_ROADMAP.md").write_text("# Roadmap\n")
    # PROGRESS.md deliberately absent

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


def test_fails_missing_custom_required_file(tmp_path: Path) -> None:
    """A custom required_files entry that is absent causes failure."""
    write_config(
        tmp_path,
        {
            "required_dirs": ["test/unit"],
            "required_files": ["IMPORTANT_DOC.md"],
        },
    )
    (tmp_path / "test" / "unit").mkdir(parents=True)
    # IMPORTANT_DOC.md deliberately absent

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


def test_fails_missing_custom_required_dir(tmp_path: Path) -> None:
    """A custom required_dirs entry that is absent causes failure."""
    write_config(
        tmp_path,
        {
            "required_dirs": ["test/unit", "docs/api"],
            "required_files": [],
        },
    )
    (tmp_path / "test" / "unit").mkdir(parents=True)
    # docs/api deliberately absent

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


# ---------------------------------------------------------------------------
# Malformed config handling
# ---------------------------------------------------------------------------


def test_malformed_yaml_falls_back_to_defaults(tmp_path: Path) -> None:
    """A malformed .validators.yml degrades to defaults, not a crash."""
    make_complete_structure(tmp_path)
    # Write invalid YAML
    (tmp_path / ".validators.yml").write_text("key: [unclosed\n  bad: yaml: here\n")

    result = run_validator(tmp_path)
    # Should pass using defaults (complete structure is present)
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# Layer-boundary compliance (optional feature)
# ---------------------------------------------------------------------------


def test_layer_rules_not_violated_exits_zero(tmp_path: Path) -> None:
    """When layer_rules are configured and no violations exist, exits 0."""
    make_complete_structure(tmp_path)

    src = tmp_path / "src" / "lib"
    src.mkdir(parents=True)
    # A lib module that does NOT import from capabilities — no violation
    (src / "service.py").write_text("# clean service\nresult = 1 + 1\n")

    write_config(
        tmp_path,
        {
            "required_dirs": ["test/unit", "test/integration"],
            "required_files": [
                "PROJECT_CONTEXT.md",
                "ARCHITECTURE.md",
                "CODEBASE_STRUCTURE.md",
                "PROGRESS.md",
                "PROJECT_ROADMAP.md",
            ],
            "layer_rules": {
                "src/lib": {"forbidden_imports": ["src/capabilities"]},
            },
        },
    )

    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stderr


def test_layer_rules_violation_exits_one(tmp_path: Path) -> None:
    """When a lib module imports from capabilities, layer rule is violated."""
    make_complete_structure(tmp_path)

    caps = tmp_path / "src" / "capabilities"
    caps.mkdir(parents=True)
    (caps / "entry.py").write_text("ENTRY = True\n")

    lib = tmp_path / "src" / "lib"
    lib.mkdir(parents=True)
    # This lib file imports from capabilities — a layer violation
    (lib / "broken_service.py").write_text(
        "from src.capabilities.entry import ENTRY\nresult = ENTRY\n"
    )

    write_config(
        tmp_path,
        {
            "required_dirs": ["test/unit", "test/integration"],
            "required_files": [
                "PROJECT_CONTEXT.md",
                "ARCHITECTURE.md",
                "CODEBASE_STRUCTURE.md",
                "PROGRESS.md",
                "PROJECT_ROADMAP.md",
            ],
            "layer_rules": {
                "src/lib": {"forbidden_imports": ["src/capabilities"]},
            },
        },
    )

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout
