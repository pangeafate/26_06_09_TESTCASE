#!/usr/bin/env python3
"""
SP_205 — Multi-agent ring-fencing validator.

Walks `workspace/sprints/SP_*.md`, finds plans whose frontmatter has
`status: In Progress`, and computes pairwise overlap on two declared
fields:

  * touches_checklist_items — list of `§N.N` references this sprint claims.
    Pairwise overlap → FAIL (deploy-blocking). Checklist items are
    precise; overlap is unambiguous coordination failure.

  * touches_paths — list of file/dir prefixes this sprint touches.
    Pairwise prefix overlap → WARN (advisory). Path overlap is often
    legitimate (two sprints both add validators); judgment-call.

Files every sprint touches by Rule 7 (PROGRESS, IMPLEMENTATION_CHECKLIST,
etc.) are excluded from the path-overlap check via OVERLAP_IGNORE_PATHS
to keep the false-positive rate low.

Exit codes:
  0 — no checklist-overlap (paths may have warnings)
  1 — at least one checklist-overlap pair
"""
from __future__ import annotations

import sys
from pathlib import Path

# SP_209 — frontmatter parsing + active-claims discovery + the
# `OVERLAP_IGNORE_PATHS` constant moved into the shared helper.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _sprint_frontmatter import (  # noqa: E402  — shared helper
    OVERLAP_IGNORE_PATHS,
    Claim,
    read_active_claims,
)


def _filter_paths(paths: list[str]) -> list[str]:
    """Drop ubiquitous files from the path list before overlap check."""
    return [p for p in paths if p not in OVERLAP_IGNORE_PATHS]


def _path_prefix_overlap(a: str, b: str) -> bool:
    """True if either path is a prefix of the other (directory-style)."""
    return a == b or a.startswith(b.rstrip("/") + "/") or b.startswith(a.rstrip("/") + "/")


def find_checklist_overlaps(claims: list[Claim]) -> list[tuple[str, str, str]]:
    """Return [(sprint_a, sprint_b, item)] for every checklist-item overlap."""
    overlaps: list[tuple[str, str, str]] = []
    for i, ca in enumerate(claims):
        items_a = set(ca.touches_checklist_items)
        if not items_a:
            continue
        for cb in claims[i + 1 :]:
            items_b = set(cb.touches_checklist_items)
            for item in items_a & items_b:
                overlaps.append((ca.sprint_id, cb.sprint_id, item))
    return overlaps


def find_path_overlaps(claims: list[Claim]) -> list[tuple[str, str, str, str]]:
    """Return [(sprint_a, sprint_b, path_a, path_b)] for filtered prefix overlaps."""
    overlaps: list[tuple[str, str, str, str]] = []
    for i, ca in enumerate(claims):
        paths_a = _filter_paths(list(ca.touches_paths))
        if not paths_a:
            continue
        for cb in claims[i + 1 :]:
            paths_b = _filter_paths(list(cb.touches_paths))
            for pa in paths_a:
                for pb in paths_b:
                    if _path_prefix_overlap(pa, pb):
                        overlaps.append((ca.sprint_id, cb.sprint_id, pa, pb))
    return overlaps


def validate(project_root: Path) -> int:
    # Stage-5 HIGH-2 fix: warn-and-skip malformed plans so a single
    # archived bad-YAML file doesn't crash the CI overlap check.
    claims = read_active_claims(
        project_root,
        statuses=("In Progress",),
        on_parse_error="warn",
    )
    if not claims:
        print("[Stage SO-1] PASS: no In Progress sprint plans to compare.")
        return 0

    fail = False
    checklist_overlaps = find_checklist_overlaps(claims)
    if checklist_overlaps:
        fail = True
        for sa, sb, item in checklist_overlaps:
            print(
                f"[Stage SO-1] FAIL: {sa} and {sb} both claim checklist item {item} "
                f"(touches_checklist_items overlap — coordinate or branch-isolate per Rule 11)",
                file=sys.stderr,
            )
    else:
        print(f"[Stage SO-1] PASS: no checklist-item overlap across {len(claims)} In Progress plan(s).")

    path_overlaps = find_path_overlaps(claims)
    if path_overlaps:
        for sa, sb, pa, pb in path_overlaps:
            print(
                f"[Stage SO-2] WARN: {sa} ({pa}) and {sb} ({pb}) declare overlapping touches_paths — "
                f"merge-conflict risk; coordinate or branch-isolate."
            )
    else:
        print(f"[Stage SO-2] PASS: no advisory path overlap.")

    return 1 if fail else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: validate_sprint_overlap.py <project_root>", file=sys.stderr)
        sys.exit(2)
    sys.exit(validate(Path(sys.argv[1])))
