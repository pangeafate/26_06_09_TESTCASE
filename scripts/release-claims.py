#!/usr/bin/env python3
"""
SP_205 — Release IMPLEMENTATION_CHECKLIST claims when a sprint completes.

Walks `workspace/sprints/SP_*.md`, finds plans with `status: Complete`
+ `touches_checklist_items: [...]` frontmatter, and removes the matching
` (owner: SP_NNN)` end-of-line suffixes from `IMPLEMENTATION_CHECKLIST.md`.

Suffix format (anchored regex; SP_205 Stage-2 HIGH-2 spec, SP_209
Stage-5 MEDIUM-2 widened from `\\d{3}` to `\\d{3,}`):
    r' \\(owner: SP_(\\d{3,})\\)$'
- Single ASCII space before `(`
- Capital `SP_` + 3 or more digits (handles SP_1000+)
- Position: end of line, no trailing whitespace
- Single suffix per line; nested suffixes not supported
- Other parenthetical content elsewhere on the line is unaffected
  (anchor is end-of-line)

Idempotent — running it twice with no new Complete sprints is a no-op.

Usage:
    python3 scripts/release-claims.py [project_root]

Exit codes:
    0 — success (claims released or already clean)
    2 — usage error
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# SP_209 — frontmatter parsing extracted to shared helper to satisfy
# Rule 18.7 ("defer specialization until you see three" — pre-commit
# hook is the third consumer).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "validators"))
from _sprint_frontmatter import read_active_claims  # noqa: E402

# Stage-5 MEDIUM-2 fix: \d{3,} (3+ digits) so SP_1000+ is matched.
OWNER_SUFFIX_RE = re.compile(r" \(owner: SP_(\d{3,})\)$")


def find_completed_sprint_numbers(project_root: Path) -> set[int]:
    """Return set of SP_NNN integers for plans with status: Complete."""
    out: set[int] = set()
    # Stage-5 HIGH-2 fix: warn-and-skip malformed plans so a single
    # archived bad-YAML file doesn't crash the release script.
    claims = read_active_claims(
        project_root,
        statuses=("Complete",),
        on_parse_error="warn",
    )
    for claim in claims:
        m = re.match(r"SP_(\d{3,})$", claim.sprint_id)
        if m:
            out.add(int(m.group(1)))
    return out


def release(project_root: Path) -> int:
    completed = find_completed_sprint_numbers(project_root)
    checklist = project_root / "IMPLEMENTATION_CHECKLIST.md"
    if not checklist.is_file():
        print(f"NOTE: {checklist} not found; nothing to release.")
        return 0
    if not completed:
        print("NOTE: no Complete sprints found; nothing to release.")
        return 0

    # Stage-5 H-1 fix: use splitlines(keepends=True) so trailing-newline
    # semantics (including double-newline blocks) are preserved exactly.
    # Idempotency depends on byte-for-byte equality on second runs.
    text = checklist.read_text(encoding="utf-8")
    removed = 0
    new_lines: list[str] = []
    for line in text.splitlines(keepends=True):
        # Suffix regex requires end-of-line anchor against the line's content
        # (excluding trailing newline). Strip newline for matching, re-attach
        # the same line-ending after substitution.
        if line.endswith("\r\n"):
            ending = "\r\n"
            content = line[:-2]
        elif line.endswith("\n"):
            ending = "\n"
            content = line[:-1]
        else:
            ending = ""
            content = line
        m = OWNER_SUFFIX_RE.search(content)
        if m and int(m.group(1)) in completed:
            new_lines.append(OWNER_SUFFIX_RE.sub("", content) + ending)
            removed += 1
        else:
            new_lines.append(line)

    if removed > 0:
        checklist.write_text("".join(new_lines), encoding="utf-8")
    print(f"release-claims: {removed} claim suffix(es) removed for {len(completed)} Complete sprint(s).")
    return 0


if __name__ == "__main__":
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    if not root.is_dir():
        print(f"usage error: {root} is not a directory", file=sys.stderr)
        sys.exit(2)
    sys.exit(release(root))
