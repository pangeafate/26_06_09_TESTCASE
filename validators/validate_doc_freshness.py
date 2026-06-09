#!/usr/bin/env python3
"""
validate_doc_freshness.py — Diff-aware documentation freshness gate.

Four stages:
    F-1 — Sprint-plan frontmatter presence + opt-in gate.
    F-2 — Frontmatter claims match the sprint's git diff (forward + inverse).
    F-3 — Proportionality: code changes require meta-doc changes.
    F-4 — `last-reconciled` was bumped to a valid date on every touched meta-doc.

Writes .docs_reconciled lockfile on full pass by default; --no-lockfile
suppresses the write (for CI dry-runs).

Usage:
    python validate_doc_freshness.py <project_root> [--skip-stage F1,F2,F3,F4] [--no-lockfile]

Exit codes:
    0 — all enforced stages pass
    1 — one or more stages failed
"""
from __future__ import annotations

import argparse
import datetime as _dt
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml  # type: ignore
    _HAS_YAML = True
except ImportError:  # pragma: no cover
    _HAS_YAML = False


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_SOURCE_ROOTS = ["src", "skills", "validators"]
_DEFAULT_META_DOCS = [
    "PROGRESS.md",
    "FEATURE_LIST.md",
    "PROJECT_ROADMAP.md",
    "ARCHITECTURE.md",
    "DATA_SCHEMA.md",
    "CODEBASE_STRUCTURE.md",
    "USER_STORIES.md",
]
_DEFAULT_EXEMPT_PATHS = ["**/test_*.py", "**/*.test.ts", "**/fixtures/**"]

_LOCKFILE_NAME = ".docs_reconciled"
_LOCKFILE_SCHEMA_VERSION = 1

_EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

_FRONTMATTER_MAX_LINES = 50
_ACCEPTED_SPRINT_STATUS = {"Planning", "In Progress", "Complete", "Abandoned"}

_SPRINT_NUM_RE = re.compile(r"SP_(\d+)")
_LAST_RECONCILED_DIFF_RE = re.compile(r"^([+-])\s*last-reconciled:\s*(\S+)")

# SP_719 — the previously-duplicated `_ACTIVE_SPRINT_RE` + first-match
# `find_active_sprint` (broken under parallel agents) is now the single
# multi-agent-robust resolver in validators/_common.py (the extraction
# the old SP_003 note designated). Imported here as a drop-in (signature
# identical). validators run as `python validators/<f>.py <root>` so the
# script dir is sys.path[0] → this resolves.
from _common import find_active_sprint  # noqa: E402  pylint: disable=wrong-import-position
from _diff_scope import scope_gate  # noqa: E402  pylint: disable=wrong-import-position


def find_sprint_plan(project_root: Path, sprint_id: str) -> Path | None:
    """Locate sprint plan file by sprint_id in conventional locations."""
    search_dirs = [
        project_root / "workspace" / "sprints",
        project_root / "00_IMPLEMENTATION" / "SPRINTS",
    ]
    for sprints_dir in search_dirs:
        if not sprints_dir.exists():
            continue
        exact = sprints_dir / f"{sprint_id}.md"
        if exact.exists():
            return exact
        matches = list(sprints_dir.glob(f"{sprint_id}_*.md"))
        if len(matches) >= 1:
            return matches[0]
        subfolder = sprints_dir / sprint_id
        if subfolder.is_dir():
            exact_sub = subfolder / f"{sprint_id}.md"
            if exact_sub.exists():
                return exact_sub
            sub_matches = list(subfolder.glob(f"{sprint_id}_*.md"))
            if sub_matches:
                return sub_matches[0]
    return None


def parse_frontmatter(text: str) -> tuple[str, dict | None]:
    """Return (state, dict|None). state ∈ {'missing','malformed','present'}."""
    if not text.startswith("---\n") and not text.startswith("---\r\n") and text != "---":
        return "missing", None
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return "missing", None
    closing_idx = None
    for idx in range(1, min(len(lines), _FRONTMATTER_MAX_LINES + 1)):
        if lines[idx].strip() == "---":
            closing_idx = idx
            break
    if closing_idx is None:
        return "malformed", None
    body = "\n".join(lines[1:closing_idx])
    if _HAS_YAML:
        try:
            loaded = yaml.safe_load(body)
            parsed = loaded if isinstance(loaded, dict) else {}
        except Exception:
            return "malformed", None
    else:
        parsed = _minimal_yaml_parse(body)
    return "present", parsed


