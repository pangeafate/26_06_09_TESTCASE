"""
Tests for validate_tdd.py

Validator contract:
- For every .py file in src_dir, a corresponding test_*.py must exist in test_dir
- Test files must contain at least one test function (def test_)
- Git-based test-first ordering is advisory (warning), not hard-fail
- Configurable via --src-dir and --test-dir flags
- Returns 0 on pass, 1 on failure
- __init__.py files are exempt from the test coverage requirement
- Nested src paths map to test_dir/<subpath>/test_<name>.py OR test_dir/test_<name>.py
- Coverage gate (M-2): when a Cobertura coverage report is present, line/branch
  coverage below the threshold (default 80%/75%) fails the build; a missing
  report is advisory unless --require-coverage-report / coverage.require_report.
  Thresholds configurable via .validators.yml and CLI overrides.
"""
import subprocess
import sys
from pathlib import Path

import pytest

VALIDATOR = Path(__file__).parent / "validate_tdd.py"


def run_validator(project_root: Path, *extra_args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(project_root), *extra_args],
        capture_output=True,
        text=True,
    )


def make_src_with_test(project_root: Path) -> None:
    """Create a minimal src/ + test/ layout that passes the file-pairing checks."""
    src = project_root / "src"
    src.mkdir(exist_ok=True)
    (src / "foo.py").write_text("def add(a, b):\n    return a + b\n")
    test_dir = project_root / "test" / "unit"
    test_dir.mkdir(parents=True, exist_ok=True)
    (test_dir / "test_foo.py").write_text("def test_add():\n    assert add(1, 2) == 3\n")


def write_coverage_xml(
    project_root: Path, line_rate: float, branch_rate: float | None = None,
    name: str = "coverage.xml",
) -> None:
    """Write a minimal Cobertura report with the given rates (fractions 0..1)."""
    attrs = f'line-rate="{line_rate}"'
    if branch_rate is not None:
        attrs += f' branch-rate="{branch_rate}"'
    (project_root / name).write_text(
        f'<?xml version="1.0" ?>\n<coverage {attrs} version="1.0">\n'
        "  <packages/>\n</coverage>\n"
    )


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


def test_passes_when_all_source_files_have_tests(tmp_path: Path) -> None:
    """All .py files in src/ have a corresponding test_*.py with at least one test."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "foo.py").write_text("def add(a, b):\n    return a + b\n")

    test_dir = tmp_path / "test" / "unit"
    test_dir.mkdir(parents=True)
    (test_dir / "test_foo.py").write_text("def test_add():\n    assert 1 + 1 == 2\n")

    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stderr


def test_passes_with_custom_dirs(tmp_path: Path) -> None:
    """Custom --src-dir and --test-dir flags are respected."""
    custom_src = tmp_path / "lib"
    custom_src.mkdir()
    (custom_src / "bar.py").write_text("x = 1\n")

    custom_tests = tmp_path / "specs"
    custom_tests.mkdir()
    (custom_tests / "test_bar.py").write_text("def test_bar():\n    assert True\n")

    result = run_validator(
        tmp_path,
        "--src-dir", "lib",
        "--test-dir", "specs",
    )
    assert result.returncode == 0, result.stderr


def test_ignores_init_files(tmp_path: Path) -> None:
    """__init__.py files do not require a corresponding test file."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "__init__.py").write_text("")
    (src / "util.py").write_text("pass\n")

    test_dir = tmp_path / "test" / "unit"
    test_dir.mkdir(parents=True)
    (test_dir / "test_util.py").write_text("def test_util():\n    pass\n")

    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stderr


def test_handles_nested_directories_with_mirror_path(tmp_path: Path) -> None:
    """src/sub/bar.py maps to test/unit/sub/test_bar.py (mirrored path)."""
    sub = tmp_path / "src" / "sub"
    sub.mkdir(parents=True)
    (sub / "bar.py").write_text("pass\n")

    test_sub = tmp_path / "test" / "unit" / "sub"
    test_sub.mkdir(parents=True)
    (test_sub / "test_bar.py").write_text("def test_bar():\n    pass\n")

    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stderr


def test_handles_nested_directories_with_flat_test_path(tmp_path: Path) -> None:
    """src/sub/bar.py also matches test/unit/test_bar.py (flat fallback)."""
    sub = tmp_path / "src" / "sub"
    sub.mkdir(parents=True)
    (sub / "bar.py").write_text("pass\n")

    test_dir = tmp_path / "test" / "unit"
    test_dir.mkdir(parents=True)
    (test_dir / "test_bar.py").write_text("def test_bar():\n    pass\n")

    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# Failure-path tests
# ---------------------------------------------------------------------------


def test_fails_when_source_file_has_no_test(tmp_path: Path) -> None:
    """A .py source file with no corresponding test_*.py causes failure."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "foo.py").write_text("def foo():\n    pass\n")

    test_dir = tmp_path / "test" / "unit"
    test_dir.mkdir(parents=True)
    # Deliberately no test_foo.py created

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


def test_fails_when_test_file_is_empty(tmp_path: Path) -> None:
    """A test file that is completely empty (no test functions) causes failure."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "foo.py").write_text("pass\n")

    test_dir = tmp_path / "test" / "unit"
    test_dir.mkdir(parents=True)
    (test_dir / "test_foo.py").write_text("")  # empty — no def test_

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


