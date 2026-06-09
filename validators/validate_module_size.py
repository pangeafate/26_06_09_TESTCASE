#!/usr/bin/env python3
"""Validate module size — a language-agnostic God-file sensor.

GL-RDD mandates small, single-responsibility modules ("split at >8 imports,
cyclomatic >10, cognitive >15") but no validator ever enforced file size, so
modules can silently grow into thousands-of-lines God-files. This validator is
the missing mechanical sensor: it counts raw lines and import-like lines per
source file and flags the offenders. It does not split anything — it makes the
debt visible and stops *new* God-files from landing unnoticed.

Severity model (intentionally two-tier so adoption is not a hard wall):
- lines > ``fail_lines``  → FAIL (exit 1), unless the file is ``allow``-listed.
- lines > ``warn_lines``  → WARNING (exit 0).
- import-like lines > ``warn_imports`` → WARNING (exit 0). Imports are advisory
  because a composition root legitimately wires many modules; the line count is
  the load-bearing signal.

Language-agnostic: works on any text source. Line count is a raw
``splitlines()`` count (what a human sees). Import detection uses a small
per-extension regex map; imperfect grouping (e.g. Go ``import (`` blocks) is
acceptable since imports are warn-only.

Configuration (``.validators.yml`` at project_root, key ``module_size``):

    module_size:
      enabled: true                 # set false to short-circuit to a pass
      source_roots: [src, scripts, skills]
      extensions: ['.ts', '.tsx', '.js', '.jsx', '.py', '.go', '.rs', ...]
      warn_lines: 800
      fail_lines: 2000
      warn_imports: 25
      exclude: ['*.min.js', '*.generated.*']   # fnmatch over repo-relative path
      allow:   ['src/runtime/components.ts']    # grandfathered: warn, never fail

``exclude`` globs and ``allow`` globs are fnmatch patterns over the
project-root-relative POSIX path; ``*`` spans directory separators, so use
``*.gen.ts`` rather than ``**/*.gen.ts``. Built-in vendored/generated
directories (.git, .venv, node_modules, dist, build, __pycache__, vendor, …)
are always skipped.

Usage:
    python validate_module_size.py <project_root>

Exit codes:
    0 — no hard failures (warnings may be present)
    1 — one or more files exceed fail_lines and are not allow-listed
"""
from __future__ import annotations

import argparse
import fnmatch
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_SOURCE_ROOTS = ["src", "scripts", "skills"]
DEFAULT_EXTENSIONS = [
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".py", ".go", ".rs", ".java", ".kt", ".scala",
    ".rb", ".php", ".cs", ".c", ".cc", ".cpp", ".h", ".hpp",
    ".swift", ".m", ".mm",
]
DEFAULT_WARN_LINES = 800
DEFAULT_FAIL_LINES = 2000
DEFAULT_WARN_IMPORTS = 25

# Directory components that are never scanned (vendored / generated / VCS).
EXCLUDED_DIR_PARTS = {
    ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "vendor",
    "dist", "build", ".next", "out", "coverage", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".cache", ".gradle", "target",
}

# Per-extension import-line detector. Each pattern matches a single line that
# introduces a dependency. Warn-only, so coarse patterns are fine.
_IMPORT_PATTERNS = {
    # JS / TS family
    "js": re.compile(r"""^\s*(import\b|export\s+.*\bfrom\b|.*\brequire\s*\()"""),
    # Python
    "py": re.compile(r"^\s*(import\s+\S|from\s+\S+\s+import\b)"),
    # Go / Rust / Java / Kotlin / Scala / C# / C-family / Ruby / PHP / Swift
    "go": re.compile(r'^\s*(import\s+["(]|\s*"[^"]+"\s*$)'),
    "rs": re.compile(r"^\s*(use\s+\S|extern\s+crate\b)"),
    "jvm": re.compile(r"^\s*import\s+\S"),
    "cs": re.compile(r"^\s*using\s+\S"),
    "c": re.compile(r"^\s*#\s*include\b"),
    "rb": re.compile(r"^\s*(require|require_relative|load)\b"),
    "php": re.compile(r"^\s*(use\s+\S|require|require_once|include|include_once)\b"),
    "swift": re.compile(r"^\s*import\s+\S"),
}