def _minimal_yaml_parse(body: str) -> dict:
    result: dict = {}
    for line in body.splitlines():
        line = line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, raw = line.partition(":")
        key = key.strip()
        val = raw.strip()
        if not key:
            continue
        if val.startswith("[") and val.endswith("]"):
            items = [
                item.strip().strip("'\"")
                for item in val[1:-1].split(",")
                if item.strip()
            ]
            result[key] = items
        elif val.startswith("'") and val.endswith("'"):
            result[key] = val[1:-1]
        elif val.startswith('"') and val.endswith('"'):
            result[key] = val[1:-1]
        else:
            result[key] = val
    return result


def load_config(project_root: Path) -> dict:
    """Load .validators.yml `doc_freshness:` block.

    CRITICAL: substitute `doc_freshness` for `doc_reality` — this function is
    a sibling of validate_doc_reality.py's load_config(), not a copy-paste.
    """
    path = project_root / ".validators.yml"
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return {}
    if _HAS_YAML:
        try:
            data = yaml.safe_load(text) or {}
        except Exception:
            return {}
    else:
        try:
            data = _fallback_parse_validators_yml(text)
        except Exception:
            return {}
    if not isinstance(data, dict):
        return {}
    block = data.get("doc_freshness")
    return block if isinstance(block, dict) else {}


def _fallback_parse_validators_yml(text: str) -> dict:
    """Limited YAML subset parser. See validate_doc_reality.py for full spec."""
    result: dict = {}
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.startswith(" ") and line.rstrip().endswith(":"):
            section_key = line.rstrip().rstrip(":").strip()
            section: dict = {}
            i += 1
            while i < len(lines) and lines[i].startswith(" "):
                sub = lines[i]
                stripped = sub.strip()
                if ":" in stripped and not stripped.startswith("-"):
                    key, _, rhs = stripped.partition(":")
                    key = key.strip()
                    rhs = rhs.strip()
                    if not rhs:
                        items: list = []
                        i += 1
                        while i < len(lines) and lines[i].lstrip().startswith("-"):
                            item_line = lines[i].lstrip()[1:].strip()
                            items.append(_parse_scalar_or_flow(item_line))
                            i += 1
                        section[key] = items
                        continue
                    section[key] = _parse_scalar_or_flow(rhs)
                i += 1
            result[section_key] = section
            continue
        if ":" in line:
            key, _, rhs = line.partition(":")
            result[key.strip()] = _parse_scalar_or_flow(rhs.strip())
        i += 1
    return result


def _parse_scalar_or_flow(raw: str):
    if raw == "":
        return ""
    if raw.startswith("[") and raw.endswith("]"):
        body = raw[1:-1].strip()
        if not body:
            return []
        return [_parse_scalar_or_flow(part.strip()) for part in body.split(",")]
    if raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1]
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    try:
        return int(raw)
    except ValueError:
        return raw


def _coerce_bool(value) -> bool | None:
    """Accept Python bool OR case-insensitive 'true'/'false' string; else None."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.lower() == "true":
            return True
        if value.lower() == "false":
            return False
    return None


# ---------------------------------------------------------------------------
# Git interaction
# ---------------------------------------------------------------------------


def _git(project_root: Path, *args: str) -> tuple[int, str, str]:
    """Run a git command; return (rc, stdout, stderr). Never raises."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 127, "", "git unavailable"
    return result.returncode, result.stdout, result.stderr


def git_available(project_root: Path) -> bool:
    rc, _, _ = _git(project_root, "rev-parse", "HEAD")
    return rc == 0


