#!/usr/bin/env python3
"""
consolidate-deps.py — union declared sprint dependencies into a pyproject snippet.

DEV_REINFORCE F-2. The fan-out rule forbids editing the shared `pyproject.toml`
mid-sprint (six agents appending to one `[project.dependencies]` block conflict
every merge). Instead each sprint declares its third-party packages in
frontmatter:

    dependencies: [anthropic>=0.40, voyageai>=0.3]   # runtime
    dev_dependencies: [pytest>=8]                     # dev / test only

This script reads every sprint plan under `workspace/sprints/` (all statuses by
default; `--active` to restrict to In Progress), unions the declared runtime and
dev dependencies, and prints a `pyproject.toml`-ready snippet for the
orchestrator to paste at integration. It does NOT edit `pyproject.toml` — the
union is a human-reviewed merge step, not an automatic mutation.

Usage:
    python scripts/consolidate-deps.py <project_root> [--active]

Exit codes (GL-ERROR-LOGGING):
    0 — snippet printed (even if empty)
    2 — usage error
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "validators"))
from _sprint_frontmatter import (  # noqa: E402
    FrontmatterParseError,
    parse_frontmatter,
)


def _as_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


def collect(project_root: Path, *, active_only: bool) -> tuple[list[str], list[str], list[str]]:
    """Return (runtime, dev, sources) — sorted, de-duplicated dep lists + the
    sprint files that contributed at least one dependency."""
    sprints_dir = project_root / "workspace" / "sprints"
    runtime: set[str] = set()
    dev: set[str] = set()
    sources: list[str] = []
    try:
        plans = sorted(sprints_dir.glob("SP_*.md"))
    except OSError:
        plans = []
    for plan in plans:
        try:
            fm = parse_frontmatter(plan)
        except (FrontmatterParseError, OSError):
            continue
        if active_only and str(fm.get("status", "")).strip().lower() != "in progress":
            continue
        rt = _as_list(fm.get("dependencies"))
        dv = _as_list(fm.get("dev_dependencies"))
        if rt or dv:
            sources.append(plan.name)
        runtime.update(rt)
        dev.update(dv)
    return sorted(runtime), sorted(dev), sources


def render(runtime: list[str], dev: list[str], sources: list[str]) -> str:
    lines: list[str] = []
    lines.append("# --- consolidated from sprint-plan `dependencies` (DEV_REINFORCE F-2) ---")
    if sources:
        lines.append(f"# contributing plans: {', '.join(sources)}")
    lines.append("")
    lines.append("[project]")
    lines.append("dependencies = [")
    for dep in runtime:
        lines.append(f'    "{dep}",')
    lines.append("]")
    lines.append("")
    lines.append("[dependency-groups]")
    lines.append("dev = [")
    for dep in dev:
        lines.append(f'    "{dep}",')
    lines.append("]")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: consolidate-deps.py <project_root> [--active]", file=sys.stderr)
        return 2
    project_root = Path(argv[0]).resolve()
    active_only = "--active" in argv[1:]
    runtime, dev, sources = collect(project_root, active_only=active_only)
    print(render(runtime, dev, sources))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
