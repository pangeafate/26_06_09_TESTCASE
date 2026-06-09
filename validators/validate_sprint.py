#!/usr/bin/env python3
"""
validate_sprint.py — Sprint cycle validator (7-stage subset).

Usage:
    python validate_sprint.py <project_root> [extra_args...]

Exit codes:
    0 — all enforced checks pass (or no active sprint found)
    1 — one or more checks failed

Enforced stages:
    Stage 1  — Sprint plan file exists
    Stage 2  — Sprint plan has all required sections
    Stage 3  — Pre-Implementation Review Log: >= tier floor entries with severity + files reviewed
    Stage 5  — Post-Implementation Review Log: >= tier floor entries with severity + files reviewed
    Stage 6  — PROGRESS.md updated (advisory, git-based, never fails the run; Stage 6 = Documentation per SP_002)

The review iteration floor scales with the sprint's `tier` frontmatter, per the
authoritative table in practices/GL-SELF-CRITIQUE.md ("Review Iteration Floor"):
Micro=1, Standard/Foundational=2, unspecified/unrecognized=2 (fail-safe). A
Micro single-iteration review additionally must name its independent reviewer
(a `Reviewer:` annotation) so it cannot be a builder self-rubber-stamp.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# A review entry starts with "- **Iteration N**"
_ITERATION_ENTRY_RE = re.compile(r"^\s*-\s+\*\*Iteration\s+\d+\*\*", re.MULTILINE)

# A valid entry must contain:
#   (a) an explicit severity keyword (CRITICAL, HIGH, MEDIUM, LOW), OR
#   (b) a numeric "0 issues" / "0 CRITICAL" style count
# This rejects pure rubber-stamp entries like "Looks good."
_SEVERITY_INDICATOR_RE = re.compile(
    r"\b(?:CRITICAL|HIGH|MEDIUM|LOW)\b"          # explicit severity level
    r"|"
    r"\b\d+\s+issues?\b"                          # e.g. "0 issues", "1 issue"
    r"|"
    r"\b\d+\s+CRITICAL\b"                         # e.g. "0 CRITICAL"
    r"|"
    r"\b\d+\s+CRITICAL/HIGH\b",                   # e.g. "0 CRITICAL/HIGH"
    re.IGNORECASE,
)

# "Files reviewed:" (case-insensitive)
_FILES_REVIEWED_RE = re.compile(r"files\s+reviewed\s*:", re.IGNORECASE)

# "Reviewer:" annotation (case-insensitive). Required on a Micro single-iteration
# review as the compensating guard for the dropped second-context floor. Matches
# the literal annotation only — "Files reviewed:" does not match (reviewed != reviewer).
_REVIEWER_ATTRIBUTION_RE = re.compile(r"reviewer\s*:", re.IGNORECASE)

# Tier -> minimum review iterations (floor). Authoritative source:
# practices/GL-SELF-CRITIQUE.md "Review Iteration Floor". Tier keys are matched
# case-insensitively. A missing or unrecognized tier falls back to the strong
# floor (2) — only an explicit `tier: Micro` relaxes the floor to 1.
_TIER_REVIEW_FLOOR: dict[str, int] = {
    "micro": 1,
    "standard": 2,
    "foundational": 2,
}
_DEFAULT_REVIEW_FLOOR = 2

# Required top-level sections in the sprint plan (## heading)
_REQUIRED_SECTIONS = [
    "## Sprint Goal",
    "## Testing Strategy",
    "## Success Criteria",
]
# At least one of these two must be present
_SCOPE_OR_APPROACH = ["## Scope", "## Technical Approach"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# SP_719 — single multi-agent-robust resolver (was a duplicated
# first-match copy w/ plain utf-8; _common standardises utf-8-sig +
# guard — strictly safer, BOM-tolerant). Drop-in import.
from _common import find_active_sprint  # noqa: E402  pylint: disable=wrong-import-position
from _diff_scope import scope_gate  # noqa: E402  pylint: disable=wrong-import-position
from _sprint_frontmatter import (  # noqa: E402  pylint: disable=wrong-import-position
    FrontmatterParseError,
    _parse_text,
)


def _read_tier(plan_text: str) -> str | None:
    """Return the lowercased `tier` frontmatter value, or None when absent.

    A malformed frontmatter block is treated as "no tier" (returns None) rather
    than crashing the sprint gate — frontmatter syntax is policed by the
    dedicated doc-freshness/overlap validators, not here.
    """
    try:
        fm = _parse_text(plan_text, Path("<plan>"))
    except FrontmatterParseError:
        return None
    tier = fm.get("tier")
    return tier.strip().lower() if isinstance(tier, str) and tier.strip() else None


def _review_floor(tier: str | None) -> int:
    """Map a (lowercased) tier to its minimum review-iteration floor.

    Authoritative mapping: practices/GL-SELF-CRITIQUE.md. Unknown/missing tier
    -> _DEFAULT_REVIEW_FLOOR (fail-safe strong floor).
    """
    if tier is None:
        return _DEFAULT_REVIEW_FLOOR
    return _TIER_REVIEW_FLOOR.get(tier, _DEFAULT_REVIEW_FLOOR)


def find_sprint_plan(project_root: Path, sprint_id: str) -> Path | None:
    """Locate the sprint plan file, trying multiple locations.

    Supports both exact match (SP_042.md) and slug match (SP_042_Goal_Name.md).
    """
    search_dirs = [
        project_root / "00_IMPLEMENTATION" / "SPRINTS",
        project_root / "workspace" / "sprints",
    ]
    for sprints_dir in search_dirs:
        if not sprints_dir.exists():
            continue
        # Exact match
        exact = sprints_dir / f"{sprint_id}.md"
        if exact.exists():
            return exact
        # Slug match: SP_042_*.md
        matches = list(sprints_dir.glob(f"{sprint_id}_*.md"))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            return matches[0]  # take first if multiple
        # Subfolder match: SP_042/SP_042.md or SP_042/SP_042_*.md
        subfolder = sprints_dir / sprint_id
        if subfolder.is_dir():
            exact_sub = subfolder / f"{sprint_id}.md"
            if exact_sub.exists():
                return exact_sub
            sub_matches = list(subfolder.glob(f"{sprint_id}_*.md"))
            if sub_matches:
                return sub_matches[0]
    return None


def extract_section_content(text: str, section_heading: str) -> str:
    """Return the content under a given ### heading, up to the next ### heading."""
    pattern = re.compile(
        r"^" + re.escape(section_heading) + r"\s*$(.+?)(?=^###|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    return match.group(1) if match else ""


def collect_iteration_entries(section_text: str) -> list[str]:
    """Return individual iteration entry lines from a review section."""
    entries: list[str] = []
    for line in section_text.splitlines():
        if _ITERATION_ENTRY_RE.match(line):
            entries.append(line)
    return entries


def entry_is_valid(entry: str) -> bool:
    """Return True if the entry contains a severity indicator AND 'Files reviewed:'."""
    return bool(_SEVERITY_INDICATOR_RE.search(entry)) and bool(
        _FILES_REVIEWED_RE.search(entry)
    )


def check_git_progress_updated(project_root: Path) -> None:
    """Advisory check: warn if PROGRESS.md has no uncommitted changes since last commit."""
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), "diff", "HEAD", "--", "PROGRESS.md"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and not result.stdout.strip():
            print(
                "[Stage 6] ADVISORY: PROGRESS.md has no uncommitted changes. "
                "Remember to update it after the sprint.",
                file=sys.stderr,
            )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        # git not available or timed out — skip silently
        pass