def resolve_diff_base(project_root: Path, sprint_plan: Path) -> tuple[str | None, str | None]:
    """Return (base_commit, sprint_start_date_iso).

    Strategy: parent of the commit that introduced the sprint plan. Empty-tree
    SHA fallback for "no commits yet" / "plan in initial commit".
    """
    if not git_available(project_root):
        return None, None
    try:
        rel = sprint_plan.resolve().relative_to(project_root.resolve())
    except ValueError:
        return None, None
    rc, stdout, _ = _git(project_root, "log", "--format=%H", "--", str(rel))
    commits = [c.strip() for c in stdout.splitlines() if c.strip()] if rc == 0 else []
    if not commits:
        return _EMPTY_TREE_SHA, _dt.date.today().isoformat()
    introducing = commits[-1]
    rc_p, parent_out, _ = _git(project_root, "rev-parse", f"{introducing}^")
    base = parent_out.strip() if rc_p == 0 else _EMPTY_TREE_SHA
    rc_d, date_out, _ = _git(project_root, "log", "-1", "--format=%cs", introducing)
    sprint_start = date_out.strip() if rc_d == 0 and date_out.strip() else _dt.date.today().isoformat()
    return base, sprint_start


def list_changed_files(project_root: Path, base: str) -> set[str]:
    """Union of committed delta (base...HEAD three-dot) + working-tree delta
    from porcelain. Returns POSIX-normalized project-root-relative paths."""
    paths: set[str] = set()

    # Committed delta: three-dot to exclude merged-from-main changes.
    # Exception: empty-tree base has no merge-base with HEAD, so use two-dot
    # (which means "diff from empty-tree to HEAD" = "all files at HEAD").
    diff_range = f"{base} HEAD" if base == _EMPTY_TREE_SHA else f"{base}...HEAD"
    rc, stdout, _ = _git(
        project_root, "diff", "--name-status", *diff_range.split()
    )
    if rc == 0:
        for line in stdout.splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            status = parts[0]
            if status.startswith("R") or status.startswith("C"):
                if len(parts) >= 3:
                    paths.add(parts[1].strip())  # old path (conservative)
                    paths.add(parts[2].strip())  # new path
            else:
                if len(parts) >= 2:
                    paths.add(parts[1].strip())

    # Working-tree delta via porcelain (staged + unstaged + untracked).
    # --untracked-files=all ensures untracked files in new directories are listed
    # individually, not collapsed to the parent directory.
    rc_p, porcelain, _ = _git(
        project_root, "status", "--porcelain", "--untracked-files=all"
    )
    if rc_p == 0:
        for line in porcelain.splitlines():
            if len(line) < 3:
                continue
            xy = line[:2]
            rest = line[3:]
            if xy == "??":
                paths.add(rest.strip())
                continue
            # Renames in porcelain appear as "R  old -> new" or "RM old -> new".
            if "->" in rest:
                old, _, new = rest.partition("->")
                paths.add(old.strip())
                paths.add(new.strip())
            else:
                paths.add(rest.strip())

    return {p for p in paths if p}


def _file_diff_union(project_root: Path, base: str, path: str) -> str:
    """Concatenated diff output for a specific file: committed + working tree."""
    if base == _EMPTY_TREE_SHA:
        _, committed, _ = _git(project_root, "diff", base, "HEAD", "--", path)
    else:
        _, committed, _ = _git(project_root, "diff", f"{base}...HEAD", "--", path)
    _, worktree, _ = _git(project_root, "diff", "HEAD", "--", path)
    return (committed or "") + "\n" + (worktree or "")


def _file_is_added(project_root: Path, base: str, path: str) -> bool:
    """True if the file is A (added) in the committed diff range."""
    if base == _EMPTY_TREE_SHA:
        _, stdout, _ = _git(
            project_root, "diff", "--name-status", base, "HEAD", "--", path
        )
    else:
        _, stdout, _ = _git(
            project_root, "diff", "--name-status", f"{base}...HEAD", "--", path
        )
    for line in stdout.splitlines():
        if line.strip() and line.split("\t")[0].strip() == "A":
            return True
    # Also check porcelain for new files in working tree.
    _, porcelain, _ = _git(project_root, "status", "--porcelain", "--", path)
    for line in porcelain.splitlines():
        if line.startswith("A ") or line.startswith("?? "):
            return True
    return False


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------


