#!/usr/bin/env python3
"""
Parallel-agent isolation validator.

Boris Cherny's team runs 3-5 parallel Claude sessions, each in its own git
worktree on its own branch, each producing its own PR — "the single biggest
productivity unlock". This validator makes that discipline first-class for
self-developing agents: every active sprint declares HOW it stays isolated from
its peers, and the declaration is checked.

Authoritative source for the rules: `practices/GL-PARALLEL-ISOLATION.md`.

Each sprint plan declares an `isolation` mode in frontmatter:

  * read-only    — analysis / docs / no code writes. Exempt from collision
                   checks (Boris's team's dedicated "analysis worktree").
  * shared-tree  — works in the main working tree, no dedicated branch. This is
                   the historical default; an omitted `isolation` field is
                   treated as `shared-tree` (backward compatible).
  * branch-only  — guarantees a distinct git branch (e.g. a separate checkout,
                   the way Boris personally works), without a managed worktree.
  * git-worktree — a dedicated git worktree on a dedicated branch (the team's
                   preferred mode; `claude --worktree`).

Checks (tier-aware so they REFINE rather than contradict the Rule-6 stance that
disjoint-path overlap is legitimate — see `find_path_overlaps` in
`validate_sprint_overlap.py`):

  WI-1  per-sprint declaration validity
        - unknown `isolation` value                                   → FAIL
        - `git-worktree` without a `worktree` path                    → FAIL
        - `git-worktree`/`branch-only` without a `branch`             → FAIL
        - `branch` set but does not reference the sprint id           → WARN
  WI-2  uniqueness across active sprints
        - two active sprints declaring the same `branch`              → FAIL
        - two active sprints declaring the same `worktree`            → FAIL
  WI-3  shared-tree collision (the C-6 resolution: escalate the SO-2 WARN to a
        FAIL only for the genuinely dangerous combination)
        - two non-isolated sprints, overlapping touches_paths, and at
          least one is a strict tier (Standard/Foundational/unspecified) → FAIL
        - same, but BOTH are Micro                                    → WARN
        - a strict-tier non-isolated sprint while another active
          non-read-only sprint exists (advisory nudge to isolate)     → WARN

A solo sprint, or fully disjoint/ properly-isolated parallel sprints, pass clean
— so existing single-stream projects and plans without an `isolation` field are
never newly blocked.

Exit codes:
  0 — no isolation failures (warnings may be present)
  1 — at least one isolation failure
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

# Shared frontmatter parser + the canonical ubiquitous-file ignore list. The
# path-prefix predicate below is a 1-liner deliberately duplicated from
# validate_sprint_overlap.py (Rule 18.7 — two consumers is not yet three) to
# keep each validator runnable as a standalone subprocess without importing a
# sibling validator's internals.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _sprint_frontmatter import (  # noqa: E402  — shared helper
    OVERLAP_IGNORE_PATHS,
    FrontmatterParseError,
    parse_frontmatter,
    read_active_claims,
)

ALLOWED_ISOLATION = frozenset({
    "read-only",
    "shared-tree",
    "branch-only",
    "git-worktree",
})

# Modes that guarantee a distinct branch (and therefore can run in parallel
# safely once WI-2 has confirmed the branch/worktree are unique).
ISOLATED_MODES = frozenset({"branch-only", "git-worktree"})

# Tiers whose floor relaxes (mirrors the review-iteration floor in
# GL-SELF-CRITIQUE.md: only an explicit `Micro` relaxes; everything else,
# including an unspecified tier, is held to the strong/strict floor).
RELAXED_TIER = "micro"

# Recognized tier values (CLAUDE.md "Tiers"). An unrecognized tier is treated as
# strict (the safe direction) but warned about so a typo is visible.
KNOWN_TIERS = frozenset({"precedent-clone", "micro", "standard", "foundational"})


@dataclass(frozen=True)
class IsoSprint:
    """Isolation-relevant view of an active sprint plan."""

    sprint_id: str
    tier: str | None          # lowercased, or None when unspecified
    isolation: str            # normalized; "shared-tree" when the field is absent
    isolation_declared: bool
    branch: str               # "" when absent
    worktree: str             # "" when absent
    touches_paths: tuple[str, ...]
    path: Path

    @property
    def is_read_only(self) -> bool:
        return self.isolation == "read-only"

    @property
    def is_isolated(self) -> bool:
        return self.isolation in ISOLATED_MODES

    @property
    def is_strict_tier(self) -> bool:
        # Only an explicit `Micro` relaxes; unspecified/unknown → strict.
        return self.tier != RELAXED_TIER


def _filter_paths(paths: tuple[str, ...]) -> list[str]:
    """Drop ubiquitous Rule-7 files before overlap checking (matches
    validate_sprint_overlap._filter_paths)."""
    return [p for p in paths if p not in OVERLAP_IGNORE_PATHS]


def _path_prefix_overlap(a: str, b: str) -> bool:
    """True if either path is a prefix of the other (directory-style). Duplicated
    from validate_sprint_overlap by design (see module header)."""
    return (
        a == b
        or a.startswith(b.rstrip("/") + "/")
        or b.startswith(a.rstrip("/") + "/")
    )


def _paths_overlap(a: IsoSprint, b: IsoSprint) -> bool:
    pa = _filter_paths(a.touches_paths)
    pb = _filter_paths(b.touches_paths)
    return any(_path_prefix_overlap(x, y) for x in pa for y in pb)


def _coerce_paths(value: object) -> tuple[str, ...]:
    """Normalize a frontmatter `touches_paths` value to a tuple of path strings.

    Guards the scalar case: `touches_paths: src/foo/` (no list brackets) parses
    to the *string* "src/foo/", and a naive `tuple(value)` would explode it into
    individual characters — silently voiding every overlap check. Treat a bare
    scalar as a one-element list.
    """
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if isinstance(value, (list, tuple)):
        return tuple(str(p) for p in value)
    return ()


def _to_iso_sprint(path: Path) -> IsoSprint:
    """Parse a sprint plan into an IsoSprint. Re-reads the plan file (the
    claim-reader does not surface tier/isolation/branch/worktree); raises
    FrontmatterParseError/OSError on a file that changed under us — the caller
    warns and skips."""
    fm = parse_frontmatter(path)

    tier_raw = fm.get("tier")
    tier = tier_raw.strip().lower() if isinstance(tier_raw, str) and tier_raw.strip() else None

    # isolation: None → field absent → shared-tree (backward compatible).
    # str "" or a non-str (e.g. a bare `isolation:` key parses to []) → field
    # PRESENT but empty/malformed → declared with isolation "" so the WI-1
    # unknown-value check fires instead of a silent shared-tree downgrade.
    iso_raw = fm.get("isolation")
    if iso_raw is None:
        isolation, declared = "shared-tree", False
    elif isinstance(iso_raw, str):
        isolation, declared = iso_raw.strip().lower(), True
    else:
        isolation, declared = "", True

    def _str(key: str) -> str:
        v = fm.get(key)
        return v.strip() if isinstance(v, str) else ""

    sprint_id = str(
        fm.get("sprint_id") or "_".join(path.stem.split("_")[:2])
    )

    return IsoSprint(
        sprint_id=sprint_id,
        tier=tier,
        isolation=isolation,
        isolation_declared=declared,
        branch=_str("branch"),
        worktree=_str("worktree"),
        touches_paths=_coerce_paths(fm.get("touches_paths")),
        path=path,
    )


def _load_active(project_root: Path) -> list[IsoSprint]:
    # warn-and-skip malformed plans, matching validate_sprint_overlap so one
    # archived bad-YAML file never crashes the CI isolation check.
    claims = read_active_claims(
        project_root,
        statuses=("In Progress",),
        on_parse_error="warn",
    )
    sprints: list[IsoSprint] = []
    for claim in claims:
        try:
            sprints.append(_to_iso_sprint(claim.path))
        except (FrontmatterParseError, OSError) as exc:
            # The claim-reader accepted this file moments ago; a re-parse failure
            # means it changed/vanished under us (the exact concurrent-write
            # scenario this validator guards). Surface it rather than silently
            # shrinking the comparison set.
            print(
                f"[Stage WI-1] WARN: {claim.path} was accepted by the claim "
                f"reader but failed re-parse ({exc}); skipped.",
                file=sys.stderr,
            )
            continue
    return sprints


def check_declarations(sprints: list[IsoSprint]) -> tuple[list[str], list[str]]:
    """WI-1 — per-sprint declaration validity. Returns (failures, warnings)."""
    failures: list[str] = []
    warnings: list[str] = []
    for s in sprints:
        if s.tier is not None and s.tier not in KNOWN_TIERS:
            warnings.append(
                f"[Stage WI-1] WARN: {s.sprint_id} declares unrecognized tier "
                f"'{s.tier}' — treated as strict (only 'micro' relaxes). "
                f"Known tiers: {sorted(KNOWN_TIERS)} (GL-PARALLEL-ISOLATION.md)."
            )
        if s.isolation not in ALLOWED_ISOLATION:
            shown = s.isolation if s.isolation else "(empty)"
            failures.append(
                f"[Stage WI-1] FAIL: {s.sprint_id} declares unknown isolation "
                f"'{shown}' — use one of {sorted(ALLOWED_ISOLATION)} "
                f"(GL-PARALLEL-ISOLATION.md)."
            )
            continue  # downstream completeness checks are meaningless on a bad value
        if s.isolation == "git-worktree" and not s.worktree:
            failures.append(
                f"[Stage WI-1] FAIL: {s.sprint_id} is isolation: git-worktree but "
                f"declares no `worktree` path (GL-PARALLEL-ISOLATION.md)."
            )
        if s.isolation in ISOLATED_MODES and not s.branch:
            failures.append(
                f"[Stage WI-1] FAIL: {s.sprint_id} is isolation: {s.isolation} but "
                f"declares no `branch` (GL-PARALLEL-ISOLATION.md)."
            )
        if s.branch and s.sprint_id not in s.branch:
            warnings.append(
                f"[Stage WI-1] WARN: {s.sprint_id} declares branch '{s.branch}' that "
                f"does not reference the sprint id — prefer `sprint/{s.sprint_id}-<slug>` "
                f"for traceability (GL-PARALLEL-ISOLATION.md)."
            )
    return failures, warnings


def check_uniqueness(sprints: list[IsoSprint]) -> list[str]:
    """WI-2 — branch/worktree uniqueness across active sprints (FAIL)."""
    failures: list[str] = []
    for field in ("branch", "worktree"):
        seen: dict[str, str] = {}
        for s in sprints:
            value = getattr(s, field)
            if not value:
                continue
            if value in seen:
                failures.append(
                    f"[Stage WI-2] FAIL: {seen[value]} and {s.sprint_id} both declare "
                    f"{field} '{value}' — two agents on the same {field} clobber each "
                    f"other (GL-PARALLEL-ISOLATION.md). Give each sprint a distinct {field}."
                )
            else:
                seen[value] = s.sprint_id
    return failures


def check_shared_tree(sprints: list[IsoSprint]) -> tuple[list[str], list[str]]:
    """WI-3 — shared-tree parallel collision. Returns (failures, warnings)."""
    failures: list[str] = []
    warnings: list[str] = []

    # Only non-isolated, code-writing sprints can collide in the shared tree.
    # read-only is exempt; git-worktree/branch-only carry a distinct branch
    # (uniqueness already enforced by WI-2).
    non_isolated = [s for s in sprints if not s.is_read_only and not s.is_isolated]

    # WI-3a / WI-3b — pairwise overlap among non-isolated sprints. Track which
    # sprints land in a FAIL so WI-3c does not pile a redundant advisory on top.
    failed_ids: set[str] = set()
    for i, a in enumerate(non_isolated):
        for b in non_isolated[i + 1:]:
            if not _paths_overlap(a, b):
                continue
            if a.is_strict_tier or b.is_strict_tier:
                failures.append(
                    f"[Stage WI-3] FAIL: {a.sprint_id} and {b.sprint_id} share the main "
                    f"working tree (isolation: {a.isolation}/{b.isolation}) and declare "
                    f"overlapping touches_paths while at least one is a strict tier — "
                    f"move to isolation: git-worktree or branch-only "
                    f"(GL-PARALLEL-ISOLATION.md)."
                )
                failed_ids.add(a.sprint_id)
                failed_ids.add(b.sprint_id)
            else:
                warnings.append(
                    f"[Stage WI-3] WARN: {a.sprint_id} and {b.sprint_id} (both Micro) share "
                    f"the main working tree and overlap on touches_paths — coordinate or "
                    f"isolate (GL-PARALLEL-ISOLATION.md)."
                )

    # WI-3c — advisory nudge: a strict-tier sprint sharing the tree with ANOTHER
    # non-isolated sprint should isolate even without a path overlap. Gate on the
    # non-isolated count (an already-isolated peer is not a reason to warn) and
    # skip sprints already named in a WI-3a FAIL (no redundant advisory).
    if len(non_isolated) > 1:
        for s in non_isolated:
            if s.is_strict_tier and s.sprint_id not in failed_ids:
                warnings.append(
                    f"[Stage WI-3] WARN: {s.sprint_id} ({s.tier or 'unspecified'} tier) runs in "
                    f"the shared working tree alongside other active sprints — consider "
                    f"isolation: git-worktree (GL-PARALLEL-ISOLATION.md)."
                )

    return failures, warnings


def validate(project_root: Path) -> int:
    sprints = _load_active(project_root)
    if not sprints:
        print("[Stage WI-1] PASS: no In Progress sprint plans to check.")
        return 0

    failures: list[str] = []
    warnings: list[str] = []

    decl_fail, decl_warn = check_declarations(sprints)
    failures += decl_fail
    warnings += decl_warn

    failures += check_uniqueness(sprints)

    tree_fail, tree_warn = check_shared_tree(sprints)
    failures += tree_fail
    warnings += tree_warn

    for w in warnings:
        print(w)
    for f in failures:
        print(f, file=sys.stderr)

    if failures:
        return 1

    print(
        f"[Stage WI] PASS: {len(sprints)} In Progress plan(s) — isolation declarations "
        f"valid (WI-1), branches/worktrees unique (WI-2), no shared-tree collisions (WI-3)."
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: validate_worktree_isolation.py <project_root>", file=sys.stderr)
        sys.exit(2)
    sys.exit(validate(Path(sys.argv[1])))
