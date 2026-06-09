#!/usr/bin/env bash
# scripts/agent-message.sh — agent-to-agent inbox CLI (SP_301).
#
# Per-sprint mailbox under workspace/agent_inbox/SP_NNN.md. Each entry is an
# append-only markdown block with status `open` or `resolved (SP_<your>)`.
# The commit-msg hook gates SP_NNN-scoped commits on outstanding open entries
# in the recipient's inbox file; agents either resolve in-line, defer via an
# `Acknowledges-inbox: <timestamp>` trailer in the commit message, or use
# --no-verify with a workspace/git-bypass-log.txt entry.
#
# Subcommands:
#   send <from-SP> <to-SP> <subject>     stdin → appended entry
#   check <my-SP>                        exit 0 if no open; exit 1 if open
#   list-all                             open-entry counts per SP file

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
INBOX_DIR="${REPO_ROOT}/workspace/agent_inbox"

# SP_NNN format: literal SP_ then 1+ digits, optional trailing -NNN range
# (e.g. SP_273-279 → routed to SP_273; range tail kept in the from line).
SP_RE='^SP_[0-9]+([-_][0-9]+)?$'

usage() {
  cat >&2 <<'EOF'
Usage:
  agent-message.sh send <from-SP> <to-SP> <subject>
      Reads body from stdin, appends a dated `open` entry to
      workspace/agent_inbox/<to-SP>.md.

  agent-message.sh check <my-SP>
      Lists open entries in workspace/agent_inbox/<my-SP>.md to stderr.
      Exit 0 if no open entries (or file missing); exit 1 if any exist.

  agent-message.sh list-all
      Prints each inbox file with its open-entry count. Exit 0 always.

SP format: SP_NNN or SP_NNN-MMM (range; routes to lowest number).
EOF
  exit 2
}

normalise_to_sp() {
  # Range like SP_273-279 → SP_273 for routing; otherwise pass through.
  local raw="$1"
  if [[ "$raw" =~ ^(SP_[0-9]+)[-_][0-9]+$ ]]; then
    echo "${BASH_REMATCH[1]}"
  else
    echo "$raw"
  fi
}

cmd_send() {
  [[ $# -ge 3 ]] || usage
  local from_sp="$1" to_sp_raw="$2" subject="$3"

  [[ "$from_sp" =~ $SP_RE ]] || { echo "agent-message: from-SP '$from_sp' must match SP_NNN[-NNN]" >&2; exit 2; }
  [[ "$to_sp_raw" =~ $SP_RE ]] || { echo "agent-message: to-SP '$to_sp_raw' must match SP_NNN[-NNN]" >&2; exit 2; }
  [[ -n "$subject" ]] || { echo "agent-message: subject must be non-empty" >&2; exit 2; }

  local to_sp file timestamp body file_existed
  to_sp="$(normalise_to_sp "$to_sp_raw")"
  mkdir -p "$INBOX_DIR"
  file="${INBOX_DIR}/${to_sp}.md"
  timestamp="$(date -u +%Y-%m-%dT%H:%MZ)"
  body="$(cat)"

  # Capture file-existed state BEFORE the redirection block; the >>
  # redirection creates the file before any [[ -f ]] inside the block runs.
  if [[ -f "$file" ]]; then file_existed=1; else file_existed=0; fi

  {
    if [[ "$file_existed" -eq 0 ]]; then
      printf '# Inbox: %s\n\nMessages addressed to sprint %s. Each entry is open until the recipient sprint flips its heading to `resolved (SP_<theirs>)`. Append-only.\n' "$to_sp" "$to_sp"
    fi
    printf '\n## %s — from %s — open\n\n**Subject**: %s\n\n%s\n\n**Acknowledge**: change `open` → `resolved (SP_<your>)` in the heading above when addressed; reference the resolving commit SHA if relevant.\n' \
      "$timestamp" "$from_sp" "$subject" "$body"
  } >> "$file"

  echo "Filed: ${file}  ($timestamp from $from_sp)"
}

cmd_check() {
  [[ $# -ge 1 ]] || usage
  local my_sp_raw="$1"
  [[ "$my_sp_raw" =~ $SP_RE ]] || { echo "agent-message: SP '$my_sp_raw' must match SP_NNN[-NNN]" >&2; exit 2; }

  local my_sp file
  my_sp="$(normalise_to_sp "$my_sp_raw")"
  file="${INBOX_DIR}/${my_sp}.md"

  if [[ ! -f "$file" ]]; then
    return 0
  fi

  # Open entry headings end with " — open" (em-dash + open).
  local open_count
  open_count=$(grep -c '^## .* — open$' "$file" 2>/dev/null || true)
  open_count="${open_count:-0}"

  if [[ "$open_count" -eq 0 ]]; then
    return 0
  fi

  {
    echo "INBOX ${my_sp}: ${open_count} open entry/entries — address before committing SP_NNN-scoped work, or defer via 'Acknowledges-inbox: <timestamp>' trailer."
    grep '^## .* — open$' "$file"
  } >&2
  return 1
}

cmd_list_all() {
  if [[ ! -d "$INBOX_DIR" ]]; then
    echo "(no inbox directory)"
    return 0
  fi

  local found=0 f sp open
  for f in "$INBOX_DIR"/SP_*.md; do
    [[ -f "$f" ]] || continue
    found=1
    sp="$(basename "$f" .md)"
    open=$(grep -c '^## .* — open$' "$f" 2>/dev/null || true)
    open="${open:-0}"
    printf '%-12s  %d open\n' "$sp" "$open"
  done
  if [[ "$found" -eq 0 ]]; then
    echo "(no inbox files)"
  fi
}

cmd="${1:-}"
[[ -n "$cmd" ]] || usage
shift

case "$cmd" in
  send)     cmd_send "$@" ;;
  check)    cmd_check "$@" ;;
  list-all) cmd_list_all "$@" ;;
  -h|--help|help) usage ;;
  *)        echo "agent-message: unknown subcommand '$cmd'" >&2; usage ;;
esac