def stage_f1(project_root: Path, cfg: dict) -> tuple[bool, dict | None, str | None]:
    """Returns (passed, parsed_frontmatter, sprint_plan_path_str).

    parsed_frontmatter is None if the stage could not get that far.
    """
    enabled = cfg.get("enabled", False)
    enabled_bool = _coerce_bool(enabled) if not isinstance(enabled, bool) else enabled
    if enabled_bool is not True:
        print(
            "[Stage F-1] ADVISORY: doc_freshness disabled; opt in by setting "
            "doc_freshness.enabled: true in .validators.yml. Skipping all stages.",
            file=sys.stderr,
        )
        return True, None, None

    sprint_id = find_active_sprint(project_root)
    if sprint_id is None:
        print(
            "[Stage F-1] ADVISORY: No active sprint in PROGRESS.md; skipping.",
            file=sys.stderr,
        )
        return True, None, None

    # Scope the doc-freshness gate to the actually deploying sprint
    # (symmetric with validate_sprint.py). Advisory mode means CI asserted
    # this deploy is code-free; every other path is fail-closed enforce.
    scoped_id, gate_mode = scope_gate(project_root, sprint_id)
    if gate_mode == "advisory":
        print(
            "[Stage F-1] ADVISORY: deploy is provably code-free "
            "(DEV_DEPLOY_CODE_CHANGED=false); skipping doc-freshness gate "
            f"for resolver-resolved '{sprint_id}'.",
            file=sys.stderr,
        )
        return True, None, None
    gate_rescoped = scoped_id is not None and scoped_id != sprint_id
    if gate_rescoped:
        print(
            f"[Stage F-1] [SP_736] Gate scoped from resolver '{sprint_id}' "
            f"to deploying sprint '{scoped_id}' (touches_paths ∩ code-set).",
            file=sys.stderr,
        )
        sprint_id = scoped_id

    plan_path = find_sprint_plan(project_root, sprint_id)
    if plan_path is None:
        print(
            f"[Stage F-1] FAIL: Sprint plan not found for '{sprint_id}'.",
            file=sys.stderr,
        )
        return False, None, None

    try:
        text = plan_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"[Stage F-1] FAIL: could not read {plan_path}: {exc}", file=sys.stderr)
        return False, None, None

    state, parsed = parse_frontmatter(text)
    if state != "present" or not parsed:
        print(
            f"[Stage F-1] FAIL: {plan_path.name} frontmatter {state} "
            "(expected opening `---` at byte 0 and closing `---` within 50 lines).",
            file=sys.stderr,
        )
        return False, None, None

    # When the gate was rescoped from the resolver's
    # active sprint to a co-claiming sibling, that sibling's plan-to-HEAD
    # diff base structurally conflates PARALLEL agents' meta-doc edits
    # (DATA_SCHEMA.md / CODEBASE_STRUCTURE.md) with the sibling's own
    # claims on a busy linear main — the documented multi-agent
    # fleet-freeze. F-2's inverse-drift checks are downgraded to ADVISORY
    # in that case (forward-claim checks stay ENFORCE; they cannot
    # false-positive from parallel collateral).
    parsed["_gate_rescoped"] = gate_rescoped

    failures: list[str] = []
    required = ("sprint_id", "features", "user_stories", "schema_touched", "structure_touched", "status")
    for key in required:
        if key not in parsed:
            failures.append(f"missing required key '{key}'")

    if "sprint_id" in parsed:
        sid = str(parsed["sprint_id"])
        num_match = _SPRINT_NUM_RE.match(sid)
        active_num = _SPRINT_NUM_RE.match(sprint_id)
        if num_match and active_num and num_match.group(1) != active_num.group(1):
            failures.append(
                f"sprint_id '{sid}' numeric prefix differs from active sprint '{sprint_id}'"
            )

    if "features" in parsed and not isinstance(parsed["features"], list):
        failures.append("'features' must be a list")
    if "user_stories" in parsed and not isinstance(parsed["user_stories"], list):
        failures.append("'user_stories' must be a list")

    for bool_key in ("schema_touched", "structure_touched"):
        if bool_key in parsed:
            coerced = _coerce_bool(parsed[bool_key])
            if coerced is None:
                failures.append(f"'{bool_key}' is not a bool or 'true'/'false' string")
                parsed[bool_key] = False  # safe default so F-2 isn't corrupted
            else:
                parsed[bool_key] = coerced  # normalize for Stage F-2

    if "status" in parsed:
        if str(parsed["status"]) not in _ACCEPTED_SPRINT_STATUS:
            failures.append(
                f"'status' = {parsed['status']!r} not in {sorted(_ACCEPTED_SPRINT_STATUS)}"
            )

    if failures:
        for f in failures:
            print(f"[Stage F-1] FAIL: {plan_path.name} — {f}", file=sys.stderr)
        return False, parsed, str(plan_path)

    print(f"[Stage F-1] PASS", file=sys.stderr)
    return True, parsed, str(plan_path)


