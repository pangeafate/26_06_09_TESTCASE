#!/usr/bin/env python3
"""
validate_doc_reality.py — Documentation-reality drift validator.

Four stages:
    A. Dead-path references in meta-doc markdown
    B. TBD-by decay (overdue placeholders)
    C. Meta-doc frontmatter presence + validity
    D. Paired-file duplication (long identical runs)

Usage:
    python validate_doc_reality.py <project_root> [--skip-stage A,B,C,D]

Exit codes:
    0 — all enforced stages pass
    1 — one or more stages failed
"""
from __future__ import annotations

import argparse
import datetime as _dt
import difflib
import fnmatch
import re
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

_DEFAULT_EXCLUDE_COMPONENTS = {
    ".git", ".hg", ".svn",
    "node_modules", "__pycache__",
    ".venv", "venv", "env",
    "dist", "build",
    ".tox", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".idea",
    "templates", "vision",
    "test", "tests",
    "workspace", "practices", "architecture", "roles", "deploy", "skills",
    "examples",
}

_DEFAULT_EXCLUDE_FILENAME_GLOBS = [
    "PROGRESS_ARCHIVE_*.md",
    "*_ARCHIVE.md",
]

_DEFAULT_FRONTMATTER_REQUIRED = [
    "PROGRESS.md",
    "PROJECT_ROADMAP.md",
    "FEATURE_LIST.md",
    "ARCHITECTURE.md",
    "DATA_SCHEMA.md",
    "CODEBASE_STRUCTURE.md",
    "USER_STORIES.md",
]

_DEFAULT_PAIRED_FILES: list[list[str]] = [
    ["AGENT_INSTRUCTIONS.md", "CLAUDE.md"],
]

_DEFAULT_DUPLICATION_THRESHOLD = 30
_MIN_NON_BLANK_LINES_IN_BLOCK = 20
_PER_FILE_READ_CAP_BYTES = 1_048_576  # 1 MB
_FRONTMATTER_MAX_LINES = 50

_ACCEPTED_STATUS_VALUES = {"living", "vision", "spec", "archived", "generated"}

_PLACEHOLDER_MARKERS = ("XXX", "YYY", "NNN", "<", ">", "{{", "...")
_GLOB_CHARS = set("*?[]")

_KNOWN_EXTENSIONS = ("py", "md", "sh", "yml", "yaml", "json", "ts", "js", "sql")

# Regex: backtick-wrapped token consisting of path-safe chars.
_BACKTICK_TOKEN_RE = re.compile(r"`([A-Za-z0-9_./\-]+)`")

# Code-fence lines (start or end): a line whose *first non-whitespace content*
# is three-or-more backticks (optionally followed by a language tag).
_CODE_FENCE_RE = re.compile(r"^\s*```")

# HTML comment block: `<!-- ... -->` possibly multi-line.
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

# Inline suppression markers.
_IGNORE_PATHS_MARKER = "doc-reality:ignore-paths"
_IGNORE_BLOCK_START_MARKER = "doc-reality:ignore-block-start"
_IGNORE_BLOCK_END_MARKER = "doc-reality:ignore-block-end"

# Active-sprint pattern — duplicated from validate_sprint.py.
# NOTE: duplicated from validators/validate_sprint.py; shared helper extraction
# deferred to SP_002 to keep this sprint's scope tight.
# TBD-by decay marker.
_TBD_BY_RE = re.compile(r"TBD-by:\s*SP_(\d+)\b")

# Numeric sprint extractor for the active sprint slug.
_SPRINT_NUM_RE = re.compile(r"SP_(\d+)")

