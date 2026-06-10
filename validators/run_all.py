#!/usr/bin/env python3
"""Run project validators in sequence.

Usage:
    python run_all.py <project_root> [--bootstrap] [--skip NAME[,NAME]] [--fix]

Flags:
    --bootstrap  Run only validate_structure and validate_workspace.
    --skip       Comma-separated validator names to skip.
    --fix        Create missing required directories before running validators.

Exit codes:
    0  all validators passed
    1  one or more validators failed
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ALL_VALIDATORS = [
    "validate_structure",
    "validate_workspace",
    "validate_tdd",
    "validate_rdd",
    "validate_module_size",
    "validate_sprint",
    "validate_sprint_overlap",
    "validate_worktree_isolation",
    "validate_declared_deps",
    "validate_doc_reality",
    "validate_doc_freshness",
]

BOOTSTRAP_VALIDATORS = [
    "validate_structure",
    "validate_workspace",
]

DEFAULT_FIX_DIRS = [
    "test/unit",
    "test/integration",
    "test/fixtures",
]


def _get_validators_dir() -> Path:
    override = os.environ.get("_VALIDATOR_DIR_OVERRIDE")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent


def _run_validator(name: str, project_root: Path) -> tuple[str, int]:
    script = _get_validators_dir() / f"{name}.py"
    if not script.is_file():
        print(f"[run_all] FAIL: missing validator {script}", file=sys.stderr)
        return name, 1
    result = subprocess.run(
        [sys.executable, str(script), str(project_root)],
        text=True,
    )
    return name, result.returncode


def _apply_fix_dirs(project_root: Path) -> None:
    for rel in DEFAULT_FIX_DIRS:
        (project_root / rel).mkdir(parents=True, exist_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_root")
    parser.add_argument("--bootstrap", action="store_true")
    parser.add_argument("--skip", default="")
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args(argv)

    project_root = Path(args.project_root).resolve()
    if args.fix:
        _apply_fix_dirs(project_root)

    selected = BOOTSTRAP_VALIDATORS if args.bootstrap else ALL_VALIDATORS
    skip = {x.strip() for x in args.skip.split(",") if x.strip()}
    results: list[tuple[str, int | str]] = []

    for name in selected:
        if name in skip:
            results.append((name, "SKIP"))
            print(f"[run_all] SKIP: {name}")
            continue
        results.append(_run_validator(name, project_root))

    print("\nValidator summary:")
    failed = False
    for name, code in results:
        status = "PASS" if code == 0 else str(code)
        if code not in (0, "SKIP"):
            failed = True
            status = "FAIL"
        print(f"  {name}: {status}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