def stage_f2(
    parsed: dict | None,
    changed_files: set[str] | None,
) -> bool:
    if parsed is None:
        print("[Stage F-2] ADVISORY: depends on F-1; skipping.", file=sys.stderr)
        return True
    if changed_files is None:
        print("[Stage F-2] ADVISORY: git unavailable; skipping.", file=sys.stderr)
        return True
    features = parsed.get("features") or []
    user_stories = parsed.get("user_stories") or []
    schema_touched = bool(parsed.get("schema_touched") or False)
    structure_touched = bool(parsed.get("structure_touched") or False)
    has_positive_claims = bool(features or user_stories or schema_touched or structure_touched)

    if not changed_files:
        if has_positive_claims:
            print(
                "[Stage F-2] FAIL: empty diff but sprint plan declares positive claims "
                f"(features={features}, user_stories={user_stories}, "
                f"schema_touched={schema_touched}, structure_touched={structure_touched}). "
                "Either commit the work or remove the unfulfilled claims.",
                file=sys.stderr,
            )
            return False
        print("[Stage F-2] ADVISORY: empty diff; skipping.", file=sys.stderr)
        return True

    failures: list[str] = []
    # Meta-docs are recognized ONLY at project root (path has no parent dir).
    # A "templates/DATA_SCHEMA.md" basename does not count as a meta-doc match.
    basenames = {p for p in changed_files if "/" not in p}

    if features and "FEATURE_LIST.md" not in basenames:
        failures.append(
            f"features declared {features} but FEATURE_LIST.md not in diff"
        )
    if user_stories and "USER_STORIES.md" not in basenames:
        failures.append(
            f"user_stories declared {user_stories} but USER_STORIES.md not in diff"
        )
    if schema_touched and "DATA_SCHEMA.md" not in basenames:
        failures.append("schema_touched: true but DATA_SCHEMA.md not in diff")
    if structure_touched and "CODEBASE_STRUCTURE.md" not in basenames:
        failures.append("structure_touched: true but CODEBASE_STRUCTURE.md not in diff")

    # Inverse checks (silent-drift prevention) are ADVISORY-only.
    #
    # On this project's shared linear main, dozens of agents commit in
    # parallel. Any sprint's diff range (parent-of-plan-introducing-commit
    # ...HEAD) therefore accumulates OTHER agents' DATA_SCHEMA.md /
    # CODEBASE_STRUCTURE.md commits. The raw-range inverse check ("doc in
    # range but declared false") cannot distinguish the active sprint's
    # own meta-doc edits from parallel collateral, so it false-fires for
    # essentially every non-trivial-age sprint and hard-freezes EVERY
    # fleet deploy — the documented multi-agent fleet-freeze class
    # (PROGRESS.md 2026-05-19; first narrowed to the SP_736 rescoped
    # path, now generalized after that proved non-convergent: the
    # non-rescoped active-sprint path has the identical conflation).
    #
    # The project's DESIGNATED authority for "what did THIS sprint
    # actually touch" is scripts/reconcile-sprint-frontmatter.py, run
    # mandatorily at Stage 6 (CLAUDE.md Rule 16); it sets
    # schema_touched / structure_touched from the sprint's attributable
    # contribution and auto-syncs genuine drift. Re-deriving drift here
    # from the polluted raw range second-guesses that authority with
    # strictly worse information. Inverse drift is therefore ADVISORY;
    # the FORWARD checks above stay ENFORCE — "declared true but doc
    # absent" cannot false-positive from parallel collateral and still
    # catches a sprint over-claiming work it did not deliver.
    if "DATA_SCHEMA.md" in basenames and not schema_touched:
        print(
            "[Stage F-2] ADVISORY (parallel meta-doc collateral; reconcile-"
            "sprint-frontmatter.py is authoritative per Rule 16): "
            "DATA_SCHEMA.md in range but schema_touched: false.",
            file=sys.stderr,
        )
    if "CODEBASE_STRUCTURE.md" in basenames and not structure_touched:
        print(
            "[Stage F-2] ADVISORY (parallel meta-doc collateral; reconcile-"
            "sprint-frontmatter.py is authoritative per Rule 16): "
            "CODEBASE_STRUCTURE.md in range but structure_touched: false.",
            file=sys.stderr,
        )

    if failures:
        for f in failures:
            print(f"[Stage F-2] FAIL: {f}", file=sys.stderr)
        return False
    print("[Stage F-2] PASS", file=sys.stderr)
    return True