# ---------------------------------------------------------------------------
# Validation stages
# ---------------------------------------------------------------------------


def stage1_plan_exists(sprint_id: str, plan_path: Path | None) -> bool:
    if plan_path is None:
        print(
            f"[Stage 1] FAIL: Sprint plan not found for '{sprint_id}'. "
            "Expected locations: 00_IMPLEMENTATION/SPRINTS/<id>.md, "
            "00_IMPLEMENTATION/SPRINTS/<id>/<id>.md, or workspace/sprints/<id>.md",
            file=sys.stderr,
        )
        return False
    print(f"[Stage 1] PASS: Sprint plan found at {plan_path}", file=sys.stderr)
    return True


def stage2_required_sections(sprint_id: str, plan_text: str) -> bool:
    failures: list[str] = []

    for section in _REQUIRED_SECTIONS:
        if section not in plan_text:
            failures.append(section)

    if not any(s in plan_text for s in _SCOPE_OR_APPROACH):
        failures.append("## Scope' or '## Technical Approach")

    if failures:
        for missing in failures:
            print(
                f"[Stage 2] FAIL: Missing required section '{missing}' in {sprint_id}",
                file=sys.stderr,
            )
        return False

    print(f"[Stage 2] PASS: All required sections present in {sprint_id}", file=sys.stderr)
    return True


