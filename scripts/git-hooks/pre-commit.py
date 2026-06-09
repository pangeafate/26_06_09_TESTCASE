#!/usr/bin/env python3
"""Fast local pre-commit gateway hook.

Runs only fast, deterministic checks. Full compliance remains in pre-push via
scripts/dev-gateway.py --stage pre-push.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True)


def _repo_root() -> Path | None:
    result = _run(["git", "rev-parse", "--show-toplevel"])
    if result.returncode != 0:
        print("[pre-commit] WARNING: not inside a git repo; skipping gateway", file=sys.stderr)
        return None
    return Path(result.stdout.strip())


def main() -> int:
    repo = _repo_root()
    if repo is None:
        return 0
    gateway = repo / "scripts" / "dev-gateway.py"
    if not gateway.is_file():
        print("[pre-commit] WARNING: scripts/dev-gateway.py missing; skipping gateway", file=sys.stderr)
        return 0
    result = subprocess.run(
        [sys.executable, "scripts/dev-gateway.py", ".", "--stage", "pre-commit"],
        cwd=repo,
        text=True,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
