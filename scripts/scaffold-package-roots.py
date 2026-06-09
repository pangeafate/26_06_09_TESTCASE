#!/usr/bin/env python3
"""
scaffold-package-roots.py — pre-create shared package roots at the gate.

DEV_REINFORCE F-1. When two parallel agents own sibling modules under a common
package (Agent 1 owns `helixpay/ingest/loaders/**`, Agent 2 owns
`helixpay/ingest/**`), the *parent* package `__init__.py` belongs to neither
brief — so both agents independently create it, and it collides at merge
(`helixpay/ingest/__init__.py` did exactly this). The fix is structural: the
Phase-0 gate commits the shared package roots **before** fan-out, so agents
*add to* a file that already exists on `main` instead of *racing to create* it.

This helper creates a missing `__init__.py` (and `py.typed` when asked) for each
named package directory, idempotently — an existing file is never overwritten.
Run it at the gate with the package roots that more than one downstream agent
will write under.

Usage:
    python scripts/scaffold-package-roots.py <project_root> <pkg_dir> [<pkg_dir> ...] [--py-typed]

Example:
    python scripts/scaffold-package-roots.py . helixpay/ingest helixpay/query --py-typed

Exit codes (GL-ERROR-LOGGING):
    0 — roots ensured (created or already present)
    2 — usage error
"""
from __future__ import annotations

import sys
from pathlib import Path

_INIT_STUB = '"""Package root — pre-created at the gate (DEV_REINFORCE F-1).\n\nOwned by the gate, not by any single fan-out agent: pre-creating it on `main`\nstops two agents that own sibling subpackages from both creating it and\ncolliding at merge. Agents add to this file; they do not race to create it.\n"""\n'


def ensure_root(project_root: Path, pkg_dir: str, *, py_typed: bool) -> list[str]:
    """Create missing __init__.py (and optional py.typed) under pkg_dir. Returns
    the list of created relative paths (empty when everything already existed)."""
    created: list[str] = []
    base = project_root / pkg_dir
    base.mkdir(parents=True, exist_ok=True)

    init_path = base / "__init__.py"
    if not init_path.exists():
        init_path.write_text(_INIT_STUB, encoding="utf-8")
        created.append(str(init_path.relative_to(project_root)))

    if py_typed:
        typed_path = base / "py.typed"
        if not typed_path.exists():
            typed_path.write_text("", encoding="utf-8")
            created.append(str(typed_path.relative_to(project_root)))

    return created


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(
            "usage: scaffold-package-roots.py <project_root> <pkg_dir> "
            "[<pkg_dir> ...] [--py-typed]",
            file=sys.stderr,
        )
        return 2
    project_root = Path(argv[0]).resolve()
    py_typed = "--py-typed" in argv[1:]
    pkg_dirs = [a for a in argv[1:] if a != "--py-typed"]
    if not pkg_dirs:
        print("error: no package directories given", file=sys.stderr)
        return 2

    total: list[str] = []
    for pkg_dir in pkg_dirs:
        created = ensure_root(project_root, pkg_dir, py_typed=py_typed)
        for path in created:
            print(f"created {path}")
        total += created

    if not total:
        print("all package roots already present — nothing to do")
    else:
        print(f"ensured {len(pkg_dirs)} package root(s); created {len(total)} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
