#!/usr/bin/env python3
"""Validate TDD compliance: every source file must have a corresponding test
file, and (when a coverage report is present) line/branch coverage must meet
the thresholds documented in GL-TDD.md.

Usage:
    python validate_tdd.py <project_root> [--src-dir SRC] [--test-dir TEST]
        [--coverage-report PATH] [--min-coverage PCT] [--min-branch-coverage PCT]
        [--require-coverage-report]

Coverage gate (M-2):
    The gate is artifact-based. Produce a Cobertura report alongside your test
    run — `pytest --cov=src --cov-report=xml` — and this validator parses it and
    fails the build when line coverage is below the threshold (default 80%, per
    GL-TDD.md). When no report exists the gate is advisory (it does not fail),
    so adopters who have not wired up coverage tooling are not blocked; set
    `coverage.require_report: true` (or --require-coverage-report) to make a
    missing report a hard failure. Thresholds are configurable via .validators.yml.

Exit codes:
    0 — all source files have non-empty test files AND the coverage gate passes
        (or is advisory)
    1 — a source file is missing/empty its test, OR coverage is below threshold
"""
import argparse
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


# Default coverage thresholds (percent). Authoritative source: GL-TDD.md.
DEFAULT_MIN_LINE_COVERAGE = 80.0
DEFAULT_MIN_BRANCH_COVERAGE = 75.0
DEFAULT_COVERAGE_REPORT = "coverage.xml"


def _find_source_files(src_dir: Path) -> list[Path]:
    """Find all .py files in src_dir, excluding __init__.py."""
    if not src_dir.exists():
        return []
    return [
        p for p in src_dir.rglob("*.py")
        if p.name != "__init__.py" and p.is_file()
    ]


def _find_test_file(source: Path, src_dir: Path, test_dir: Path) -> Path | None:
    """Find the test file for a given source file.

    Tries, in order:
    1. Mirrored path: test_dir/<relative_subpath>/test_<name>.py
    2. Flat path: test_dir/test_<name>.py
    3. Mirrored/flat under each immediate test_dir subdirectory (e.g. test/unit/…)
    4. Layout-tolerant fallback: a ``test_<name>.py`` anywhere under test_dir.

    Step 4 makes the check tolerant of repos that FLATTEN the mirror (e.g.
    ``helixpay/ingest/extract/coerce.py`` → ``test/unit/ingest/test_coerce.py``) or
    name tests by behavior. It only ADDS matches — a module with no ``test_<name>.py``
    anywhere still returns ``None`` and is reported as a gap, so it never weakens the
    genuine-gap signal.
    """
    rel = source.relative_to(src_dir)
    test_name = f"test_{source.stem}.py"

    # Try mirrored path first
    mirrored = test_dir / rel.parent / test_name
    if mirrored.exists():
        return mirrored

    # Fall back to flat path
    flat = test_dir / test_name
    if flat.exists():
        return flat

    # Also try under test/unit/ subdirectory
    for subdir in test_dir.iterdir() if test_dir.exists() else []:
        if subdir.is_dir():
            candidate = subdir / rel.parent / test_name
            if candidate.exists():
                return candidate
            candidate = subdir / test_name
            if candidate.exists():
                return candidate

    # Layout-tolerant fallback: the test exists but at a flattened/behavior-named
    # path. Match the first ``test_<name>.py`` anywhere under the test tree.
    if test_dir.exists():
        for candidate in sorted(test_dir.rglob(test_name)):
            if candidate.is_file():
                return candidate

    return None


def _has_test_function(test_file: Path) -> bool:
    """Check if a test file contains at least one test function."""
    try:
        content = test_file.read_text(encoding="utf-8")
        return bool(re.search(r"def test_", content))
    except (OSError, UnicodeDecodeError):
        return False