def _classify(
    path: str,
    source_roots: list[str],
    meta_docs: list[str],
    exempt_paths: list[str],
) -> str:
    """Classification priority: meta_doc > exempt > source > other.

    Meta-docs are recognized ONLY at project root (no parent directory).
    A templates/ copy of a meta-doc is NOT a meta-doc for this purpose.
    """
    if "/" not in path and path in meta_docs:
        return "meta_doc"
    for glob in exempt_paths:
        if fnmatch.fnmatch(path, glob):
            return "exempt"
    parts = Path(path).parts
    if parts and parts[0] in source_roots:
        return "source"
    return "other"


def stage_f3(
    changed_files: set[str] | None,
    source_roots: list[str],
    meta_docs: list[str],
    exempt_paths: list[str],
) -> bool:
    if changed_files is None:
        print("[Stage F-3] ADVISORY: git unavailable; skipping.", file=sys.stderr)
        return True
    if not changed_files:
        print("[Stage F-3] ADVISORY: empty diff; skipping.", file=sys.stderr)
        return True
    source_count = 0
    meta_count = 0
    for path in changed_files:
        kind = _classify(path, source_roots, meta_docs, exempt_paths)
        if kind == "source":
            source_count += 1
        elif kind == "meta_doc":
            meta_count += 1
    if source_count > 0 and meta_count == 0:
        print(
            f"[Stage F-3] FAIL: {source_count} source file(s) changed but no meta-doc "
            f"was touched. Update at least one of: {', '.join(meta_docs)}.",
            file=sys.stderr,
        )
        return False
    print("[Stage F-3] PASS", file=sys.stderr)
    return True


