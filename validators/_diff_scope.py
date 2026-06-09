"""
Deploy-gate scoping helper.

This module is intentionally import-light so lifecycle validators can use it
without circular imports. It consumes two optional CI-provided signals:

- `DEV_DEPLOY_CODE_CHANGED`: literal "false" means the deploy diff is
  provably docs-only; every other value is fail-closed as code-bearing.
- `DEV_DEPLOY_CHANGED_FILES`: newline-separated changed paths.

Only the exact literal "false" yields advisory mode. Local runs and malformed
CI signals enforce the structural sprint gate.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

# Byte-parity with the `grep -vE` doc-exclusion regex in BOTH
# .github/workflows/ci.yml (~:65) and .github/workflows/deploy.yml
# (~:49). The 3-way parity test pins all three representations equal.
DOC_EXCLUDE_RE = r"(^|/)[^/]+\.md$|^docs/|^workspace/|^rules/|^principles/"

_OPEN_STATUSES = {"Planning", "In Progress"}
_DEPLOY_SCOPING_STATUSES = _OPEN_STATUSES | {"Complete"}
_COMMIT_SPRINT_RE = re.compile(r"\bSP_\d{2,}\w*\b")
_COMMIT_SCAN_LIMIT = 40


def _is_doc(path: str) -> bool:
    """True iff `path` is documentation/plan-only (excluded from the
    code-set, exactly as the workflow `changes` job's `grep -vE`)."""
    return re.search(DOC_EXCLUDE_RE, path) is not None


def _sprint_touches(
    project_root: Path, accepted_statuses: set[str]
) -> dict[str, list[str]]:
    """{SP_NNN: [touches_paths…]} for every sprint plan with an accepted
    status. Self-contained frontmatter read — must not import _common /
    validate_doc_freshness (circular-import constraint)."""
    out: dict[str, list[str]] = {}
    sprints_dir = project_root / "workspace" / "sprints"
    if not sprints_dir.is_dir():
        return out
    for plan in sorted(sprints_dir.glob("SP_*.md")):
        sid_m = re.match(r"(SP_\d+)", plan.stem)
        if not sid_m:
            continue
        try:
            text = plan.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fm_m = re.match(r"^---\n(.*?)\n---", text, re.S)
        # Fallback (no `---` frontmatter, or CRLF defeating `^---\n`):
        # scan the first 4000 chars. Bounded so a pathological huge
        # preamble can't blow the regex; fail-closed (a junk parse here
        # only ever yields ENFORCE, never advisory).
        fm = fm_m.group(1) if fm_m else text[:4000]
        st_m = re.search(r"^status:\s*(.+)$", fm, re.M)
        status = st_m.group(1) if st_m else ""
        status = re.sub(r"\s+#.*$", "", status)  # strip inline YAML comment
        status = status.strip().strip("\"'")
        if status not in accepted_statuses:
            continue
        paths: list[str] = []
        tp_inline = re.search(r"^touches_paths:\s*\[(.*?)\]", fm, re.M | re.S)
        if tp_inline:
            paths = [
                x.strip().strip("\"'")
                for x in tp_inline.group(1).split(",")
                if x.strip().strip("\"'")
            ]
        else:
            # YAML block-sequence style — explicit line-scan (not one
            # greedy regex): collect `- item` lines after the bare
            # `touches_paths:` key and STOP at the first line that is not
            # an indented dash item (a blank line or the next frontmatter
            # key). This makes over-capture into an adjacent block key
            # (e.g. `touches_checklist_items:`) structurally impossible.
            lines = fm.splitlines()
            start = None
            for i, ln in enumerate(lines):
                if re.match(r"^touches_paths:[ \t]*$", ln):
                    start = i + 1
                    break
            if start is not None:
                for ln in lines[start:]:
                    dash = re.match(r"^[ \t]*-[ \t]*(.*)$", ln)
                    if not dash:
                        break  # blank line or next key — block ended
                    v = dash.group(1).strip()
                    if not v:
                        continue  # empty list item — skip, not end-of-block
                    v = re.sub(r"\s+#.*$", "", v).strip().strip("\"'")
                    if v:
                        paths.append(v)
        out[sid_m.group(1)] = paths
    return out


def _open_sprint_touches(project_root: Path) -> dict[str, list[str]]:
    """{SP_NNN: [touches_paths…]} for every Planning / In Progress plan."""
    return _sprint_touches(project_root, _OPEN_STATUSES)


def _recent_sprint_tokens(project_root: Path) -> list[str]:
    """Newest-first SP tokens from recent commit subjects. Never raises."""
    try:
        result = subprocess.run(
            ["git", "log", f"-{_COMMIT_SCAN_LIMIT}", "--format=%s", "HEAD"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0:
        return []
    seen: set[str] = set()
    tokens: list[str] = []
    for subject in result.stdout.splitlines():
        for token in _COMMIT_SPRINT_RE.findall(subject):
            if token in seen:
                continue
            seen.add(token)
            tokens.append(token)
    return tokens


def _paths_match(code_set: list[str], paths: list[str]) -> bool:
    return any(
        c == p or c.startswith(p if p.endswith("/") else p + "/")
        for c in code_set
        for p in paths
    )


def scope_gate(project_root: Path, resolved_sprint_id: str | None):
    """Return (gated_sprint_id, mode) where mode ∈ {"enforce","advisory"}.

    `advisory` ⇔ the deploy is provably code-free (CI-asserted). Every
    other path is fail-closed `enforce`. The caller (validate_sprint /
    validate_doc_freshness wrapper) emits a WARN and short-circuits to a
    pass when mode == "advisory"; otherwise it gates `gated_sprint_id`.
    """
    code = os.environ.get("DEV_DEPLOY_CODE_CHANGED")
    if code is None:
        return (resolved_sprint_id, "enforce")  # off-CI / local — fail-closed
    if code == "false":
        return (None, "advisory")  # provably code-free — the ONLY advisory path
    # code-bearing: "true", or any non-"false" value → fail-closed code-bearing
    changed = [
        c.strip()
        for c in os.environ.get("DEV_DEPLOY_CHANGED_FILES", "").splitlines()
        if c.strip()
    ]
    code_set = [c for c in changed if not _is_doc(c)]
    if not code_set:
        return (resolved_sprint_id, "enforce")  # defensive (CI fail-safe true/∅)
    # Stage-7 deploys often mark the sprint plan `Complete` before the
    # code-bearing merge reaches deploy. Prefer a recent commit token whose
    # touched code matches, even when that plan is already Complete; otherwise
    # a newer blocked/planning sibling can fleet-freeze the deploy gate.
    deploy_touches = _sprint_touches(project_root, _DEPLOY_SCOPING_STATUSES)
    for sid in _recent_sprint_tokens(project_root):
        if sid in deploy_touches and _paths_match(code_set, deploy_touches[sid]):
            return (sid, "enforce")

    # Iteration is over sorted(glob) order (Python 3.7+ dict preserves
    # insertion order) → on a multi-sprint code-set match, the
    # lowest-numbered SP_NNN wins. Deterministic; both outcomes are
    # ENFORCE so a "wrong but still strict" scope is fail-closed-safe.
    for sid, paths in _open_sprint_touches(project_root).items():
        if _paths_match(code_set, paths):
            return (sid, "enforce")  # the deploying sprint — scoped gate
    return (resolved_sprint_id, "enforce")  # no touches_paths match — fail-closed
