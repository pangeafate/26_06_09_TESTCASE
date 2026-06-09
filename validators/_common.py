"""SP_719 — shared multi-agent-robust active-sprint resolver.

SINGLE SOURCE OF TRUTH for "which sprint is active" across the deploy
gate. Previously five files each carried their own
`_ACTIVE_SPRINT_RE = **Current:**\\s+(SP_\\S+)` + first-regex-match
`find_active_sprint`. Under N parallel agents PROGRESS.md accumulates
multiple `**Current:** SP_NNN` lines, so first-match resolved the WRONG
sprint → `resolve_diff_base` used the wrong plan → F-4 false-RED → the
session-long collateral `--no-verify` deploy churn (and the BUG_035
misdiagnosis). Extraction designated by the in-tree note
`validate_doc_freshness.py` ("queued for SP_003", never done).

Resolution strategy (deterministic per-SHA, immune to parallel PROGRESS
prepends; never throws; NEVER looser — only ever yields a real
open-status plan id or None → existing F-1 ADVISORY-skip):

  1. PRIMARY — newest commit subject on HEAD (bounded window) carrying
     `\\bSP_\\d{2,}\\b` whose sprint plan file exists with frontmatter
     status ∈ {Planning, In Progress}. This is the sprint THIS HEAD is
     about (matches CI/deploy-a-SHA semantics).
  2. FALLBACK — PROGRESS.md first `**Current:**\\s+(SP_\\d{2,})` (regex
     TIGHTENED vs the old `SP_\\S+` which even matched the literal
     `SP_NNN` placeholder in prose). Preserves single-agent behaviour.
  3. None — neither yields a real open-status sprint.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

# Tightened: \d{2,} so a prose placeholder `SP_NNN` can never match.
_ACTIVE_SPRINT_RE = re.compile(r"\*\*Current:\*\*\s+(SP_\d{2,}\w*)")
_COMMIT_SPRINT_RE = re.compile(r"\bSP_\d{2,}\w*\b")
_STATUS_LINE_RE = re.compile(r"^status:\s*(.+?)\s*$", re.MULTILINE)
_OPEN_STATUSES = {"Planning", "In Progress"}
_COMMIT_SCAN_LIMIT = 40


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
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return 127, "", "git unavailable"
    return result.returncode, result.stdout, result.stderr


def _read_text(path: Path) -> str | None:
    """utf-8-sig (BOM-tolerant) read; None on any IO/decode error."""
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None


def _plan_status(project_root: Path, sprint_id: str) -> str | None:
    """Frontmatter `status:` of the sprint plan.

    Returns: the status string; `""` when a plan file exists but has NO
    `status:` line (deliberately NOT in `_OPEN_STATUSES` → treated as
    not-active, same as Complete — a statusless plan must never resolve
    as the active sprint); `None` when no plan file exists at all.
    Callers MUST gate on `status in _OPEN_STATUSES` (never `is not None`
    / `!= ""`) or a statusless plan would be wrongly treated as active.
    Status read is a simple `status:` line match (sufficient for the
    open-status gate — equivalent to full YAML for this single scalar)."""
    for sprints_dir in (
        project_root / "workspace" / "sprints",
        project_root / "00_IMPLEMENTATION" / "SPRINTS",
    ):
        if not sprints_dir.is_dir():
            continue
        exact = sprints_dir / f"{sprint_id}.md"
        candidates = [exact] if exact.exists() else sorted(
            sprints_dir.glob(f"{sprint_id}_*.md")
        )
        sub = sprints_dir / sprint_id
        if sub.is_dir():
            sexact = sub / f"{sprint_id}.md"
            candidates += [sexact] if sexact.exists() else sorted(
                sub.glob(f"{sprint_id}_*.md")
            )
        for plan in candidates:
            text = _read_text(plan)
            if text is None:
                continue
            m = _STATUS_LINE_RE.search(text)
            if m:
                return m.group(1).strip()
            return ""  # plan exists but no status line → treat as not-open
    return None


def _sprint_id_from_recent_commits(project_root: Path) -> str | None:
    """Newest HEAD commit-subject SP_<digits> token whose plan is open."""
    rc, out, _ = _git(
        project_root, "log", f"-{_COMMIT_SCAN_LIMIT}", "--format=%s", "HEAD"
    )
    if rc != 0:
        return None
    for subject in out.splitlines():  # newest-first
        for tok in _COMMIT_SPRINT_RE.findall(subject):
            status = _plan_status(project_root, tok)
            if status in _OPEN_STATUSES:
                return tok
    return None


def find_active_sprint(project_root: Path) -> str | None:
    """Resolve the active sprint id. Signature-identical to every prior
    copy (drop-in). Never raises; None → caller's ADVISORY-skip."""
    git_first = _sprint_id_from_recent_commits(project_root)
    if git_first is not None:
        return git_first
    progress = project_root / "PROGRESS.md"
    if not progress.exists():
        return None
    text = _read_text(progress)
    if text is None:
        return None
    m = _ACTIVE_SPRINT_RE.search(text)
    return m.group(1) if m else None
