#!/usr/bin/env bash
# Tests for scripts/git-hooks/pre-push.py and scripts/install-git-hooks.sh.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")"/.. && pwd)"
HOOK="$REPO_ROOT/scripts/git-hooks/pre-push.py"
INSTALLER="$REPO_ROOT/scripts/install-git-hooks.sh"

PASS=0
FAIL=0

for f in "$HOOK" "$INSTALLER"; do
  if [ ! -f "$f" ]; then
    echo "test_pre_push: subject under test missing: $f" >&2
    exit 2
  fi
done

init_repo() {
  local repo="$1"
  git init --quiet -b main "$repo"
  git -C "$repo" config user.email "test@example.com"
  git -C "$repo" config user.name "Test"
  git -C "$repo" config commit.gpgsign false
  echo "test" >"$repo/README.md"
  git -C "$repo" add README.md
  git -C "$repo" commit --quiet -m "init"
}

assert_rc() {
  local got="$1" want="$2" label="$3"
  if [ "$got" -ne "$want" ]; then
    echo "  FAIL $label: expected exit $want, got $got" >&2
    FAIL=$((FAIL + 1))
    return 1
  fi
  echo "  PASS $label"
  PASS=$((PASS + 1))
}

assert_substr() {
  local haystack="$1" needle="$2" label="$3"
  if [[ "$haystack" != *"$needle"* ]]; then
    echo "  FAIL $label: missing '$needle'" >&2
    echo "    output: $haystack" >&2
    FAIL=$((FAIL + 1))
    return 1
  fi
  echo "  PASS $label"
  PASS=$((PASS + 1))
}

echo "Test 1: install idempotency"
test_install_idempotency() {
  local tmp rc1 rc2
  tmp=$(mktemp -d)
  init_repo "$tmp"
  mkdir -p "$tmp/scripts/git-hooks"
  cp "$REPO_ROOT/scripts/git-hooks/pre-commit.py" "$tmp/scripts/git-hooks/"
  cp "$REPO_ROOT/scripts/git-hooks/commit-msg.py" "$tmp/scripts/git-hooks/"
  cp "$HOOK" "$tmp/scripts/git-hooks/"
  cp "$INSTALLER" "$tmp/scripts/install-git-hooks.sh"
  chmod +x "$tmp/scripts/install-git-hooks.sh"
  set +e
  (cd "$tmp" && bash scripts/install-git-hooks.sh) >/dev/null 2>&1
  rc1=$?
  (cd "$tmp" && bash scripts/install-git-hooks.sh) >/dev/null 2>&1
  rc2=$?
  set -e
  rm -rf "$tmp"
  assert_rc $rc1 0 "first install exits 0"
  assert_rc $rc2 0 "second install exits 0"
}
test_install_idempotency

echo "Test 2: injected typecheck failure refuses"
test_typecheck_failure_refuses() {
  local tmp local_sha out rc
  tmp=$(mktemp -d)
  init_repo "$tmp"
  cat >"$tmp/package.json" <<'JSON'
{"scripts":{"typecheck":"echo typecheck"}}
JSON
  local_sha=$(git -C "$tmp" rev-parse HEAD)
  set +e
  out=$(echo "refs/heads/main $local_sha refs/heads/main $local_sha" \
    | (cd "$tmp" && env DEV_PREPUSH_TEST_FAIL_STEP=typecheck python3 "$HOOK") 2>&1)
  rc=$?
  set -e
  rm -rf "$tmp"
  assert_rc $rc 1 "typecheck failure exits 1"
  assert_substr "$out" "FAIL: typecheck" "stderr names failing step"
}
test_typecheck_failure_refuses

echo "Test 3: bypass without reason refuses"
test_bypass_no_reason() {
  local tmp local_sha out rc
  tmp=$(mktemp -d)
  init_repo "$tmp"
  local_sha=$(git -C "$tmp" rev-parse HEAD)
  set +e
  out=$(echo "refs/heads/main $local_sha refs/heads/main $local_sha" \
    | (cd "$tmp" && env DEV_PREPUSH_BYPASS=1 python3 "$HOOK") 2>&1)
  rc=$?
  set -e
  rm -rf "$tmp"
  assert_rc $rc 1 "empty bypass reason exits 1"
  assert_substr "$out" "BYPASS REJECTED" "stderr explains bypass refusal"
}
test_bypass_no_reason

echo "Test 4: bypass with reason logs"
test_bypass_with_reason() {
  local tmp local_sha out rc
  tmp=$(mktemp -d)
  init_repo "$tmp"
  local_sha=$(git -C "$tmp" rev-parse HEAD)
  set +e
  out=$(echo "refs/heads/main $local_sha refs/heads/main $local_sha" \
    | (cd "$tmp" && env DEV_PREPUSH_BYPASS=1 DEV_PREPUSH_BYPASS_REASON=testing DEV_PREPUSH_BYPASS_APPROVED_BY=operator python3 "$HOOK") 2>&1)
  rc=$?
  set -e
  assert_rc $rc 0 "bypass with reason exits 0"
  assert_substr "$out" "BYPASS" "stderr confirms bypass"
  if [ ! -f "$tmp/workspace/git-bypass-log.txt" ]; then
    echo "  FAIL bypass log created" >&2
    FAIL=$((FAIL + 1))
  else
    echo "  PASS bypass log created"
    PASS=$((PASS + 1))
  fi
  rm -rf "$tmp"
}
test_bypass_with_reason

echo "Test 5: noop gauntlet passes"
test_noop_gauntlet() {
  local tmp local_sha out rc
  tmp=$(mktemp -d)
  init_repo "$tmp"
  cat >"$tmp/package.json" <<'JSON'
{"scripts":{"typecheck":"echo typecheck","test":"echo test"}}
JSON
  mkdir -p "$tmp/validators"
  printf 'import sys\nsys.exit(0)\n' >"$tmp/validators/run_all.py"
  local_sha=$(git -C "$tmp" rev-parse HEAD)
  set +e
  out=$(echo "refs/heads/main $local_sha refs/heads/main $local_sha" \
    | (cd "$tmp" && env DEV_PREPUSH_TEST_NOOP_STEPS=1 python3 "$HOOK") 2>&1)
  rc=$?
  set -e
  rm -rf "$tmp"
  assert_rc $rc 0 "noop gauntlet exits 0"
  assert_substr "$out" "NOOP: typecheck" "noop reaches typecheck"
  assert_substr "$out" "NOOP: validators/run_all.py" "noop reaches validators"
  assert_substr "$out" "NOOP: npm test" "noop reaches npm test"
}
test_noop_gauntlet

echo
echo "test_pre_push: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