def stage_f4(
    project_root: Path,
    base: str | None,
    sprint_start: str | None,
    changed_files: set[str] | None,
    meta_docs: list[str],
    parsed: dict | None = None,
) -> bool:
    if changed_files is None or base is None:
        print("[Stage F-4] ADVISORY: git unavailable; skipping.", file=sys.stderr)
        return True

    # Same parallel-collateral rationale as F-2's inverse drift: on a
    # shared linear main, DATA_SCHEMA.md / CODEBASE_STRUCTURE.md changes
    # in the range are usually OTHER agents' commits. When the sprint's
    # reconcile-synced frontmatter declares it did NOT touch them
    # (schema_touched / structure_touched false), demanding THIS sprint
    # bump their last-reconciled is the same fleet-freeze — so the
    # missing-bump check is ADVISORY for those two docs in that case.
    # reconcile-sprint-frontmatter.py (Rule 16) remains authoritative.
    _collateral_advisory: set[str] = set()
    if parsed is not None:
        if not bool(parsed.get("schema_touched") or False):
            _collateral_advisory.add("DATA_SCHEMA.md")
        if not bool(parsed.get("structure_touched") or False):
            _collateral_advisory.add("CODEBASE_STRUCTURE.md")

    start_date: _dt.date | None = None
    if sprint_start:
        try:
            start_date = _dt.date.fromisoformat(sprint_start)
        except ValueError:
            start_date = None

    failures: list[str] = []
    for path in sorted(changed_files):
        # Meta-docs are recognized only at project root.
        if "/" in path or path not in meta_docs:
            continue
        diff_text = _file_diff_union(project_root, base, path)
        is_added = _file_is_added(project_root, base, path)

        plus_date: str | None = None
        minus_date: str | None = None
        for raw_line in diff_text.splitlines():
            line = raw_line.rstrip("\r")
            m = _LAST_RECONCILED_DIFF_RE.match(line)
            if not m:
                continue
            marker, date_val = m.group(1), m.group(2)
            if marker == "-":
                minus_date = date_val
            elif marker == "+":
                plus_date = date_val

        if plus_date is None:
            if path in _collateral_advisory:
                print(
                    f"[Stage F-4] ADVISORY (parallel meta-doc collateral; "
                    f"reconcile-sprint-frontmatter.py authoritative per Rule 16): "
                    f"{path} changed in range but sprint declares it untouched; "
                    f"not demanding a last-reconciled bump.",
                    file=sys.stderr,
                )
                continue
            if is_added:
                failures.append(
                    f"{path}: file added but frontmatter has no `last-reconciled:` line"
                )
            else:
                failures.append(
                    f"{path}: `last-reconciled` not bumped; content changed but "
                    "the freshness marker did not"
                )
            continue
        # NB: `not is_added and minus_date is None` is LEGITIMATE — it means
        # frontmatter was added to a previously-unfrontmattered meta-doc.
        # This is the migration path for projects adopting the convention.
        # We accept the `+last-reconciled:` line as a valid bump.

        # Closing the same-date loophole: a `-` and `+` line with identical
        # values means the value didn't actually change.
        if minus_date is not None and plus_date == minus_date:
            failures.append(
                f"{path}: `last-reconciled` unchanged ({plus_date}); value must increase"
            )
            continue

        try:
            new_date = _dt.date.fromisoformat(plus_date)
        except ValueError:
            failures.append(
                f"{path}: `last-reconciled` = {plus_date!r} is not ISO-8601"
            )
            continue
        if start_date and new_date < start_date:
            failures.append(
                f"{path}: `last-reconciled` bumped backwards ({new_date} < sprint start {start_date})"
            )
            continue
        # Within-sprint rollback: bump-from-newer-to-older.
        # EXCEPTION: rollback is permitted when the previous value was
        # ALREADY in the future relative to today. This is the corrective
        # reset path for the runaway-ratchet bug where a future-dated
        # marker (clock skew, hand-edit, prior reconciler defect) would
        # otherwise be locked in forever by F-4's strict-increase rule.
        # The reset is bounded: new_date must still be >= today (so we
        # cannot rollback to ancient past, only correct a future overshoot
        # back to today or near-today).
        today = _dt.date.today()
        if minus_date is not None:
            try:
                old_date = _dt.date.fromisoformat(minus_date)
                if new_date < old_date:
                    if old_date > today and new_date >= today:
                        pass  # corrective reset of future-dated marker — accepted
                    else:
                        failures.append(
                            f"{path}: `last-reconciled` rolled back within sprint "
                            f"({new_date} < previous {old_date})"
                        )
            except ValueError:
                pass  # malformed previous value; let the new value's validation suffice

    if failures:
        for f in failures:
            print(f"[Stage F-4] FAIL: {f}", file=sys.stderr)
        return False
    print("[Stage F-4] PASS", file=sys.stderr)
    return True


# ---------------------------------------------------------------------------
# Lockfile
# ---------------------------------------------------------------------------


