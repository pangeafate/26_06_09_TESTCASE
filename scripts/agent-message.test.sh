#!/usr/bin/env bash
# scripts/agent-message.test.sh — bash test suite for agent-message.sh (SP_301).
#
# Runs against an isolated temp git repo so the script's `git rev-parse` finds
# a stable root and the inbox dir is sandboxed. Exit 0 on all pass; exit 1 on
# first failure with diagnostic.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/agent-message.sh"

[[ -x "$SCRIPT" ]] || { echo "test setup: $SCRIPT not executable" >&2; exit 1; }

TMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TMP_ROOT"' EXIT

cd "$TMP_ROOT"
git init -q .
git -c user.email=test@test -c user.name=test commit --allow-empty -m "init" -q

PASS=0
FAIL=0

check() {
  local name="$1" actual="$2" expected="$3"
  if [[ "$actual" == "$expected" ]]; then
    PASS=$((PASS + 1))
  else
    FAIL=$((FAIL + 1))
    echo "FAIL: $name" >&2
    echo "  expected: $expected" >&2
    echo "  actual:   $actual" >&2
  fi
}

# T1 — usage on no args
out=$("$SCRIPT" 2>&1 || true)
case "$out" in *"Usage:"*) PASS=$((PASS + 1));; *) FAIL=$((FAIL + 1)); echo "FAIL T1: usage on no args" >&2;; esac

# T2 — send with bad from-SP rejected
ec=0
echo body | "$SCRIPT" send notSP SP_222 "subject" >/dev/null 2>&1 || ec=$?
check "T2 send bad from-SP exits 2" "$ec" "2"

# T3 — send happy path creates inbox file with header
ec=0
echo "body line 1" | "$SCRIPT" send SP_111 SP_222 "first message" >/dev/null 2>&1 || ec=$?
check "T3 send exit 0" "$ec" "0"
[[ -f "workspace/agent_inbox/SP_222.md" ]] || { FAIL=$((FAIL + 1)); echo "FAIL T3: inbox file not created" >&2; }
grep -q '^# Inbox: SP_222$' workspace/agent_inbox/SP_222.md || { FAIL=$((FAIL + 1)); echo "FAIL T3: header line missing" >&2; }
grep -q '^## .* — from SP_111 — open$' workspace/agent_inbox/SP_222.md || { FAIL=$((FAIL + 1)); echo "FAIL T3: open entry heading missing" >&2; }
grep -q '\*\*Subject\*\*: first message$' workspace/agent_inbox/SP_222.md || { FAIL=$((FAIL + 1)); echo "FAIL T3: subject line missing" >&2; }
grep -q '^body line 1$' workspace/agent_inbox/SP_222.md || { FAIL=$((FAIL + 1)); echo "FAIL T3: body missing" >&2; }
PASS=$((PASS + 4))  # accumulate for the four greps above (each contributes a pass when not failing)

# T4 — check on populated inbox exits 1
ec=0
"$SCRIPT" check SP_222 >/dev/null 2>&1 || ec=$?
check "T4 check open exits 1" "$ec" "1"

# T5 — check on missing-file SP exits 0
ec=0
"$SCRIPT" check SP_999 >/dev/null 2>&1 || ec=$?
check "T5 check missing exits 0" "$ec" "0"

# T6 — flip open → resolved; check now exits 0
sed -i.bak 's/ — open$/ — resolved (SP_111)/' workspace/agent_inbox/SP_222.md
rm workspace/agent_inbox/SP_222.md.bak
ec=0
"$SCRIPT" check SP_222 >/dev/null 2>&1 || ec=$?
check "T6 check after resolve exits 0" "$ec" "0"

# T7 — second send appends; check exits 1 again
echo "body line 2" | "$SCRIPT" send SP_111 SP_222 "second message" >/dev/null 2>&1
open_count=$(grep -c '^## .* — open$' workspace/agent_inbox/SP_222.md 2>/dev/null || true)
open_count="${open_count:-0}"
check "T7 second send adds 1 open entry" "$open_count" "1"
ec=0
"$SCRIPT" check SP_222 >/dev/null 2>&1 || ec=$?
check "T7 check after second send exits 1" "$ec" "1"

# T8 — range send routes to lowest number
echo body3 | "$SCRIPT" send SP_111 SP_273-279 "range subject" >/dev/null 2>&1
[[ -f "workspace/agent_inbox/SP_273.md" ]] || { FAIL=$((FAIL + 1)); echo "FAIL T8: range routing" >&2; }
grep -q '^# Inbox: SP_273$' workspace/agent_inbox/SP_273.md || { FAIL=$((FAIL + 1)); echo "FAIL T8: range header" >&2; }
PASS=$((PASS + 2))

# T9 — list-all enumerates with counts
out=$("$SCRIPT" list-all 2>&1)
echo "$out" | grep -q '^SP_222' || { FAIL=$((FAIL + 1)); echo "FAIL T9: SP_222 listed" >&2; }
echo "$out" | grep -q '^SP_273' || { FAIL=$((FAIL + 1)); echo "FAIL T9: SP_273 listed" >&2; }
PASS=$((PASS + 2))

# T10 — check rejects malformed SP arg
ec=0
"$SCRIPT" check notSP >/dev/null 2>&1 || ec=$?
check "T10 check bad SP exits 2" "$ec" "2"

echo "---"
echo "PASS: $PASS"
echo "FAIL: $FAIL"
[[ "$FAIL" -eq 0 ]] || exit 1