def _validate_review_section(
    stage_label: str, section_name: str, section_text: str, sprint_id: str, floor: int
) -> bool:
    """Shared logic for Stage 3 and Stage 5 review section validation.

    `floor` is the tier-derived minimum number of iteration entries (see
    _review_floor). When floor == 1 the single entry must additionally carry a
    `Reviewer:` annotation — the compensating guard for the dropped
    second-independent-context floor (see GL-SELF-CRITIQUE.md).
    """
    entries = collect_iteration_entries(section_text)

    if len(entries) < floor:
        print(
            f"[{stage_label}] FAIL: '{section_name}' in {sprint_id} has "
            f"{len(entries)} iteration entry/entries (need >= {floor}).",
            file=sys.stderr,
        )
        return False

    invalid: list[str] = []
    for entry in entries:
        if not entry_is_valid(entry):
            invalid.append(entry.strip())

    if invalid:
        print(
            f"[{stage_label}] FAIL: The following entries in '{section_name}' "
            f"lack a severity indicator or 'Files reviewed:' annotation:",
            file=sys.stderr,
        )
        for bad in invalid:
            print(f"  - {bad}", file=sys.stderr)
        return False

    # Compensating guard: a Micro single-iteration review (floor == 1, one
    # entry) loses the second-independent-context bias guard, so it must name
    # the reviewer that produced it.
    if floor == 1 and len(entries) == 1 and not _REVIEWER_ATTRIBUTION_RE.search(entries[0]):
        print(
            f"[{stage_label}] FAIL: '{section_name}' in {sprint_id} is a Micro-tier "
            "single-iteration review and must name its independent reviewer with a "
            "'Reviewer:' annotation (e.g. '... Reviewer: architect-reviewer'). "
            "This is the compensating guard for the relaxed (1) iteration floor.",
            file=sys.stderr,
        )
        return False

    print(
        f"[{stage_label}] PASS: '{section_name}' in {sprint_id} has "
        f"{len(entries)} valid entries.",
        file=sys.stderr,
    )
    return True


def stage3_pre_implementation_review(sprint_id: str, plan_text: str, floor: int) -> bool:
    section_name = "### Pre-Implementation Review"
    section_text = extract_section_content(plan_text, section_name)
    if not section_text.strip():
        print(
            f"[Stage 3] FAIL: No '{section_name}' section found in {sprint_id}.",
            file=sys.stderr,
        )
        return False
    return _validate_review_section("Stage 3", section_name, section_text, sprint_id, floor)


