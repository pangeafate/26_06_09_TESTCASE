"""
Tests for validate_module_size.py

Validator contract (language-agnostic module-size sensor):
- Scans configured source_roots for files with configured extensions.
- A file whose line count exceeds ``fail_lines`` is a hard FAIL (exit 1).
- A file whose line count exceeds ``warn_lines`` (but not ``fail_lines``) is a
  WARNING (exit 0).
- A file whose import-like line count exceeds ``warn_imports`` is a WARNING.
- ``exclude`` globs (and built-in vendored/generated dirs) are skipped entirely.
- ``allow`` globs grandfather a file: it still WARNs but never FAILs.
- ``enabled: false`` short-circuits to a pass.
- Thresholds / roots / extensions are configurable via .validators.yml.
- Returns 0 on pass (or warnings only), 1 on any hard failure.
"""
import subprocess
import sys
from pathlib import Path

VALIDATOR = Path(__file__).parent / "validate_module_size.py"


def run_validator(project_root: Path, *extra_args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(project_root), *extra_args],
        capture_output=True,
        text=True,
    )


def write_config(project_root: Path, body: str) -> None:
    (project_root / ".validators.yml").write_text(body, encoding="utf-8")


def make_file(root: Path, rel: str, n_lines: int, import_lines: int = 0) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f'import mod{i} from "x";' for i in range(import_lines)]
    lines += [f"const x{i} = {i};" for i in range(max(0, n_lines - import_lines))]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


SMALL_CONFIG = (
    "module_size:\n"
    "  source_roots: [src]\n"
    "  extensions: ['.ts', '.py']\n"
    "  warn_lines: 5\n"
    "  fail_lines: 10\n"
    "  warn_imports: 3\n"
)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_passes_when_all_files_small(tmp_path: Path) -> None:
    write_config(tmp_path, SMALL_CONFIG)
    make_file(tmp_path, "src/a.ts", 3)
    make_file(tmp_path, "src/sub/b.py", 4)
    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_passes_when_no_source_roots_present(tmp_path: Path) -> None:
    write_config(tmp_path, SMALL_CONFIG)
    # No src/ directory at all.
    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Failure path: line count
# ---------------------------------------------------------------------------


def test_fails_when_file_exceeds_fail_lines(tmp_path: Path) -> None:
    write_config(tmp_path, SMALL_CONFIG)
    make_file(tmp_path, "src/huge.ts", 25)
    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout
    assert "huge.ts" in result.stdout


def test_warns_but_passes_between_warn_and_fail(tmp_path: Path) -> None:
    write_config(tmp_path, SMALL_CONFIG)
    make_file(tmp_path, "src/medium.ts", 7)  # > warn(5), < fail(10)
    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stdout
    assert "WARNING" in result.stdout
    assert "medium.ts" in result.stdout


# ---------------------------------------------------------------------------
# Imports (warn-only)
# ---------------------------------------------------------------------------


def test_warns_on_too_many_imports_but_passes(tmp_path: Path) -> None:
    write_config(tmp_path, SMALL_CONFIG)
    # 4 imports > warn_imports(3), but only 4 lines < warn_lines(5).
    make_file(tmp_path, "src/imp.ts", 4, import_lines=4)
    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stdout
    assert "import" in result.stdout.lower()
    assert "imp.ts" in result.stdout


# ---------------------------------------------------------------------------
# Exclusions
# ---------------------------------------------------------------------------


def test_excluded_glob_is_skipped(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        SMALL_CONFIG + "  exclude: ['*.gen.ts']\n",
    )
    make_file(tmp_path, "src/big.gen.ts", 25)  # would fail, but excluded
    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stdout


def test_vendored_dirs_skipped_by_default(tmp_path: Path) -> None:
    write_config(tmp_path, SMALL_CONFIG)
    make_file(tmp_path, "src/node_modules/dep.ts", 25)
    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stdout


def test_non_source_extension_ignored(tmp_path: Path) -> None:
    write_config(tmp_path, SMALL_CONFIG)
    make_file(tmp_path, "src/data.json", 25)  # .json not in extensions
    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stdout


# ---------------------------------------------------------------------------
# Grandfathering and disabling
# ---------------------------------------------------------------------------


def test_allow_listed_file_warns_not_fails(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        SMALL_CONFIG + "  allow: ['src/legacy/*']\n",
    )
    make_file(tmp_path, "src/legacy/huge.ts", 25)  # over fail, but grandfathered
    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stdout
    assert "huge.ts" in result.stdout
    assert "WARNING" in result.stdout


def test_disabled_short_circuits_to_pass(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        "module_size:\n  enabled: false\n  source_roots: [src]\n"
        "  extensions: ['.ts']\n  fail_lines: 10\n",
    )
    make_file(tmp_path, "src/huge.ts", 50)
    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stdout


# ---------------------------------------------------------------------------
# Defaults (no module_size config key)
# ---------------------------------------------------------------------------


def test_default_thresholds_pass_for_normal_file(tmp_path: Path) -> None:
    # No config at all → built-in defaults (fail_lines ~2000). A 100-line file passes.
    make_file(tmp_path, "src/normal.ts", 100)
    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_default_thresholds_fail_for_giant_file(tmp_path: Path) -> None:
    # No config → built-in fail_lines default; a 2500-line file must FAIL.
    make_file(tmp_path, "src/giant.ts", 2500)
    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout
