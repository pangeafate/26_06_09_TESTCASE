#!/usr/bin/env python3
"""
validate_declared_deps.py — Declared-dependency presence validator.

DEV_REINFORCE F-2. During the SP_002–SP_007 fan-out, every sprint left
`pyproject.toml` unchanged (the fan-out rule forbade editing the shared
manifest), and the real dependency set survived only as prose scattered across
six plans — no single machine-readable list, hand-reconstructed at merge, and a
missed dependency surfaced as an ImportError only after integration.

This validator closes the "data on the floor" gap: every **active** (In Progress)
sprint that owns code must declare a `dependencies` frontmatter field — a
machine-readable list that `scripts/consolidate-deps.py` can union into
`pyproject.toml` mechanically. An empty list (`dependencies: []`) is a valid
explicit statement of "no new third-party deps"; the failure is *silence*, not
emptiness.

Enforcement is opt-in. By default the validator is ADVISORY (warns, exits 0) so
it never retroactively breaks historical frontmatter-less plans or the in-flight
worktrees whose deps are still in prose. Pass `--strict` (CI / integration) to
turn a missing declaration into a FAIL once every active plan carries the field.

A plan "owns code" if any `touches_paths` entry looks like source rather than a
doc: it ends in `.py`, contains a `/**` glob, or ends in `/` (a directory). A
plan that only touches `.md`/docs is exempt.

Usage:
    python validate_declared_deps.py <project_root> [--strict]

Exit codes:
    0 — no undeclared-dependency issues, or advisory mode (default)
    1 — at least one active code-owning plan lacks `dependencies` AND --strict
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _sprint_frontmatter import (  # noqa: E402  — shared helper
    FrontmatterParseError,
    parse_frontmatter,
    read_active_claims,
)

# Frontmatter keys that satisfy the declaration (presence of either counts).
_DECL_KEYS = ("dependencies", "dev_dependencies")


def _owns_code(touches_paths: tuple[str, ...]) -> bool:
    """True if any declared path looks like source code (not a pure-docs plan)."""
    for p in touches_paths:
        p = p.strip()
        if not p:
            continue
        if p.endswith(".py") or "/**" in p or p.endswith("/"):
            return True
    return False


def _coerce_paths(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if isinstance(value, (list, tuple)):
        return tuple(str(p) for p in value)
    return ()


def find_undeclared(project_root: Path) -> list[str]:
    """Return a message per active code-owning plan missing a deps declaration."""
    issues: list[str] = []
    claims = read_active_claims(
        project_root, statuses=("In Progress",), on_parse_error="warn"
    )
    for claim in claims:
        try:
            fm = parse_frontmatter(claim.path)
        except (FrontmatterParseError, OSError):
            continue  # malformed/raced plan — policed by other validators
        if not _owns_code(_coerce_paths(fm.get("touches_paths"))):
            continue
        if any(key in fm for key in _DECL_KEYS):
            continue
        issues.append(
            f"{claim.sprint_id} ({claim.path}) owns code but declares no "
            f"`dependencies` frontmatter field — add `dependencies: [...]` (use "
            f"`[]` for none) so scripts/consolidate-deps.py can union it into "
            f"pyproject.toml at merge (DEV_REINFORCE F-2)."
        )
    return issues


def validate(project_root: Path, *, strict: bool = False) -> int:
    issues = find_undeclared(project_root)
    if not issues:
        print("[Stage DEP] PASS: every active code-owning plan declares dependencies.")
        return 0

    label = "FAIL" if strict else "ADVISORY"
    stream = sys.stderr if strict else sys.stdout
    for msg in issues:
        print(f"[Stage DEP] {label}: {msg}", file=stream)
    if strict:
        return 1
    print(
        f"[Stage DEP] PASS (advisory): {len(issues)} plan(s) missing a deps "
        f"declaration — pass --strict to enforce."
    )
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print(
            "usage: validate_declared_deps.py <project_root> [--strict]",
            file=sys.stderr,
        )
        return 2
    project_root = Path(argv[0]).resolve()
    strict = "--strict" in argv[1:]
    return validate(project_root, strict=strict)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