def stage5_post_implementation_review(sprint_id: str, plan_text: str, floor: int) -> bool:
    section_name = "### Post-Implementation Review"
    section_text = extract_section_content(plan_text, section_name)
    if not section_text.strip():
        print(
            f"[Stage 5] FAIL: No '{section_name}' section found in {sprint_id}.",
            file=sys.stderr,
        )
        return False
    return _validate_review_section("Stage 5", section_name, section_text, sprint_id, floor)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    if not argv:
        print("Usage: validate_sprint.py <project_root> [--gate pre-impl|post-impl|full]", file=sys.stderr)
        return 1

    project_root = Path(argv[0]).resolve()

    # Parse optional --gate flag and --allow-no-sprint flag
    gate = "full"
    allow_no_sprint_flag = False
    for i, arg in enumerate(argv[1:], 1):
        if arg == "--gate" and i + 1 < len(argv):
            gate = argv[i + 1]
        if arg == "--allow-no-sprint":
            allow_no_sprint_flag = True

    if gate not in ("pre-impl", "post-impl", "full"):
        print(f"[Error] Invalid gate: {gate}. Use: pre-impl, post-impl, full", file=sys.stderr)
        return 1

    # Detect active sprint
    sprint_id = find_active_sprint(project_root)
    if sprint_id is None:
        allow_no_sprint = allow_no_sprint_flag or bool(os.environ.get("SDA_ALLOW_NO_SPRINT"))
        if allow_no_sprint:
            print(
                "[Advisory] No active sprint found in PROGRESS.md "
                "(file missing or no '**Current:** SP_XXX' line). Skipping sprint validation.",
                file=sys.stderr,
            )
            return 0
        print(
            "[Error] No active sprint declared in PROGRESS.md "
            "(file missing or no '**Current:** SP_XXX' line). "
            "Declare an active sprint or pass --allow-no-sprint / set SDA_ALLOW_NO_SPRINT=1.",
            file=sys.stderr,
        )
        return 1

    # Scope the structural gate to the actually deploying sprint. Advisory
    # mode is allowed only when CI proves the deploy is code-free.
    scoped_id, gate_mode = scope_gate(project_root, sprint_id)
    if gate_mode == "advisory":
        print(
            "[SP_736] ADVISORY: deploy is provably code-free "
            "(DEV_DEPLOY_CODE_CHANGED=false); skipping sprint structural "
            f"gate for resolver-resolved '{sprint_id}'.",
            file=sys.stderr,
        )
        return 0
    if scoped_id is not None and scoped_id != sprint_id:
        print(
            f"[SP_736] Gate scoped from resolver '{sprint_id}' to deploying "
            f"sprint '{scoped_id}' (touches_paths ∩ code-set).",
            file=sys.stderr,
        )
        sprint_id = scoped_id

    print(f"[Info] Active sprint detected: {sprint_id}", file=sys.stderr)
    print(f"[Info] Gate: {gate}", file=sys.stderr)

    # Locate sprint plan
    plan_path = find_sprint_plan(project_root, sprint_id)

    passed = True

    # Stage 1 — always checked
    if not stage1_plan_exists(sprint_id, plan_path):
        return 1  # Cannot proceed without a plan

    plan_text = plan_path.read_text(encoding="utf-8")  # type: ignore[union-attr]

    # Resolve the tier-aware review floor (authoritative: GL-SELF-CRITIQUE.md).
    tier = _read_tier(plan_text)
    floor = _review_floor(tier)
    print(
        f"[Info] Tier: {tier or 'unspecified'} → review iteration floor: {floor}",
        file=sys.stderr,
    )

    # Stage 2 — always checked
    if not stage2_required_sections(sprint_id, plan_text):
        passed = False

    # Stage 3 — checked for pre-impl and full gates
    if gate in ("pre-impl", "full"):
        if not stage3_pre_implementation_review(sprint_id, plan_text, floor):
            passed = False

    # Stage 5 — checked for post-impl and full gates only
    if gate in ("post-impl", "full"):
        if not stage5_post_implementation_review(sprint_id, plan_text, floor):
            passed = False

    # Stage 6 (advisory only — never sets passed=False; Documentation per SP_002 swap)
    if gate == "full":
        check_git_progress_updated(project_root)

    if passed:
        print(f"[Result] Gate '{gate}' passed for sprint {sprint_id}.", file=sys.stderr)
        # Write lockfile only when pre-impl gate passes
        if gate == "pre-impl":
            lockfile = project_root / ".pre_impl_passed"
            lockfile.write_text(json.dumps({
                "sprint_id": sprint_id,
                "gate": "pre-impl",
                "passed_at": datetime.now(timezone.utc).isoformat(),
            }))
            print(f"[Info] Lockfile written: {lockfile}", file=sys.stderr)
        return 0

    print(f"[Result] Gate '{gate}' FAILED for sprint {sprint_id}.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