def write_lockfile(
    project_root: Path,
    sprint_id: str,
    stages_checked: list[str],
    git_base: str | None,
) -> Path:
    """Atomic lockfile write. Uses a unique tempname per process to avoid races
    between concurrent run_all.py invocations. Refuses to overwrite a symlink."""
    import tempfile

    num = _SPRINT_NUM_RE.match(sprint_id)
    sprint_num = int(num.group(1)) if num else None
    payload = {
        "schema_version": _LOCKFILE_SCHEMA_VERSION,
        "sprint_id": sprint_id,
        "sprint_num": sprint_num,
        "passed_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stages_checked": stages_checked,
        "git_base": git_base or "",
    }
    final = project_root / _LOCKFILE_NAME
    if final.is_symlink():
        # Refuse to follow a symlink — could redirect writes outside the project.
        raise OSError(f"{_LOCKFILE_NAME} exists as a symlink; refusing to overwrite for safety")
    body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    fd, tmp_path = tempfile.mkstemp(
        prefix=f"{_LOCKFILE_NAME}.", suffix=".tmp", dir=str(project_root)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, final)
    except Exception:
        # Best-effort cleanup of the tempfile if something went wrong.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return final


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Validate documentation freshness")
    parser.add_argument("project_root", type=Path)
    parser.add_argument(
        "--skip-stage",
        default="",
        help="Comma-separated stages to skip (e.g. F1,F2)",
    )
    parser.add_argument(
        "--no-lockfile",
        action="store_true",
        help="Do not write .docs_reconciled on success (CI dry-run)",
    )
    args = parser.parse_args(argv)

    project_root: Path = args.project_root.resolve()
    if not project_root.exists():
        print(f"[Error] project_root does not exist: {project_root}", file=sys.stderr)
        return 1

    skip = {s.strip().upper().replace("-", "") for s in args.skip_stage.split(",") if s.strip()}

    cfg = load_config(project_root)
    source_roots = cfg.get("source_roots") or list(_DEFAULT_SOURCE_ROOTS)
    meta_docs = cfg.get("meta_docs") or list(_DEFAULT_META_DOCS)
    exempt_paths = cfg.get("exempt_paths") or list(_DEFAULT_EXEMPT_PATHS)

    # Stage F-1 (also handles the enabled gate).
    stages_checked: list[str] = []
    passed = True
    parsed = None
    plan_path_str = None
    base: str | None = None
    sprint_start: str | None = None
    changed: set[str] | None = None
    skipped_f1 = "F1" in skip

    if not skipped_f1:
        f1_pass, parsed, plan_path_str = stage_f1(project_root, cfg)
        if not f1_pass:
            passed = False
        stages_checked.append("F-1")

    # If F-1 is skipped, still run downstream stages using a synthetic empty
    # frontmatter (claims = no claims, bools = false). This prevents the
    # `--skip-stage F1` cascade where F-2/F-3/F-4 silently don't run.
    if skipped_f1:
        sprint_id = find_active_sprint(project_root)
        if sprint_id is not None:
            plan_path_candidate = find_sprint_plan(project_root, sprint_id)
            plan_path_str = str(plan_path_candidate) if plan_path_candidate else None
        parsed = {
            "features": [],
            "user_stories": [],
            "schema_touched": False,
            "structure_touched": False,
        }
        print(
            "[Stage F-1] SKIPPED via --skip-stage; running F-2/F-3/F-4 with empty claims.",
            file=sys.stderr,
        )

    # Validator disabled OR no active sprint AND no skip — terminate early.
    if parsed is None or plan_path_str is None:
        # SP_736 seam fix: an ADVISORY pass (deploy provably code-free)
        # short-circuits here with parsed=None, so it never reached the
        # write_lockfile() below. But deploy.yml's gate step hard-asserts
        # `.docs_reconciled` exists ("FATAL: .docs_reconciled missing")
        # — so every docs-only deploy FATALs fleet-wide, re-introducing
        # the exact freeze SP_736 set out to remove. Advisory IS a pass
        # (the doc-freshness gate does not apply to a code-free deploy)
        # → it must still emit the deploy receipt. Distinguish advisory
        # from validator-disabled/no-sprint via scope_gate (same pure
        # env+file computation stage_f1 used); only write on a real
        # advisory pass.
        if passed and not args.no_lockfile:
            adv_sprint = find_active_sprint(project_root)
            if adv_sprint is not None:
                _, adv_mode = scope_gate(project_root, adv_sprint)
                if adv_mode == "advisory":
                    write_lockfile(
                        project_root,
                        adv_sprint,
                        stages_checked or ["F-1(advisory)"],
                        None,
                    )
        return 0 if passed else 1

    plan_path = Path(plan_path_str)
    base, sprint_start = resolve_diff_base(project_root, plan_path)
    if base is not None:
        changed = list_changed_files(project_root, base)
    else:
        print("[Stage F-2/F-3/F-4] ADVISORY: git unavailable; skipping.", file=sys.stderr)
        changed = None

    if "F2" not in skip:
        if not stage_f2(parsed, changed):
            passed = False
        stages_checked.append("F-2")

    if "F3" not in skip:
        if not stage_f3(changed, source_roots, meta_docs, exempt_paths):
            passed = False
        stages_checked.append("F-3")

    if "F4" not in skip:
        if not stage_f4(project_root, base, sprint_start, changed, meta_docs, parsed):
            passed = False
        stages_checked.append("F-4")

    if passed and not args.no_lockfile and parsed is not None:
        sprint_id = find_active_sprint(project_root)
        if sprint_id:
            write_lockfile(project_root, sprint_id, stages_checked, base)

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
