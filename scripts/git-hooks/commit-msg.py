#!/usr/bin/env python3
"""
SP_209 — Multi-agent collision prevention commit-msg hook.

Installed as `.git/hooks/commit-msg` (NOT pre-commit). Why: git's
`pre-commit` hook fires BEFORE the commit message is composed, so the
hook cannot read the `<type>(SP_NNN):` prefix. `.git/COMMIT_EDITMSG`
during pre-commit holds the LAST commit's message, not the new one —
checking against it gives wrong cross-sprint scope.

`commit-msg` fires AFTER the message is finalized; git passes the
message-file path as `$1`. Refusal here aborts the commit before it
records (same outcome as pre-commit refusal from the user's POV; the
tradeoff is that the user has typed/specified the message before
seeing the rejection — acceptable since rejection diagnostic explains
exactly which paths to drop from staging).

Refuses cross-sprint staged content + enforces plan-first-commit rule
(Rule 6 step 2). Runs at commit-time, before destructive sweeps land.

Behaviour:
  1. Read all *active* sprint plans:
     - status: In Progress → always active
     - status: Planned AND tracked-in-git → active (plan committed already)
     - status: Planned AND untracked → NOT active (we can't trust the
       file's frontmatter content yet)
  2. Extract SP_NNN from the commit-message conventional-commit prefix
     (`docs(SP_NNN):` / `feat(SP_NNN):` / `fix(SP_NNN):` / etc.).
     Empty / unreadable commit message file (rebase apply phase, etc.)
     → exit 0 with stderr advisory; do not block.
  3. For each staged file (other than Rule-7-mandated meta-docs):
     refuse if the file appears in another active sprint's
     `touches_paths` (precise path match OR directory-prefix match).
  4. Sweep heuristic: stage > 10 files AND > 3 outside the commit's
     sprint claims → WARNING (non-blocking).
  5. Plan-first-commit guard: untracked plan file matching the commit's
     SP_NNN → REFUSE with Rule 6 step 2 reference.
     Modified-not-staged plan file does NOT trigger (legitimate fixup).
  6. Malformed frontmatter on any active plan → REFUSE with diagnostic.

Bypass: `git commit --no-verify`. The hook isn't called when bypassed
(Git skips the hook entirely); the bypass is structurally visible only
via the absence of any hook output in the commit context.

Exit codes:
  0 — pass (commit proceeds)
  1 — refuse (commit rejected)
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Locate the shared frontmatter helper relative to this hook.
_HOOK_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _HOOK_DIR.parent.parent  # scripts/git-hooks/ → scripts/ → repo
sys.path.insert(0, str(_REPO_ROOT / "validators"))
from _sprint_frontmatter import (  # noqa: E402
    BROAD_FILE_THRESHOLD,
    OVERLAP_IGNORE_PATHS,
    STALE_DAYS,
    Claim,
    FrontmatterParseError,
    is_over_broad,
    plan_age_days,
    read_active_claims,
    tracked_files_under,
)

# Conventional-commit prefix: `<type>(SP_NNN):` or `<type>(SP_NNN<word>):`.
# Captures the SP id including any 3+-digit number.
_PREFIX_RE = re.compile(
    r"^(?:[a-z]+)\((SP_\d{3,})\)(?:[!]?:)",
    re.IGNORECASE,
)

# Conventional-commit prefix without an SP scope (e.g. `chore: ...`,
# `fix(ci): ...`) — recognised but treated as cross-sprint hygiene.
_GENERIC_PREFIX_RE = re.compile(
    r"^(?:[a-z]+)(?:\([^)]+\))?[!]?:",
    re.IGNORECASE,
)

# Sweep-heuristic thresholds — Stage-2 architect MEDIUM-2 evidence.
SWEEP_TOTAL = 10
SWEEP_UNCLAIMED = 3

# Agent-inbox heading — `## <ISO timestamp Z> — from <SP_NNN[-NNN]> — open`.
# Captures the timestamp; status `open` is the gating signal.
_INBOX_OPEN_RE = re.compile(
    r"^## (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z) — from SP_\d+(?:[-_]\d+)? — open\s*$",
    re.MULTILINE,
)
# Acknowledgement trailer — `Acknowledges-inbox: <ts>[, <ts>...]`.
# Comma-separated list of ISO timestamps the commit explicitly addresses
# or defers; missing → REFUSE (the gating mechanism).
_INBOX_ACK_RE = re.compile(
    r"^Acknowledges-inbox:\s*(.+?)\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_ISO_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z")


def _project_root() -> Path:
    """Repo root from `git rev-parse --show-toplevel`."""
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=False,
    )
    if out.returncode != 0:
        return _REPO_ROOT
    return Path(out.stdout.strip() or _REPO_ROOT)


def _staged_files(root: Path) -> list[str]:
    """Files in the staging area (relative to repo root)."""
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        capture_output=True, text=True, check=False, cwd=root,
    )
    if out.returncode != 0:
        return []
    return [line for line in out.stdout.splitlines() if line]


def _is_tracked(root: Path, rel_path: str) -> bool:
    """True iff `rel_path` is tracked in git (HEAD or staged)."""
    out = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", rel_path],
        capture_output=True, text=True, check=False, cwd=root,
    )
    return out.returncode == 0


def _read_commit_message(msg_file: Optional[str], root: Path) -> str:
    """Read the commit message.

    Git's `commit-msg` hook receives the message-file path as `$1`. For
    `-m`/`-F`/`-c`/`-C`/editor commits, git writes the proposed message
    to that file BEFORE firing this hook, so reading from there returns
    the message about to be recorded. Tests pass an explicit path for
    synthetic invocations; production receives it from git.

    Returns empty string on missing/unreadable/empty (rebase apply,
    pre-rebase, no-message commits, etc.).
    """
    if msg_file:
        try:
            with open(msg_file, "r", encoding="utf-8") as f:
                return f.read()
        except (OSError, UnicodeDecodeError):
            pass
    return ""


def _extract_sprint_id(commit_msg: str) -> Optional[str]:
    """Pull `SP_NNN` from a `<type>(SP_NNN): ...` first line.
    Returns None when the message has no SP-scoped prefix.
    """
    if not commit_msg.strip():
        return None
    first_line = commit_msg.splitlines()[0]
    m = _PREFIX_RE.match(first_line)
    return m.group(1).upper() if m else None


def _path_matches_claim(staged_path: str, claim_path: str) -> bool:
    """True if `staged_path` is `claim_path` exactly, or under it
    (directory-style), or matches a glob suffix `*` (e.g. `SP_209_*`).
    Single-segment glob patterns are treated leniently — matches when
    the prefix-before-`*` is a prefix of the staged path's basename in
    the same directory.
    """
    # Normalise trailing slash for prefix-form claims like "src/foo/"
    cp = claim_path.rstrip("/")
    if cp == staged_path:
        return True
    if staged_path.startswith(cp + "/"):
        return True
    # Glob suffix shape `dir/prefix*` (used in claims like
    # `workspace/sprints/SP_209_*`) — match when staged_path is in the
    # same dir AND its basename starts with the prefix-before-`*`.
    if "*" in cp:
        head, _, tail = cp.partition("*")
        if tail == "":  # trailing-only glob — supported
            if "/" in head:
                head_dir, _, prefix = head.rpartition("/")
                staged_dir, _, staged_base = staged_path.rpartition("/")
                if staged_dir == head_dir and staged_base.startswith(prefix):
                    return True
            else:
                # No directory in head — match any path starting with it
                if staged_path.startswith(head):
                    return True
        else:
            # Stage-5 LOW-2: non-trailing glob (`src/foo/*.ts`, `**/x`)
            # is unsupported. Surface a warning so misconfigured claims
            # don't silently void.
            print(
                f"[pre-commit] WARNING: claim path '{cp}' uses an unsupported "
                f"glob shape (only trailing `*` is supported); treating as no-match.",
                file=sys.stderr,
            )
    return False


def _foreign_claim_match(
    staged_path: str,
    own_sprint_id: Optional[str],
    claims: list[Claim],
    root: Path,
    age_cache: dict[str, Optional[int]],
    broad_cache: Optional[dict[str, int]] = None,
) -> Optional[Claim]:
    """Return the first BLOCKING foreign claim matching this staged path, or None.

    SP_956 (relax-only): a foreign claim whose owner plan has had no commit in
    ≥ STALE_DAYS is a "zombie" and is SKIPPED — stale sprints no longer block
    other agents' commits (the ~397-bypass class). Stale claims are skipped
    INDIVIDUALLY so a *fresh* co-claiming sprint still refuses (a hot path like
    `components.ts` is co-claimed by ~21 In-Progress sprints). `age_cache`
    memoises plan age per plan-path across the whole commit, so a zombie
    co-claiming N staged paths is aged once, not N times.

    SP_957 (relax-only): after the stale skip, a foreign claim that matches the
    staged path ONLY via over-broad bare-directory prefixes (> BROAD_FILE_THRESHOLD
    tracked files) is SKIPPED — a blanket high-traffic-root claim (`scenarios/`,
    `docs/`, `src/jobs/`) must not freeze the commits underneath it
    (the ~242-bypass class). The skip fires ONLY when EVERY matching prefix of this
    claim is over-broad; a *specific* matching prefix (≤ threshold) still refuses
    ("specific wins"). `broad_cache` memoises the tracked-file count per PREFIX
    string across the whole commit, so a hot prefix co-claimed by several sprints
    (`scenarios/` by SP_751 + SP_950) is `git ls-files`-ed once. Stale-skip runs
    first: a claim that is both stale and over-broad never reaches the
    `git ls-files` count (the cheaper `git log` short-circuits).

    ACCEPTED TRADE-OFF: a sprint that expresses its claim ONLY at bare-directory
    granularity loses foreign-block protection on EVERY file under it — including
    a file it genuinely co-edits, not just unrelated ones. This is intentional: a
    blanket `scenarios/` claim cannot distinguish related from unrelated edits, so
    it carries no usable collision signal (the bypass log shows ~6 genuine
    concurrent-edit conflicts in 2,453 entries — blanket claims are noise). A
    sprint that needs real collision protection must claim the specific
    sub-paths it edits (≤ threshold), which still refuse.

    Both skips are fail-CLOSED: a None/uncomputable age is treated as NOT stale,
    and an empty `matching` list (caller/recompute predicate divergence) leaves
    `matching and …` falsy → falls through to `return claim`. The own-sprint skip
    is the first guard. This function only ever suppresses a refusal; it can never
    produce one — so it cannot fleet-freeze (the load-bearing relax-only invariant).
    """
    if broad_cache is None:
        broad_cache = {}
    for claim in claims:
        if claim.sprint_id == own_sprint_id:
            continue
        if not any(_path_matches_claim(staged_path, cp) for cp in claim.touches_paths):
            continue
        key = str(claim.path)
        if key not in age_cache:
            age_cache[key] = plan_age_days(root, claim.path)
        age = age_cache[key]
        if age is not None and age >= STALE_DAYS:
            print(
                f"[pre-commit] note: skipping stale claim {claim.sprint_id} "
                f"({age}d, no plan commit) on {staged_path}",
                file=sys.stderr,
            )
            continue  # zombie — does not block
        # SP_957 over-broad skip. Recompute which prefixes matched (the caller
        # only knows "at least one matched"). Skip iff EVERY matching prefix is
        # over-broad; any specific (≤ threshold) prefix refuses. Empty `matching`
        # is impossible today (the caller already matched) but the `matching and`
        # guard makes the relax-only invariant leak-proof even if the predicates
        # ever diverge: empty → refuse, never silently skip.
        matching = [cp for cp in claim.touches_paths
                    if _path_matches_claim(staged_path, cp)]
        if matching:
            all_broad = True
            for cp in matching:
                if cp not in broad_cache:
                    broad_cache[cp] = tracked_files_under(root, cp)
                if not is_over_broad(broad_cache[cp]):
                    all_broad = False
                    break
            if all_broad:
                print(
                    f"[pre-commit] note: skipping over-broad claim "
                    f"{claim.sprint_id} ({matching[0]} >{BROAD_FILE_THRESHOLD} "
                    f"tracked files) on {staged_path}",
                    file=sys.stderr,
                )
                continue  # blanket bare-directory claim — does not block
        return claim
    return None


def _is_own_sprint_claim(
    staged_path: str,
    own_sprint_id: Optional[str],
    claims: list[Claim],
) -> bool:
    """True if `staged_path` is in the commit's own sprint's `touches_paths`."""
    if own_sprint_id is None:
        return False
    for claim in claims:
        if claim.sprint_id != own_sprint_id:
            continue
        for cp in claim.touches_paths:
            if _path_matches_claim(staged_path, cp):
                return True
    return False


def _untracked_plan_for_sprint(
    root: Path,
    sprint_id: str,
) -> Optional[Path]:
    """If `workspace/sprints/SP_NNN_*.md` exists on disk but isn't tracked,
    return its path; else None. Modified-not-staged returns None
    (Stage-2 architect HIGH-1 fix — only true untracked is a guard trigger).
    """
    sprints_dir = root / "workspace" / "sprints"
    if not sprints_dir.is_dir():
        return None
    # SP_NNN_<anything>.md
    pattern = f"{sprint_id}_*.md"
    for candidate in sprints_dir.glob(pattern):
        rel = str(candidate.relative_to(root))
        if not _is_tracked(root, rel):
            return candidate
    return None


def _open_inbox_timestamps(root: Path, sprint_id: str) -> list[str]:
    """Return ISO timestamps of `open` entries in workspace/agent_inbox/<sprint_id>.md.

    Returns empty list if the file does not exist (no messages addressed
    to this sprint) or no `open` entries remain (all resolved).
    """
    inbox = root / "workspace" / "agent_inbox" / f"{sprint_id}.md"
    if not inbox.is_file():
        return []
    try:
        text = inbox.read_text(encoding="utf-8")
    except OSError:
        return []
    return _INBOX_OPEN_RE.findall(text)


def _commit_acknowledged_timestamps(commit_msg: str) -> set[str]:
    """Return set of ISO timestamps the commit message explicitly acknowledges
    via `Acknowledges-inbox: <ts>[, <ts>...]` trailers (case-insensitive,
    multiple lines accepted).
    """
    acked: set[str] = set()
    for trailer_value in _INBOX_ACK_RE.findall(commit_msg):
        for ts in _ISO_TS_RE.findall(trailer_value):
            acked.add(ts)
    return acked


def main(argv: list[str]) -> int:
    # `pre-commit` git hook is invoked without arguments (unlike
    # `commit-msg`). Tests + manual invocations may pass an explicit
    # commit-message file path as argv[1]; production reads
    # `.git/COMMIT_EDITMSG` (populated by git before pre-commit fires).
    msg_file = argv[1] if len(argv) > 1 else os.environ.get("COMMIT_EDITMSG_PATH", "")
    root = _project_root()

    # Step 1 — load active claims (FrontmatterParseError handled below).
    try:
        # In Progress sprints are unconditionally active. Planned sprints
        # are active iff their plan file is tracked (committed).
        in_progress = read_active_claims(root, statuses=("In Progress",))
        planned_all = read_active_claims(root, statuses=("Planned",))
    except FrontmatterParseError as exc:
        print(f"[pre-commit] REFUSE: malformed frontmatter — {exc}", file=sys.stderr)
        print(
            "  Fix the YAML or use `git commit --no-verify` "
            "with an entry in `workspace/git-bypass-log.txt`.",
            file=sys.stderr,
        )
        return 1
    planned_tracked = [
        c for c in planned_all
        if _is_tracked(root, str(c.path.relative_to(root)))
    ]
    claims = list(in_progress) + planned_tracked

    # Step 2 — commit-message context.
    commit_msg = _read_commit_message(msg_file, root)
    if not commit_msg.strip():
        print(
            "[pre-commit] empty commit-message context (rebase apply / amend / "
            "merge?), skipping cross-sprint claim checks.",
            file=sys.stderr,
        )
        return 0

    own_sprint = _extract_sprint_id(commit_msg)
    if own_sprint is None:
        # Recognised generic prefix (e.g. `chore: ...`) → allow with note.
        first_line = commit_msg.splitlines()[0]
        if _GENERIC_PREFIX_RE.match(first_line):
            print(
                "[pre-commit] no SP_NNN prefix detected; "
                "cross-sprint claim-check skipped (hygiene/cross-cutting commit).",
                file=sys.stderr,
            )
        else:
            print(
                "[pre-commit] unconventional commit-message format; "
                "cross-sprint claim-check skipped. Recommend "
                "`<type>(SP_NNN): <subject>` for sprint-scoped commits.",
                file=sys.stderr,
            )

    # Step 3-4 — staged-file scan.
    # Stage-5 MEDIUM-1 fix: count `unclaimed_count` regardless of
    # `own_sprint` so the sweep heuristic still fires on unconventional
    # commit messages (the highest-risk attack vector — `git add -A` +
    # `WIP` message would otherwise dodge the warning entirely).
    staged = _staged_files(root)
    refusals: list[str] = []
    unclaimed_count = 0
    # SP_956 — memoise plan age per plan-path across the whole commit so a zombie
    # co-claiming many staged paths is `git log`-ed once, not once per path.
    age_cache: dict[str, Optional[int]] = {}
    # SP_957 — memoise tracked-file count per claim PREFIX across the whole commit
    # so a hot over-broad prefix (`scenarios/`) is `git ls-files`-ed once.
    broad_cache: dict[str, int] = {}
    for path in staged:
        if path in OVERLAP_IGNORE_PATHS:
            continue  # Rule-7 meta-docs — any sprint can touch
        if own_sprint is not None:
            foreign = _foreign_claim_match(
                path, own_sprint, claims, root, age_cache, broad_cache
            )
            if foreign is not None:
                refusals.append(
                    f"  {path} is claimed by {foreign.sprint_id} "
                    f"(touches_paths: {list(foreign.touches_paths)})"
                )
                continue
            if not _is_own_sprint_claim(path, own_sprint, claims):
                unclaimed_count += 1
        else:
            # No own sprint scope → every non-meta staged file is
            # "unclaimed" relative to the heuristic.
            unclaimed_count += 1

    if refusals:
        print(
            f"[pre-commit] REFUSE: {len(refusals)} staged file(s) claimed by "
            f"another active sprint:",
            file=sys.stderr,
        )
        for line in refusals:
            print(line, file=sys.stderr)
        print(
            "  Drop these from staging (`git restore --staged <path>`) or "
            "coordinate with the claiming sprint.",
            file=sys.stderr,
        )
        print(
            "  Bypass: `git commit --no-verify` + entry in "
            "`workspace/git-bypass-log.txt`.",
            file=sys.stderr,
        )
        return 1

    # Step 5 — sweep heuristic (non-blocking warning).
    if len(staged) > SWEEP_TOTAL and unclaimed_count > SWEEP_UNCLAIMED:
        scope = (
            f"outside {own_sprint}'s claimed paths"
            if own_sprint is not None
            else "with no SP_NNN scope"
        )
        print(
            f"[pre-commit] WARNING: sweep heuristic — {len(staged)} files staged, "
            f"{unclaimed_count} {scope}. "
            f"Likely accidental `git add -A`; verify with `git diff --cached --stat`.",
            file=sys.stderr,
        )

    # Step 6 — plan-first-commit guard. Only trigger on untracked plan
    # for the commit's own SP_NNN.
    if own_sprint is not None:
        untracked_plan = _untracked_plan_for_sprint(root, own_sprint)
        if untracked_plan is not None:
            rel = untracked_plan.relative_to(root)
            print(
                f"[pre-commit] REFUSE: plan-first-commit rule (Rule 6 step 2). "
                f"Plan file `{rel}` is untracked — commit it FIRST as "
                f"`docs({own_sprint}): plan — <one-line goal>` before "
                f"committing other work for {own_sprint}.",
                file=sys.stderr,
            )
            print(
                "  This protects the plan from destructive working-tree sweeps.",
                file=sys.stderr,
            )
            return 1

    # Step 7 — inbox-check (SP_301). When the commit's own SP_NNN has open
    # entries in workspace/agent_inbox/<own_sprint>.md, refuse unless every
    # open timestamp appears in an `Acknowledges-inbox:` trailer.
    if own_sprint is not None:
        open_timestamps = _open_inbox_timestamps(root, own_sprint)
        if open_timestamps:
            acked = _commit_acknowledged_timestamps(commit_msg)
            unacknowledged = [ts for ts in open_timestamps if ts not in acked]
            if unacknowledged:
                print(
                    f"[pre-commit] REFUSE: {len(unacknowledged)} open inbox "
                    f"entry/entries addressed to {own_sprint} not acknowledged:",
                    file=sys.stderr,
                )
                for ts in unacknowledged:
                    print(f"  {ts} (workspace/agent_inbox/{own_sprint}.md)", file=sys.stderr)
                print(
                    "  Either resolve in this commit (flip `open` → "
                    "`resolved (SP_<your>)` in the inbox file) or defer "
                    "explicitly via:",
                    file=sys.stderr,
                )
                print(
                    f"    Acknowledges-inbox: {', '.join(unacknowledged)}",
                    file=sys.stderr,
                )
                print(
                    "  in the commit message body (separate paragraph). "
                    "Bypass: `--no-verify` + workspace/git-bypass-log.txt entry.",
                    file=sys.stderr,
                )
                return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
