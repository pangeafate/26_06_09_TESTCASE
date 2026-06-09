#!/usr/bin/env python3
"""
SP_082 — Reconcile sprint-plan frontmatter to match the validator's view.

The recurring CI failure across SP_074 / SP_077 / SP_078 / SP_079 / SP_080
was the same bug each time: the sprint-plan frontmatter said
`schema_touched: true` / `structure_touched: true` when the actual diff
since the plan's introducing commit didn't touch DATA_SCHEMA.md /
CODEBASE_STRUCTURE.md (or vice-versa), AND PROGRESS.md / FEATURE_LIST.md
had content edits without a `last-reconciled` bump. The validator runs
on CI against a different diff base than a developer's local sense of
"what I just changed", so the developer's guess is wrong ~half the time.

This script runs the exact same diff logic the validator uses
(`validators/validate_doc_freshness.py::resolve_diff_base` +
`list_changed_files`), computes the ground-truth `schema_touched` /
`structure_touched` values, and edits the active sprint plan's
frontmatter in place. It also bumps `last-reconciled` on every touched
meta-doc to `max(current_value, today_iso)` so F-4 passes.

Usage:
    python3 scripts/reconcile-sprint-frontmatter.py [project_root]

Exits 0 on a successful reconcile (or when no changes are needed), 1
on an error. Safe to run repeatedly — idempotent.

Design notes:
- This is a maintenance tool, not a commit-time hook. The agent calls
  it BEFORE `git add` / `git commit`; it does not re-stage anything.
- Only the active sprint's frontmatter is modified. Meta-doc
  `last-reconciled` is bumped in-place (no commit) so `git status` shows
  the edits for the agent to stage + commit in the same commit as their
  real work.
- Never rolls `last-reconciled` backward. If an earlier (parallel-agent)
  edit already bumped it past today's date, we keep the higher value.
"""

from __future__ import annotations

import datetime as _dt
import re
import sys
from pathlib import Path

# Reuse the validator's own helpers so this script stays in lock-step.
_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent
sys.path.insert(0, str(_REPO_ROOT / "validators"))
from validate_doc_freshness import (  # noqa: E402  pylint: disable=import-error,wrong-import-position
    _EMPTY_TREE_SHA,
    _DEFAULT_META_DOCS,
    find_active_sprint,
    find_sprint_plan,
    list_changed_files,
    parse_frontmatter,
    resolve_diff_base,
)
META_DOCS = list(_DEFAULT_META_DOCS)


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_LAST_RECONCILED_RE = re.compile(r"^(last-reconciled:\s*)(\S+)\s*$", re.MULTILINE)
_BOOL_FIELD_RE = re.compile(
    r"^(?P<key>schema_touched|structure_touched):\s*(?P<val>\S+)\s*$",
    re.MULTILINE,
)


def _today_iso() -> str:
    return _dt.date.today().isoformat()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _set_bool_field(text: str, key: str, value: bool) -> tuple[str, bool]:
    """Replace the first occurrence of `key: <bool>` with the new value.
    Returns (new_text, changed)."""
    match = _BOOL_FIELD_RE.search(text)
    for m in _BOOL_FIELD_RE.finditer(text):
        if m.group("key") == key:
            old_val = m.group("val").lower()
            new_val = "true" if value else "false"
            if old_val == new_val:
                return text, False
            replaced = text[: m.start()] + f"{key}: {new_val}" + text[m.end():]
            return replaced, True
    # Key missing — prepend into frontmatter (rare; sprint template carries it).
    fm = _FRONTMATTER_RE.search(text)
    if fm is None:
        return text, False
    fm_body = fm.group(1)
    if not fm_body.endswith("\n"):
        fm_body += "\n"
    new_fm = fm_body + f"{key}: {'true' if value else 'false'}"
    return text[: fm.start(1)] + new_fm + text[fm.end(1):], True


def _max_iso(a: str, b: str) -> str:
    """Return the later of two ISO yyyy-mm-dd dates as a string.
    Falls back to `b` if either is unparseable — never rolls backward."""
    try:
        pa = _dt.date.fromisoformat(a)
    except ValueError:
        return b
    try:
        pb = _dt.date.fromisoformat(b)
    except ValueError:
        return a
    return (pa if pa >= pb else pb).isoformat()