# @inherits: directive syntax.
_INHERITS_OPEN_RE = re.compile(r"^@inherits:\s+\S+\s*$")
_INHERITS_END_RE = re.compile(r"^@inherits-end:\s*$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# SP_719 — single multi-agent-robust resolver (was a duplicated
# first-match copy, broken under parallel agents). Drop-in import.
from _common import find_active_sprint  # noqa: E402  pylint: disable=wrong-import-position


def load_config(project_root: Path) -> dict:
    """Load `.validators.yml` `doc_reality:` block. Returns {} if absent or
    unparseable; prints advisory in the latter case. Uses PyYAML when present,
    otherwise a limited fallback parser sufficient for the documented schema."""
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
            print(
                "[Advisory] .validators.yml failed to parse as YAML; "
                "using defaults.",
                file=sys.stderr,
            )
            return {}
    else:
        try:
            data = _fallback_parse_validators_yml(text)
        except Exception:
            print(
                "[Advisory] .validators.yml fallback parse failed; using defaults.",
                file=sys.stderr,
            )
            return {}
    if not isinstance(data, dict):
        return {}
    block = data.get("doc_reality")
    return block if isinstance(block, dict) else {}


def _fallback_parse_validators_yml(text: str) -> dict:
    """Parse the limited YAML subset required by `.validators.yml`. Supports:
    - Top-level `key:` headings with nested indented mappings.
    - Scalars: strings (unquoted or single/double-quoted), integers.
    - Flow sequences `[a, b, c]`.
    - Block sequences `- item` and `- [a, b]`.
    Two indentation levels only (top-level + nested under doc_reality).
    """
    result: dict = {}
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.startswith(" ") and line.rstrip().endswith(":"):
            # Top-level section header.
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
                        # Block-sequence follows.
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
        # Top-level key: value
        if ":" in line:
            key, _, rhs = line.partition(":")
            result[key.strip()] = _parse_scalar_or_flow(rhs.strip())
        i += 1
    return result


def _parse_scalar_or_flow(raw: str):
    """Parse a RHS as flow sequence, quoted string, integer, or bare string."""
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
    try:
        return int(raw)
    except ValueError:
        return raw


def parse_frontmatter(text: str) -> tuple[str, dict | None]:
    """Return (state, parsed_dict | None).

    state is one of:
        "missing"   — no opening `---` at byte 0.
        "malformed" — opening `---` found but closing `---` not within the
                      first _FRONTMATTER_MAX_LINES lines.
        "present"   — both delimiters found; parsed_dict is the parsed YAML.
    """
    if not text.startswith("---\n") and text != "---":
        # Accept CRLF too on the opening marker.
        if not text.startswith("---\r\n"):
            return "missing", None
    # Find closing `---` within the line cap.
    lines = text.splitlines()
    if not lines:
        return "missing", None
    if lines[0].strip() != "---":
        return "missing", None
    closing_idx = None
    for idx in range(1, min(len(lines), _FRONTMATTER_MAX_LINES + 1)):
        if lines[idx].strip() == "---":
            closing_idx = idx
            break
    if closing_idx is None:
        return "malformed", None
    body = "\n".join(lines[1:closing_idx])
    parsed: dict
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
    """Very small `key: value` / `key: [a, b]` parser for when PyYAML is
    unavailable. Supports strings, ISO dates (as strings), and flow sequences
    of scalars."""
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


def strip_code_fences(text: str) -> str:
    """Remove lines contained within triple-backtick code fences (inclusive of
    the fence lines themselves). Unterminated fences consume to EOF."""
    out: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if _CODE_FENCE_RE.match(line):
            in_fence = not in_fence
            out.append("")  # preserve line index
            continue
        if in_fence:
            out.append("")
            continue
        out.append(line)
    return "\n".join(out)


def strip_html_comments(text: str) -> str:
    """Remove `<!-- ... -->` blocks (possibly multi-line), preserving line
    count by replacing each comment span with equivalent blank lines."""
    def _replace(match: re.Match[str]) -> str:
        newlines = match.group(0).count("\n")
        return "\n" * newlines

    return _HTML_COMMENT_RE.sub(_replace, text)


def is_path_under(path: Path, root: Path) -> bool:
    """True iff resolved path is within root (protects against `../` escape)."""
    try:
        resolved = path.resolve()
        root_resolved = root.resolve()
    except (OSError, RuntimeError):
        return False
    try:
        return resolved.is_relative_to(root_resolved)
    except AttributeError:  # Python < 3.9 fallback
        try:
            resolved.relative_to(root_resolved)
            return True
        except ValueError:
            return False


def iter_markdown_files(
    project_root: Path,
    exclude_components: set[str],
    exclude_globs: list[str],
) -> list[Path]:
    """Yield *.md files under project_root honoring exclusion rules."""
    matches: list[Path] = []
    for path in project_root.rglob("*.md"):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(project_root)
        except ValueError:
            continue
        parts = set(rel.parts)
        if parts & exclude_components:
            continue
        if any(fnmatch.fnmatch(rel.name, glob) for glob in exclude_globs):
            continue
        matches.append(path)
    return matches


def _read_text_capped(path: Path, cap: int = _PER_FILE_READ_CAP_BYTES) -> str | None:
    """Read up to `cap` bytes; return None if file is above cap."""
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size > cap:
        return None
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None


# ---------------------------------------------------------------------------
# Stage A — dead path references
# ---------------------------------------------------------------------------


def _extract_path_candidates(
    text: str,
) -> list[tuple[str, int]]:
    """Return list of (token, line_number_1_based) for backtick tokens that
    look like paths."""
    cleaned = strip_code_fences(text)
    cleaned = strip_html_comments(cleaned)

    # Collect ignore-line markers (line indices where the NEXT line should be
    # skipped) and ignore-block spans.
    ignore_next_line: set[int] = set()
    ignore_block_ranges: list[tuple[int, int]] = []  # (start, end) inclusive
    # We work against the ORIGINAL text for marker detection because comments
    # are already stripped after cleaning.
    block_start: int | None = None
    for idx, line in enumerate(text.splitlines(), start=1):
        if _IGNORE_PATHS_MARKER in line:
            ignore_next_line.add(idx + 1)
        if _IGNORE_BLOCK_START_MARKER in line:
            block_start = idx
        if _IGNORE_BLOCK_END_MARKER in line and block_start is not None:
            ignore_block_ranges.append((block_start, idx))
            block_start = None

    def _in_ignore_range(line_no: int) -> bool:
        if line_no in ignore_next_line:
            return True
        for start, end in ignore_block_ranges:
            if start <= line_no <= end:
                return True
        return False

    findings: list[tuple[str, int]] = []
    for idx, line in enumerate(cleaned.splitlines(), start=1):
        if _in_ignore_range(idx):
            continue
        for match in _BACKTICK_TOKEN_RE.finditer(line):
            token = match.group(1)
            if _token_looks_like_path(token):
                findings.append((token, idx))
    return findings


def _token_looks_like_path(token: str) -> bool:
    if "/" not in token:
        return False
    if any(marker in token for marker in _PLACEHOLDER_MARKERS):
        return False
    if any(ch in _GLOB_CHARS for ch in token):
        return False
    if token.endswith("/"):
        return True
    # Must end with a known extension.
    if "." in token:
        ext = token.rsplit(".", 1)[-1].lower()
        if ext in _KNOWN_EXTENSIONS:
            return True
    return False


def stage_a_dead_paths(
    project_root: Path,
    exclude_components: set[str],
    exclude_globs: list[str],
    dead_path_exclusions: list[str],
    dead_path_glob_exclusions: list[str],
) -> list[str]:
    """Return list of failure messages; empty list = PASS."""
    failures: list[str] = []
    files = iter_markdown_files(project_root, exclude_components, exclude_globs)
    for md_path in files:
        text = _read_text_capped(md_path)
        if text is None:
            print(
                f"[Stage A] ADVISORY: {md_path.relative_to(project_root)} "
                "skipped (size > 1MB or unreadable).",
                file=sys.stderr,
            )
            continue
        for token, line_no in _extract_path_candidates(text):
            if token in dead_path_exclusions:
                continue
            if any(fnmatch.fnmatch(token, g) for g in dead_path_glob_exclusions):
                continue
            candidate = project_root / token
            if not is_path_under(candidate, project_root):
                # Path-traversal attempt — ignore silently, do not fail.
                continue
            # Check via lstat — does NOT follow symlinks. Prevents the
            # symlink false-pass: a malicious commit adding `dead/path` as a
            # symlink to `/tmp/anywhere` could otherwise mark a deleted file
            # as alive. If the path is a symlink, also verify the resolved
            # target stays inside the project root.
            try:
                candidate.lstat()
            except OSError:
                rel = md_path.relative_to(project_root)
                failures.append(
                    f"[Stage A] FAIL: {rel}:{line_no} references nonexistent path `{token}`"
                )
                continue
            if candidate.is_symlink():
                try:
                    resolved = candidate.resolve(strict=True)
                    if not is_path_under(resolved, project_root):
                        rel = md_path.relative_to(project_root)
                        failures.append(
                            f"[Stage A] FAIL: {rel}:{line_no} symlink `{token}` "
                            "escapes the project root"
                        )
                        continue
                except (OSError, RuntimeError):
                    # Broken symlink — accept (matches prior contract for symlinks).
                    pass
    return failures


# ---------------------------------------------------------------------------
# Stage B — TBD-by decay
# ---------------------------------------------------------------------------


def stage_b_tbd_decay(
    project_root: Path,
    exclude_components: set[str],
    exclude_globs: list[str],
) -> list[str]:
    """Return list of failure messages."""
    sprint_id = find_active_sprint(project_root)
    if sprint_id is None:
        print(
            "[Stage B] ADVISORY: No active sprint in PROGRESS.md; skipping.",
            file=sys.stderr,
        )
        return []
    num_match = _SPRINT_NUM_RE.match(sprint_id)
    if not num_match:
        print(
            f"[Stage B] ADVISORY: Active sprint '{sprint_id}' has no numeric "
            "prefix; skipping.",
            file=sys.stderr,
        )
        return []
    active_num = int(num_match.group(1))
    failures: list[str] = []
    for md_path in iter_markdown_files(project_root, exclude_components, exclude_globs):
        text = _read_text_capped(md_path)
        if text is None:
            continue
        for idx, line in enumerate(text.splitlines(), start=1):
            for match in _TBD_BY_RE.finditer(line):
                tbd_num = int(match.group(1))
                rel = md_path.relative_to(project_root)
                if tbd_num < active_num:
                    failures.append(
                        f"[Stage B] FAIL: {rel}:{idx} TBD-by SP_{tbd_num:03d} "
                        f"has elapsed (active: {sprint_id})"
                    )
                elif tbd_num == active_num:
                    print(
                        f"[Stage B] ADVISORY: {rel}:{idx} TBD-by SP_{tbd_num:03d} "
                        "due this sprint.",
                        file=sys.stderr,
                    )
    return failures


# ---------------------------------------------------------------------------
# Stage C — frontmatter presence and validity
# ---------------------------------------------------------------------------


def stage_c_frontmatter(
    project_root: Path,
    required_files: list[str],
) -> list[str]:
    """Return list of failure messages."""
    failures: list[str] = []
    for name in required_files:
        path = project_root / name
        if not path.exists():
            print(
                f"[Stage C] ADVISORY: manifest entry '{name}' not present at "
                "project root; skipping.",
                file=sys.stderr,
            )
            continue
        text = _read_text_capped(path)
        if text is None:
            failures.append(f"[Stage C] FAIL: {name} unreadable or > 1MB")
            continue
        state, parsed = parse_frontmatter(text)
        if state == "missing":
            failures.append(f"[Stage C] FAIL: {name} missing frontmatter (no opening `---` at byte 0)")
            continue
        if state == "malformed":
            failures.append(
                f"[Stage C] FAIL: {name} frontmatter not closed within "
                f"{_FRONTMATTER_MAX_LINES} lines"
            )
            continue
        parsed = parsed or {}
        status = parsed.get("status")
        last_rec = parsed.get("last-reconciled")
        if status is None:
            failures.append(f"[Stage C] FAIL: {name} frontmatter missing required key 'status'")
            continue
        if status not in _ACCEPTED_STATUS_VALUES:
            failures.append(
                f"[Stage C] FAIL: {name} frontmatter 'status' = {status!r} "
                f"not in accepted enum {sorted(_ACCEPTED_STATUS_VALUES)}"
            )
            continue
        if last_rec is None:
            failures.append(f"[Stage C] FAIL: {name} frontmatter missing required key 'last-reconciled'")
            continue
        # `last-reconciled` may arrive as a datetime.date (PyYAML) or a str.
        date_str = (
            last_rec.isoformat() if isinstance(last_rec, _dt.date) else str(last_rec)
        )
        try:
            _dt.date.fromisoformat(date_str)
        except ValueError:
            failures.append(
                f"[Stage C] FAIL: {name} frontmatter 'last-reconciled' = {date_str!r} "
                "is not ISO-8601 YYYY-MM-DD"
            )
            continue
        if date_str == "1970-01-01":
            failures.append(
                f"[Stage C] FAIL: {name} frontmatter 'last-reconciled' = '1970-01-01' "
                "is the template sentinel; replace with today's ISO date when you copy the template."
            )
    return failures


# ---------------------------------------------------------------------------
# Stage D — paired-file duplication
# ---------------------------------------------------------------------------


def _strip_frontmatter(text: str) -> str:
    state, _ = parse_frontmatter(text)
    if state != "present":
        return text
    lines = text.splitlines()
    # Find the closing `---` within the allowed window.
    for idx in range(1, min(len(lines), _FRONTMATTER_MAX_LINES + 1)):
        if lines[idx].strip() == "---":
            return "\n".join(lines[idx + 1 :])
    return text


def _suppress_inherits_blocks(text: str, file_label: str) -> tuple[list[str], list[str]]:
    """Remove line ranges covered by `@inherits:` blocks. Returns
    (lines_after_suppression, advisories).
    """
    lines = text.splitlines()
    out: list[str] = []
    advisories: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if _INHERITS_OPEN_RE.match(line):
            # Look for terminator: @inherits-end: or next @inherits:.
            end_idx = None
            for j in range(i + 1, n):
                if _INHERITS_END_RE.match(lines[j]) or _INHERITS_OPEN_RE.match(lines[j]):
                    end_idx = j
                    break
            if end_idx is None:
                advisories.append(
                    f"[Stage D] ADVISORY: unterminated @inherits: block in {file_label} "
                    f"(line {i + 1}); only the @inherits: directive line is removed — the following "
                    "content remains subject to duplication detection."
                )
                i += 1
                continue
            # Skip from i through end_idx inclusive if terminator is @inherits-end:;
            # if terminator is a new @inherits:, skip up to (but not including) it.
            if _INHERITS_END_RE.match(lines[end_idx]):
                i = end_idx + 1
            else:
                i = end_idx
            continue
        out.append(line)
        i += 1
    return out, advisories


def stage_d_paired_duplication(
    project_root: Path,
    paired_files: list[list[str]],
    duplication_threshold: int,
) -> list[str]:
    """Return list of failure messages."""
    failures: list[str] = []
    for pair in paired_files:
        if len(pair) != 2:
            continue
        a_name, b_name = pair
        a_path = project_root / a_name
        b_path = project_root / b_name
        if not a_path.exists() or not b_path.exists():
            continue
        a_text = _read_text_capped(a_path)
        b_text = _read_text_capped(b_path)
        if a_text is None or b_text is None:
            print(
                f"[Stage D] ADVISORY: {a_name} or {b_name} > 1MB; skipping pair.",
                file=sys.stderr,
            )
            continue
        # Pre-process: strip frontmatter, then code fences, then HTML comments.
        a_proc = strip_html_comments(strip_code_fences(_strip_frontmatter(a_text)))
        b_proc = strip_html_comments(strip_code_fences(_strip_frontmatter(b_text)))
        # Suppress @inherits: blocks.
        a_lines, a_adv = _suppress_inherits_blocks(a_proc, a_name)
        b_lines, b_adv = _suppress_inherits_blocks(b_proc, b_name)
        for adv in a_adv + b_adv:
            print(adv, file=sys.stderr)
        # Normalize whitespace on each line.
        a_norm = [ln.rstrip() for ln in a_lines]
        b_norm = [ln.rstrip() for ln in b_lines]
        matcher = difflib.SequenceMatcher(None, a_norm, b_norm, autojunk=True)
        for block in matcher.get_matching_blocks():
            if block.size < duplication_threshold:
                continue
            span_a = a_norm[block.a : block.a + block.size]
            non_blank = sum(1 for ln in span_a if ln.strip())
            if non_blank < _MIN_NON_BLANK_LINES_IN_BLOCK:
                continue
            preview = "\n    ".join(span_a[:5])
            failures.append(
                f"[Stage D] FAIL: duplication between {a_name} (line ~{block.a + 1}) "
                f"and {b_name} (line ~{block.b + 1}), span {block.size} lines.\n"
                f"    {preview}"
            )
    return failures


# ---------------------------------------------------------------------------
# Stage runner
# ---------------------------------------------------------------------------


def _run_stage(label: str, failures: list[str]) -> bool:
    if failures:
        for msg in failures:
            print(msg, file=sys.stderr)
        return False
    print(f"[{label}] PASS", file=sys.stderr)
    return True


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Validate documentation reality")
    parser.add_argument("project_root", type=Path)
    parser.add_argument(
        "--skip-stage",
        default="",
        help="Comma-separated stages to skip, e.g. 'A,B'",
    )
    args = parser.parse_args(argv)

    project_root: Path = args.project_root.resolve()
    if not project_root.exists():
        print(f"[Error] project_root does not exist: {project_root}", file=sys.stderr)
        return 1

    skip = {s.strip().upper() for s in args.skip_stage.split(",") if s.strip()}

    cfg = load_config(project_root)
    exclude_components = set(_DEFAULT_EXCLUDE_COMPONENTS)
    exclude_components.update(cfg.get("exclude_dirs") or [])
    exclude_globs = list(_DEFAULT_EXCLUDE_FILENAME_GLOBS)
    dead_path_exclusions = cfg.get("dead_path_exclusions") or []
    dead_path_glob_exclusions = cfg.get("dead_path_glob_exclusions") or []
    required_files = cfg.get("frontmatter_required") or list(_DEFAULT_FRONTMATTER_REQUIRED)
    paired_files = cfg.get("paired_files") or list(_DEFAULT_PAIRED_FILES)
    threshold_raw = cfg.get("duplication_threshold", _DEFAULT_DUPLICATION_THRESHOLD)
    try:
        duplication_threshold = max(20, int(threshold_raw))
    except (TypeError, ValueError):
        duplication_threshold = _DEFAULT_DUPLICATION_THRESHOLD

    passed = True

    if "A" not in skip:
        if not _run_stage(
            "Stage A",
            stage_a_dead_paths(
                project_root,
                exclude_components,
                exclude_globs,
                dead_path_exclusions,
                dead_path_glob_exclusions,
            ),
        ):
            passed = False

    if "B" not in skip:
        if not _run_stage(
            "Stage B",
            stage_b_tbd_decay(project_root, exclude_components, exclude_globs),
        ):
            passed = False

    if "C" not in skip:
        if not _run_stage(
            "Stage C",
            stage_c_frontmatter(project_root, required_files),
        ):
            passed = False

    if "D" not in skip:
        if not _run_stage(
            "Stage D",
            stage_d_paired_duplication(project_root, paired_files, duplication_threshold),
        ):
            passed = False

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