_EXT_TO_IMPORT_KEY = {
    ".ts": "js", ".tsx": "js", ".js": "js", ".jsx": "js", ".mjs": "js", ".cjs": "js",
    ".py": "py",
    ".go": "go",
    ".rs": "rs",
    ".java": "jvm", ".kt": "jvm", ".scala": "jvm",
    ".cs": "cs",
    ".c": "c", ".cc": "c", ".cpp": "c", ".h": "c", ".hpp": "c", ".m": "c", ".mm": "c",
    ".rb": "rb",
    ".php": "php",
    ".swift": "swift",
}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _load_config(project_root: Path) -> dict:
    """Load the ``module_size`` block from .validators.yml; {} when absent."""
    config_path = project_root / ".validators.yml"
    if not config_path.exists() or yaml is None:
        return {}
    try:
        with config_path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(data, dict):
        return {}
    section = data.get("module_size")
    return section if isinstance(section, dict) else {}


def _as_list(value, default: list[str]) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    return default


def _as_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def _count_imports(text: str, ext: str) -> int:
    key = _EXT_TO_IMPORT_KEY.get(ext)
    if key is None:
        return 0
    pattern = _IMPORT_PATTERNS[key]
    return sum(1 for line in text.splitlines() if pattern.match(line))


def _is_vendored(rel_parts: tuple[str, ...]) -> bool:
    return any(part in EXCLUDED_DIR_PARTS for part in rel_parts)


def _matches_any(rel_posix: str, globs: list[str]) -> bool:
    return any(fnmatch.fnmatch(rel_posix, g) for g in globs)


def _iter_source_files(
    project_root: Path,
    source_roots: list[str],
    extensions: set[str],
    exclude: list[str],
):
    """Yield (path, rel_posix) for each in-scope source file."""
    for root_name in source_roots:
        root = project_root / root_name
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in extensions:
                continue
            rel = path.relative_to(project_root)
            if _is_vendored(rel.parts):
                continue
            rel_posix = rel.as_posix()
            if exclude and _matches_any(rel_posix, exclude):
                continue
            yield path, rel_posix


def _read_lines(path: Path) -> int | None:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None
    return len(text.splitlines())


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate(project_root: Path) -> tuple[int, list[str]]:
    """Run the module-size sensor. Returns (exit_code, messages)."""
    cfg = _load_config(project_root)

    if cfg.get("enabled") is False:
        return 0, ["OK: module_size disabled via .validators.yml"]

    source_roots = _as_list(cfg.get("source_roots"), DEFAULT_SOURCE_ROOTS)
    extensions = set(_as_list(cfg.get("extensions"), DEFAULT_EXTENSIONS))
    warn_lines = _as_int(cfg.get("warn_lines"), DEFAULT_WARN_LINES)
    fail_lines = _as_int(cfg.get("fail_lines"), DEFAULT_FAIL_LINES)
    warn_imports = _as_int(cfg.get("warn_imports"), DEFAULT_WARN_IMPORTS)
    exclude = _as_list(cfg.get("exclude"), [])
    allow = _as_list(cfg.get("allow"), [])

    failures: list[str] = []
    warnings: list[str] = []
    scanned = 0

    for path, rel_posix in _iter_source_files(
        project_root, source_roots, extensions, exclude
    ):
        n_lines = _read_lines(path)
        if n_lines is None:
            continue
        scanned += 1
        grandfathered = _matches_any(rel_posix, allow)

        if n_lines > fail_lines:
            if grandfathered:
                warnings.append(
                    f"WARNING: {rel_posix} is {n_lines} lines "
                    f"(> fail_lines {fail_lines}) — grandfathered via allow-list; "
                    "tracked debt, split it down"
                )
            else:
                failures.append(
                    f"FAIL: {rel_posix} is {n_lines} lines "
                    f"(> fail_lines {fail_lines}) — split this module (GL-RDD SRP)"
                )
        elif n_lines > warn_lines:
            warnings.append(
                f"WARNING: {rel_posix} is {n_lines} lines "
                f"(> warn_lines {warn_lines}) — approaching God-file size"
            )

        ext = path.suffix
        n_imports = _count_imports_safe(path, ext)
        if n_imports > warn_imports:
            warnings.append(
                f"WARNING: {rel_posix} has {n_imports} imports "
                f"(> warn_imports {warn_imports}) — high coupling (GL-RDD)"
            )

    messages = failures + warnings
    if not messages:
        messages.append(
            f"OK: {scanned} source file(s) within size/import limits"
        )
    return (1 if failures else 0), messages


def _count_imports_safe(path: Path, ext: str) -> int:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return 0
    return _count_imports(text, ext)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Validate module size (God-file sensor)")
    parser.add_argument("project_root", type=Path, help="Project root directory")
    args = parser.parse_args()

    project_root: Path = args.project_root.resolve()
    exit_code, messages = validate(project_root)

    for msg in messages:
        print(msg)

    if exit_code == 0:
        print("\nModule-size validation passed.")
    else:
        print("\nModule-size validation FAILED.", file=sys.stderr)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