def test_fails_when_test_file_has_no_test_function(tmp_path: Path) -> None:
    """A test file that exists but has no 'def test_' function causes failure."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "foo.py").write_text("pass\n")

    test_dir = tmp_path / "test" / "unit"
    test_dir.mkdir(parents=True)
    (test_dir / "test_foo.py").write_text("# placeholder\nIMPORT_ME = True\n")

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


# ---------------------------------------------------------------------------
# Exit-code contract tests
# ---------------------------------------------------------------------------


def test_exits_zero_on_pass(tmp_path: Path) -> None:
    """Validator exits with code 0 when all checks pass."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "alpha.py").write_text("pass\n")

    test_dir = tmp_path / "test" / "unit"
    test_dir.mkdir(parents=True)
    (test_dir / "test_alpha.py").write_text("def test_alpha():\n    assert True\n")

    result = run_validator(tmp_path)
    assert result.returncode == 0


def test_exits_one_on_fail(tmp_path: Path) -> None:
    """Validator exits with code 1 when any check fails."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "missing_test.py").write_text("pass\n")

    test_dir = tmp_path / "test" / "unit"
    test_dir.mkdir(parents=True)
    # No test file

    result = run_validator(tmp_path)
    assert result.returncode == 1


# ---------------------------------------------------------------------------
# Advisory / warning behaviour
# ---------------------------------------------------------------------------


def test_git_ordering_is_advisory_not_hard_fail(tmp_path: Path, monkeypatch) -> None:
    """Simulating an environment where git is unavailable does not cause a hard fail
    as long as all source files have non-empty test files."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "service.py").write_text("pass\n")

    test_dir = tmp_path / "test" / "unit"
    test_dir.mkdir(parents=True)
    (test_dir / "test_service.py").write_text("def test_service():\n    pass\n")

    # Run without any git context — validator should still pass (git check is advisory)
    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stderr


def test_multiple_source_files_all_need_tests(tmp_path: Path) -> None:
    """When multiple source files exist, every one of them needs a test file."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("pass\n")
    (src / "b.py").write_text("pass\n")
    (src / "c.py").write_text("pass\n")

    test_dir = tmp_path / "test" / "unit"
    test_dir.mkdir(parents=True)
    (test_dir / "test_a.py").write_text("def test_a():\n    assert True\n")
    (test_dir / "test_b.py").write_text("def test_b():\n    assert True\n")
    # c.py is intentionally missing a test

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


def test_empty_src_dir_exits_zero(tmp_path: Path) -> None:
    """An empty src directory means nothing to check — validator exits 0."""
    src = tmp_path / "src"
    src.mkdir()

    test_dir = tmp_path / "test" / "unit"
    test_dir.mkdir(parents=True)

    result = run_validator(tmp_path)
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# Coverage gate (M-2)
# ---------------------------------------------------------------------------


def test_no_coverage_report_is_advisory(tmp_path: Path) -> None:
    """With source + tests but no coverage report, the gate is advisory (exit 0)."""
    make_src_with_test(tmp_path)

    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "ADVISORY" in result.stdout and "coverage gate skipped" in result.stdout


def test_coverage_above_threshold_passes(tmp_path: Path) -> None:
    """A coverage report at 85% line coverage passes the default 80% gate."""
    make_src_with_test(tmp_path)
    write_coverage_xml(tmp_path, line_rate=0.85)

    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stdout
    assert "OK: line coverage 85.0%" in result.stdout


def test_coverage_below_threshold_fails(tmp_path: Path) -> None:
    """A coverage report at 50% line coverage fails the default 80% gate."""
    make_src_with_test(tmp_path)
    write_coverage_xml(tmp_path, line_rate=0.50)

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout
    assert "FAIL: line coverage 50.0%" in result.stdout


def test_coverage_exactly_at_threshold_passes(tmp_path: Path) -> None:
    """Exactly 80% line coverage passes (threshold is inclusive)."""
    make_src_with_test(tmp_path)
    write_coverage_xml(tmp_path, line_rate=0.80)

    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stdout


def test_branch_coverage_below_threshold_fails(tmp_path: Path) -> None:
    """Line coverage OK but branch coverage below 75% fails."""
    make_src_with_test(tmp_path)
    write_coverage_xml(tmp_path, line_rate=0.95, branch_rate=0.50)

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout
    assert "branch coverage 50.0%" in result.stdout


def test_min_coverage_override_relaxes_gate(tmp_path: Path) -> None:
    """--min-coverage lowers the threshold so 50% coverage passes."""
    make_src_with_test(tmp_path)
    write_coverage_xml(tmp_path, line_rate=0.50)

    result = run_validator(tmp_path, "--min-coverage", "40")
    assert result.returncode == 0, result.stdout


def test_require_coverage_report_fails_when_absent(tmp_path: Path) -> None:
    """--require-coverage-report turns a missing report into a hard failure."""
    make_src_with_test(tmp_path)

    result = run_validator(tmp_path, "--require-coverage-report")
    assert result.returncode == 1, result.stdout
    assert "no coverage report" in result.stdout


def test_malformed_coverage_report_is_advisory(tmp_path: Path) -> None:
    """An unparseable coverage report is advisory, not a hard failure."""
    make_src_with_test(tmp_path)
    (tmp_path / "coverage.xml").write_text("this is not xml <<<")

    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stdout
    assert "could not be parsed" in result.stdout


def test_coverage_config_from_validators_yml(tmp_path: Path) -> None:
    """.validators.yml coverage.line threshold is honored."""
    make_src_with_test(tmp_path)
    write_coverage_xml(tmp_path, line_rate=0.70)
    (tmp_path / ".validators.yml").write_text("coverage:\n  line: 90\n")

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout
    assert "below the 90% threshold" in result.stdout


def test_custom_coverage_report_path(tmp_path: Path) -> None:
    """--coverage-report points the gate at a non-default report path."""
    make_src_with_test(tmp_path)
    write_coverage_xml(tmp_path, line_rate=0.50, name="cov-custom.xml")

    result = run_validator(tmp_path, "--coverage-report", "cov-custom.xml")
    assert result.returncode == 1, result.stdout
    assert "line coverage 50.0%" in result.stdout
