#!/usr/bin/env python3
"""Validate project structure: required directories, files, and layer boundaries.

Usage:
    python validate_structure.py <project_root>

Configuration via <project_root>/.validators.yml:
    required_dirs:   list of directory paths that must exist (overrides defaults)
    required_files:  list of file paths that must exist (overrides defaults)
    layer_rules:     dict of {dir_path: {forbidden_imports: [prefix, ...]}}

Exit codes:
    0 — all checks pass
    1 — one or more checks fail
"""
import ast
import argparse
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

DEFAULT_REQUIRED_DIRS: list[str] = [
    "test/unit",
    "test/integration",
]

DEFAULT_REQUIRED_FILES: list[str] = [
    "PROJECT_CONTEXT.md",
    "ARCHITECTURE.md",
    "CODEBASE_STRUCTURE.md",
    "PROGRESS.md",
    "PROJECT_ROADMAP.md",
]


def _load_config(project_root: Path) -> dict[str, Any]:
    """Load .validators.yml from project_root, returning an empty dict if absent."""
    config_path = project_root / ".validators.yml"
    if not config_path.exists():
        return {}
    if yaml is None:
        print("WARNING: PyYAML not installed — .validators.yml ignored, using defaults")
        return {}
    try:
        content = config_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
        return data if isinstance(data, dict) else {}
    except (OSError, yaml.YAMLError):
        print("WARNING: .validators.yml is malformed or unreadable — using defaults")
        return {}


def _check_directories(project_root: Path, required_dirs: list[str]) -> list[tuple[bool, str]]:
    """Check that each required directory exists. Returns (passed, message) pairs."""
    results: list[tuple[bool, str]] = []
    for rel_dir in required_dirs:
        full_path = project_root / rel_dir
        if full_path.is_dir():
            results.append((True, f"OK: directory '{rel_dir}' exists"))
        else:
            results.append((False, f"FAIL: required directory '{rel_dir}' is missing"))
    return results


def _check_files(project_root: Path, required_files: list[str]) -> list[tuple[bool, str]]:
    """Check that each required file exists. Returns (passed, message) pairs."""
    results: list[tuple[bool, str]] = []
    for rel_file in required_files:
        full_path = project_root / rel_file
        if full_path.is_file():
            results.append((True, f"OK: file '{rel_file}' exists"))
        else:
            results.append((False, f"FAIL: required file '{rel_file}' is missing"))
    return results


def _collect_imports_from_file(py_file: Path) -> list[str]:
    """Return all top-level module names referenced in import statements.

    Handles:
      import foo.bar        -> ["foo.bar"]
      from foo.bar import x -> ["foo.bar"]
    """
    try:
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))
    except (OSError, SyntaxError):
        return []

    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.append(node.module)
    return modules


def _path_to_module_prefix(path_prefix: str) -> str:
    """Convert a path-style prefix (src/lib) to a dotted module prefix (src.lib)."""
    return path_prefix.replace("/", ".").replace("\\", ".")


def _check_layer_rules(
    project_root: Path,
    layer_rules: dict[str, Any],
) -> list[tuple[bool, str]]:
    """Enforce layer boundary rules defined in layer_rules.

    For each directory key, scan every .py file and ensure no import starts
    with a forbidden prefix (path-style converted to dotted notation).
    """
    results: list[tuple[bool, str]] = []

    for dir_path, rule in layer_rules.items():
        layer_dir = project_root / dir_path
        if not layer_dir.is_dir():
            # Directory does not exist — nothing to check, treat as passing
            results.append((True, f"OK: layer directory '{dir_path}' not found, skipping"))
            continue

        forbidden_paths: list[str] = rule.get("forbidden_imports", [])
        forbidden_prefixes = [_path_to_module_prefix(p) for p in forbidden_paths]

        py_files = sorted(layer_dir.rglob("*.py"))
        for py_file in py_files:
            rel_file = py_file.relative_to(project_root)
            imported_modules = _collect_imports_from_file(py_file)

            for module in imported_modules:
                for forbidden_prefix in forbidden_prefixes:
                    # Match if module equals the prefix or starts with prefix + "."
                    if module == forbidden_prefix or module.startswith(forbidden_prefix + "."):
                        results.append((
                            False,
                            f"FAIL: layer violation in '{rel_file}' — "
                            f"imports '{module}' which is forbidden (prefix '{forbidden_prefix}')",
                        ))
                        break  # One violation per module is enough

        # If no violations were added for this directory, record a pass
        if not any(
            not passed and dir_path in msg
            for passed, msg in results
        ):
            results.append((True, f"OK: layer rules for '{dir_path}' — no violations"))

    return results


def validate(project_root: Path) -> tuple[int, list[str]]:
    """Run all structure checks. Returns (exit_code, messages)."""
    config = _load_config(project_root)

    required_dirs: list[str] = config.get("required_dirs", DEFAULT_REQUIRED_DIRS)
    required_files: list[str] = config.get("required_files", DEFAULT_REQUIRED_FILES)
    layer_rules: dict[str, Any] = config.get("layer_rules", {})

    all_results: list[tuple[bool, str]] = []
    all_results.extend(_check_directories(project_root, required_dirs))
    all_results.extend(_check_files(project_root, required_files))
    all_results.extend(_check_layer_rules(project_root, layer_rules))

    messages = [msg for _, msg in all_results]
    failed = any(not passed for passed, _ in all_results)

    return (1 if failed else 0), messages


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate project structure")
    parser.add_argument("project_root", type=Path, help="Project root directory")
    args = parser.parse_args()

    exit_code, messages = validate(args.project_root)

    for msg in messages:
        print(msg)

    if exit_code == 0:
        print("\nStructure validation passed.")
    else:
        print("\nStructure validation FAILED.")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