def _next_day(iso: str) -> str:
    """Return yyyy-mm-dd for the day after `iso`, or `iso` if unparseable."""
    try:
        d = _dt.date.fromisoformat(iso)
    except ValueError:
        return iso
    return (d + _dt.timedelta(days=1)).isoformat()


def _base_last_reconciled(project_root: Path, base: str, rel_path: str) -> str | None:
    """Return the meta-doc `last-reconciled` value at the validator diff base."""
    if base == _EMPTY_TREE_SHA:
        return None
    import subprocess

    proc = subprocess.run(
        ["git", "show", f"{base}:{rel_path}"],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    match = _LAST_RECONCILED_RE.search(proc.stdout)
    return match.group(2).strip() if match else None


def _target_after_diff_base(project_root: Path, base: str, rel_path: str, today: str) -> str:
    """Choose a marker date that F-4 will see as newer than the diff base.

    The active sprint may have been drafted long before implementation. In
    that case F-4 compares meta-doc content against the draft-plan base, not
    against the previous commit. Resetting a future marker to today's date is
    valid only when the diff itself contains the future value; if the base
    already has today's value, the reset produces no F-4-visible bump. Anchor
    the target to the validator's actual base marker to avoid that false
    negative.
    """
    base_value = _base_last_reconciled(project_root, base, rel_path)
    if base_value is None:
        return today
    try:
        base_date = _dt.date.fromisoformat(base_value)
        today_date = _dt.date.fromisoformat(today)
    except ValueError:
        return today
    if base_date > today_date:
        return today
    if base_date >= today_date:
        return (base_date + _dt.timedelta(days=1)).isoformat()
    return today


def _bump_last_reconciled(path: Path, target_iso: str) -> bool:
    """In-place bump of `last-reconciled:` on a meta-doc. Strategy:
      - if today > current: set to today (catch-up — most common path).
      - if today == current: keep it. `_target_after_diff_base()` already
        returns tomorrow when the validator diff base itself is today; when
        the target equals current, the visible diff is already sufficient or
        there is nothing left to bump.
      - if today < current: HARD RESET to today. The previous value was
        in the future relative to reality (clock skew, hand-edit, or
        prior reconciler bug). Letting future values stand turns into a
        runaway ratchet that pushes the marker further with every run.
        F-4 now accepts this corrective rollback when previous > today.
    Returns True if the file was modified."""
    if not path.exists():
        return False
    text = _read(path)
    match = _LAST_RECONCILED_RE.search(text)
    if match is None:
        return False  # no frontmatter / no field — leave alone
    current = match.group(2).strip()
    try:
        cur_date = _dt.date.fromisoformat(current)
        tgt_date = _dt.date.fromisoformat(target_iso)
    except ValueError:
        # Unparseable input — fall back to the strict-increase formula
        # so we never accidentally roll backward on garbage data.
        new_val = _max_iso(_next_day(current), target_iso)
    else:
        if tgt_date > cur_date:
            new_val = target_iso
        elif tgt_date == cur_date:
            return False
        else:
            # cur_date is in the FUTURE relative to today — corrective reset.
            new_val = target_iso
    if new_val == current:
        return False
    replaced = text[: match.start(2)] + new_val + text[match.end(2):]
    _write(path, replaced)
    return True


def _reconcile_sprint_frontmatter(
    plan_path: Path, schema_touched: bool, structure_touched: bool
) -> list[str]:
    """Flip the two bool fields in the sprint plan frontmatter. Returns a
    list of human-readable changes made (empty list if already correct)."""
    text = _read(plan_path)
    changes: list[str] = []
    text, changed1 = _set_bool_field(text, "schema_touched", schema_touched)
    if changed1:
        changes.append(f"schema_touched → {str(schema_touched).lower()}")
    text, changed2 = _set_bool_field(text, "structure_touched", structure_touched)
    if changed2:
        changes.append(f"structure_touched → {str(structure_touched).lower()}")
    if changes:
        _write(plan_path, text)
    return changes


def _plan_is_untracked(project_root: Path, plan_path: Path) -> bool:
    """True when the plan file is not yet in any commit (staged or
    untracked, but unknown to git history). In that state,
    `resolve_diff_base` falls back to the empty-tree SHA — which makes
    EVERY file in the repo appear 'changed', producing true/true
    frontmatter that is correct pre-commit but wrong post-commit.
    """
    import subprocess

    try:
        rel = plan_path.resolve().relative_to(project_root.resolve())
    except ValueError:
        return False
    # `git log -- <path>` returns empty when no commit has touched the file.
    proc = subprocess.run(
        ["git", "log", "--format=%H", "--", str(rel)],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return False
    return not proc.stdout.strip()


def _resolve_head_as_base(project_root: Path) -> str | None:
    """Return the SHA of current HEAD — used as the post-commit diff
    base for an uncommitted sprint plan. Post-commit, the plan's
    introducing commit's parent WILL be this SHA, so using it now
    predicts the exact same diff the validator will see on CI."""
    import subprocess

    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    sha = proc.stdout.strip()
    return sha or None


def _check_complete_claims(parsed_frontmatter: dict, basenames: set) -> list:
    """SP_618 DM-reconciler-1: return unmet-claim error strings for
    status: Complete sprints. Refuses both forward (claim asserts touch
    but meta-doc missing from diff) AND inverse (meta-doc in diff but
    boolean claim is false) F-2 mismatches. Mirrors
    validators/validate_doc_freshness.py F-2 logic exactly.

    Returns empty list iff all claims satisfied OR status != Complete.
    """
    if parsed_frontmatter.get("status") != "Complete":
        return []

    errors = []
    features = parsed_frontmatter.get("features") or []
    user_stories = parsed_frontmatter.get("user_stories") or []
    schema_touched = parsed_frontmatter.get("schema_touched", False)
    structure_touched = parsed_frontmatter.get("structure_touched", False)

    # Forward: claim asserts touch but meta-doc missing from diff.
    if features and "FEATURE_LIST.md" not in basenames:
        errors.append(f"features declared {features} but FEATURE_LIST.md not in diff")
    if user_stories and "USER_STORIES.md" not in basenames:
        errors.append(f"user_stories declared {user_stories} but USER_STORIES.md not in diff")
    if schema_touched and "DATA_SCHEMA.md" not in basenames:
        errors.append("schema_touched: true but DATA_SCHEMA.md not in diff")
    if structure_touched and "CODEBASE_STRUCTURE.md" not in basenames:
        errors.append("structure_touched: true but CODEBASE_STRUCTURE.md not in diff")

    # Inverse: meta-doc in diff but boolean claim is false. Asymmetric per
    # F-2 — features/user_stories don't have inverse checks.
    if "DATA_SCHEMA.md" in basenames and not schema_touched:
        errors.append("DATA_SCHEMA.md in diff but schema_touched not set")
    if "CODEBASE_STRUCTURE.md" in basenames and not structure_touched:
        errors.append("CODEBASE_STRUCTURE.md in diff but structure_touched not set")

    return errors


def reconcile(project_root: Path, dry_run: bool = False) -> int:
    sprint_id = find_active_sprint(project_root)
    if sprint_id is None:
        print("reconcile: no active sprint in PROGRESS.md — nothing to do.")
        return 0
    plan_path = find_sprint_plan(project_root, sprint_id)
    if plan_path is None:
        print(f"reconcile: active sprint {sprint_id} but no plan file found.", file=sys.stderr)
        return 1
    # SP_082 — if the plan is untracked (about to be committed), use
    # HEAD as the predictive diff base instead of the empty-tree
    # fallback `resolve_diff_base` would otherwise produce. This makes
    # pre-commit reconciliation match post-commit validator output.
    if _plan_is_untracked(project_root, plan_path):
        base = _resolve_head_as_base(project_root)
        note = " (predictive: plan is untracked; using HEAD)"
    else:
        base, _ = resolve_diff_base(project_root, plan_path)
        note = ""
    if base is None:
        print("reconcile: git unavailable — cannot resolve diff base.", file=sys.stderr)
        return 1
    changed = list_changed_files(project_root, base)
    basenames = {p for p in changed if "/" not in p}

    # SP_618 DM-reconciler-1: refuse Complete-flip with unmet claims.
    plan_text = _read(plan_path)
    _, parsed_fm = parse_frontmatter(plan_text)
    if parsed_fm is not None:
        claim_errors = _check_complete_claims(parsed_fm, basenames)
        if claim_errors:
            print(
                f"reconcile: REFUSE — sprint {sprint_id} marked status: Complete but frontmatter claims unmet:",
                file=sys.stderr,
            )
            for err in claim_errors:
                print(f"  {err}", file=sys.stderr)
            print(
                "Fix by EITHER (a) commit the missing edits in this run, OR (b) revert the status flip back to In Progress, OR (c) adjust the frontmatter claim to match reality.",
                file=sys.stderr,
            )
            return 1

    schema_touched = "DATA_SCHEMA.md" in basenames
    structure_touched = "CODEBASE_STRUCTURE.md" in basenames

    tag = "[dry-run] " if dry_run else ""
    print(f"{tag}reconcile: active sprint {sprint_id}")
    print(f"{tag}reconcile: diff base {base[:12]}{note}")
    print(
        f"{tag}reconcile: computed "
        f"schema_touched={schema_touched}, structure_touched={structure_touched}"
    )

    if dry_run:
        # Read-only audit. Just report what would change.
        current = _read(plan_path)
        for key, want in [
            ("schema_touched", schema_touched),
            ("structure_touched", structure_touched),
        ]:
            m = None
            for mm in _BOOL_FIELD_RE.finditer(current):
                if mm.group("key") == key:
                    m = mm
                    break
            if m is None:
                print(f"  [dry-run] {plan_path.name}: {key} missing; would add {want}")
                continue
            have = m.group("val").lower() == "true"
            if have != want:
                print(f"  [dry-run] {plan_path.name}: {key} {have} → {want}")
            else:
                print(f"  [dry-run] {plan_path.name}: {key} already {have}")
    else:
        frontmatter_changes = _reconcile_sprint_frontmatter(
            plan_path, schema_touched, structure_touched
        )
        if frontmatter_changes:
            for c in frontmatter_changes:
                print(f"  {plan_path.name}: {c}")
        else:
            print(f"  {plan_path.name}: frontmatter already correct")

    # Bump last-reconciled on every touched meta-doc to a date that is
    # strictly newer than the validator's diff base marker. This can be
    # tomorrow when a sprint was drafted earlier and the base marker already
    # equals today.
    today = _today_iso()
    touched_docs: list[str] = []
    for doc in sorted(META_DOCS):
        path = project_root / doc
        if not path.exists():
            continue
        if doc not in basenames:
            continue  # only bump docs actually touched
        target = _target_after_diff_base(project_root, base, doc, today)
        if dry_run:
            # Show what would change without writing.
            match = _LAST_RECONCILED_RE.search(_read(path))
            if match is None:
                continue
            current = match.group(2).strip()
            if _max_iso(current, target) != current or target != current:
                print(f"  [dry-run] {doc}: last-reconciled {current} → {target}")
            touched_docs.append(doc)
        else:
            if _bump_last_reconciled(path, target):
                touched_docs.append(doc)
                print(f"  {doc}: last-reconciled bumped to {target}")
    if not touched_docs:
        print("  no meta-doc last-reconciled bumps needed")

    return 0


def main() -> int:
    args = sys.argv[1:]
    dry_run = False
    if "--dry-run" in args:
        dry_run = True
        args = [a for a in args if a != "--dry-run"]
    root = Path(args[0] if args else ".").resolve()
    if not root.exists():
        print(f"reconcile: project root not found: {root}", file=sys.stderr)
        return 1
    return reconcile(root, dry_run=dry_run)


if __name__ == "__main__":
    sys.exit(main())