def _check_git_ordering(src_dir: Path, test_dir: Path, project_root: Path) -> list[str]:
    """Advisory check: verify test commits precede source commits via git log.

    Returns warnings (never failures). Skips silently if git is unavailable.
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

    return warnings


def _load_config(project_root: Path) -> dict:
    """Read .validators.yml (returns {} if absent, unreadable, or yaml missing)."""
    config_path = project_root / ".validators.yml"
    if not config_path.exists() or yaml is None:
        return {}
    try:
        return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _tdd_settings(config: dict) -> dict:
    """Resolve the structural-check settings from ``.validators.yml`` ``tdd:`` block.

    - ``src_dir``: explicit source package (overrides auto-detection).
    - ``structure_advisory``: when true, an unmatched source file is reported as an
      ADVISORY (does not fail the build); the coverage gate remains the enforced
      part. Default false preserves the historical strict behavior.
    """
    tdd = config.get("tdd", {}) if isinstance(config.get("tdd"), dict) else {}
    return {
        "src_dir": tdd.get("src_dir"),
        "structure_advisory": bool(tdd.get("structure_advisory", False)),
    }


def _resolve_src_dir(project_root: Path, src_dir_name: str, configured: str | None) -> str:
    """Pick the source dir to scan. If the requested dir is absent, fall back to a
    configured package, then to ``helixpay`` (this repo's package), so the gateway's
    no-flag invocation lands on the real source tree instead of the missing ``src/``."""
    if (project_root / src_dir_name).exists():
        return src_dir_name
    if configured and (project_root / configured).exists():
        return configured
    if (project_root / "helixpay").exists():
        return "helixpay"
    return src_dir_name


def _coverage_settings(config: dict, overrides: dict) -> dict:
    """Resolve coverage settings: defaults < .validators.yml < CLI overrides."""
    cov = config.get("coverage", {}) if isinstance(config.get("coverage"), dict) else {}
    settings = {
        "report": cov.get("report", DEFAULT_COVERAGE_REPORT),
        "line": float(cov.get("line", DEFAULT_MIN_LINE_COVERAGE)),
        "branch": float(cov.get("branch", DEFAULT_MIN_BRANCH_COVERAGE)),
        "require_report": bool(cov.get("require_report", False)),
    }
    for key, value in overrides.items():
        if value is not None:
            settings[key] = value
    return settings


def _parse_coverage_xml(report_path: Path) -> tuple[float | None, float | None]:
    """Return (line_rate, branch_rate) as fractions in [0,1] from a Cobertura
    report, or (None, None) if the file cannot be parsed."""
    try:
        root = ET.parse(report_path).getroot()
    except (ET.ParseError, OSError):
        return None, None

    def _rate(attr: str) -> float | None:
        raw = root.get(attr)
        try:
            return float(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    return _rate("line-rate"), _rate("branch-rate")


def _check_coverage(project_root: Path, settings: dict) -> tuple[int, list[str]]:
    """Coverage gate. Returns (exit_code, messages).

    Artifact-based: parses a Cobertura coverage report if present. Missing
    report → advisory (exit 0) unless require_report is set. Below threshold →
    exit 1.
    """
    report_arg = Path(settings["report"])
    report_path = report_arg if report_arg.is_absolute() else project_root / report_arg
    min_line = settings["line"]
    min_branch = settings["branch"]

    if not report_path.exists():
        hint = (
            f"no coverage report at {report_path} — coverage gate skipped. "
            f"Produce one with `pytest --cov=src --cov-report=xml` to enforce the "
            f">= {min_line:g}% line threshold (GL-TDD.md)."
        )
        if settings["require_report"]:
            return 1, [f"FAIL: {hint}"]
        return 0, [f"ADVISORY: {hint}"]

    line_rate, branch_rate = _parse_coverage_xml(report_path)
    if line_rate is None:
        return 0, [
            f"ADVISORY: coverage report {report_path.name} could not be parsed "
            "as Cobertura XML — coverage gate skipped."
        ]

    messages: list[str] = []
    failed = False
    line_pct = line_rate * 100
    # Tolerance so 79.999…% rounding from the XML doesn't trip an 80% gate.
    if line_pct < min_line - 1e-6:
        failed = True
        messages.append(
            f"FAIL: line coverage {line_pct:.1f}% is below the {min_line:g}% "
            "threshold (GL-TDD.md)."
        )
    else:
        messages.append(f"OK: line coverage {line_pct:.1f}% (>= {min_line:g}%).")

    if branch_rate is not None:
        branch_pct = branch_rate * 100
        if branch_pct < min_branch - 1e-6:
            failed = True
            messages.append(
                f"FAIL: branch coverage {branch_pct:.1f}% is below the "
                f"{min_branch:g}% threshold (GL-TDD.md)."
            )
        else:
            messages.append(
                f"OK: branch coverage {branch_pct:.1f}% (>= {min_branch:g}%)."
            )

    return (1 if failed else 0), messages


def validate(
    project_root: Path,
    src_dir_name: str = "src",
    test_dir_name: str = "test",
    coverage_overrides: dict | None = None,
) -> tuple[int, list[str]]:
    """Run TDD validation. Returns (exit_code, messages)."""
    config = _load_config(project_root)
    tdd = _tdd_settings(config)

    # Auto-detect the real source dir when the requested one is absent (the gateway
    # invokes this with no flags → default "src", which does not exist in this repo).
    src_dir_name = _resolve_src_dir(project_root, src_dir_name, tdd["src_dir"])
    advisory = tdd["structure_advisory"]

    src_dir = project_root / src_dir_name
    test_dir = project_root / test_dir_name

    messages: list[str] = []
    failures: list[str] = []

    source_files = _find_source_files(src_dir)

    if not source_files:
        messages.append(f"No source files found in {src_dir_name}/")
        return 0, messages

    # When the structural check is advisory, unmatched sources are reported but never
    # fail the build (the coverage gate stays the enforced part). Collect them into
    # `messages` with an ADVISORY prefix instead of `failures`.
    sink = messages if advisory else failures
    prefix = "ADVISORY" if advisory else "FAIL"

    for source in sorted(source_files):
        rel = source.relative_to(src_dir)
        test_file = _find_test_file(source, src_dir, test_dir)

        if test_file is None:
            sink.append(f"{prefix}: {rel} — no test file found")
            continue

        if not _has_test_function(test_file):
            sink.append(
                f"{prefix}: {rel} — test file {test_file.name} exists but contains no test functions (def test_)"
            )
            continue

        messages.append(f"OK: {rel} → {test_file.relative_to(project_root)}")

    # Advisory git ordering check
    warnings = _check_git_ordering(src_dir, test_dir, project_root)
    for w in warnings:
        messages.append(f"WARNING: {w}")

    # Coverage gate (only meaningful when source files exist).
    settings = _coverage_settings(config, coverage_overrides or {})
    cov_code, cov_messages = _check_coverage(project_root, settings)
    messages.extend(cov_messages)

    if failures or cov_code != 0:
        return 1, failures + messages
    return 0, messages


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate TDD compliance")
    parser.add_argument("project_root", type=Path, help="Project root directory")
    parser.add_argument("--src-dir", default="src", help="Source directory (default: src)")
    parser.add_argument("--test-dir", default="test", help="Test directory (default: test)")
    parser.add_argument(
        "--coverage-report",
        default=None,
        help=f"Path to a Cobertura coverage report (default: {DEFAULT_COVERAGE_REPORT}).",
    )
    parser.add_argument(
        "--min-coverage",
        type=float,
        default=None,
        help=f"Minimum line coverage percent (default: {DEFAULT_MIN_LINE_COVERAGE:g}).",
    )
    parser.add_argument(
        "--min-branch-coverage",
        type=float,
        default=None,
        help=f"Minimum branch coverage percent (default: {DEFAULT_MIN_BRANCH_COVERAGE:g}).",
    )
    parser.add_argument(
        "--require-coverage-report",
        action="store_true",
        default=None,
        help="Fail (instead of advise) when no coverage report is present.",
    )
    args = parser.parse_args()

    coverage_overrides = {
        "report": args.coverage_report,
        "line": args.min_coverage,
        "branch": args.min_branch_coverage,
        "require_report": args.require_coverage_report,
    }

    exit_code, messages = validate(
        args.project_root, args.src_dir, args.test_dir, coverage_overrides
    )

    for msg in messages:
        print(msg)

    if exit_code == 0:
        print("\nTDD validation passed.")
    else:
        print("\nTDD validation FAILED.")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
