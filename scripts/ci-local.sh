#!/usr/bin/env bash
# Generic local CI gauntlet.
#
# Runs common checks when their project files are present. Projects can extend
# or replace this script after copying the scaffold.
#
# Env vars:
#   DEV_CILOCAL_SKIP_INSTALL=1       Skip dependency installation.
#   DEV_CILOCAL_TEST_NOOP_STEPS=1    Print steps without executing them.
#   DEV_CILOCAL_VENV=.venv           Python venv path when none is active.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

STEP_N=0

run_step() {
  local label="$1"
  shift
  STEP_N=$((STEP_N + 1))
  echo "[ci:local] ${STEP_N} ${label}"
  if [[ "${DEV_CILOCAL_TEST_NOOP_STEPS:-0}" == "1" ]]; then
    echo "  ... noop (DEV_CILOCAL_TEST_NOOP_STEPS=1)"
    return 0
  fi
  "$@"
}

maybe_npm_install() {
  if [[ ! -f package.json ]]; then
    echo "  ... skipped (no package.json)"
    return 0
  fi
  if [[ "${DEV_CILOCAL_SKIP_INSTALL:-0}" == "1" ]]; then
    echo "  ... skipped (DEV_CILOCAL_SKIP_INSTALL=1)"
    return 0
  fi
  if [[ -f package-lock.json ]]; then
    npm ci
  else
    npm install
  fi
}

maybe_python_deps() {
  if [[ ! -f requirements.txt ]]; then
    echo "  ... skipped (no requirements.txt)"
    return 0
  fi
  if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    local venv_path="${DEV_CILOCAL_VENV:-.venv}"
    if [[ ! -x "${venv_path}/bin/python3" ]]; then
      python3 -m venv "$venv_path"
    fi
    # shellcheck source=/dev/null
    source "${venv_path}/bin/activate"
  fi
  python3 -m pip install --upgrade pip --quiet
  python3 -m pip install -r requirements.txt --quiet
}

maybe_npm_typecheck() {
  if [[ -f package.json ]] && npm run | grep -qE '(^|[[:space:]])typecheck($|[[:space:]])'; then
    npm run typecheck
  else
    echo "  ... skipped (no npm typecheck script)"
  fi
}

maybe_npm_test() {
  if [[ -f package.json ]] && npm run | grep -qE '(^|[[:space:]])test($|[[:space:]])'; then
    npm test
  else
    echo "  ... skipped (no npm test script)"
  fi
}

maybe_python_tests() {
  if find . -path './.venv' -prune -o -name 'test_*.py' -print -quit | grep -q .; then
    python3 -m unittest discover -p 'test_*.py' -v
  else
    echo "  ... skipped (no Python unittest files)"
  fi
}

maybe_shellcheck() {
  if ! command -v shellcheck >/dev/null 2>&1; then
    echo "  ... skipped (shellcheck not installed)"
    return 0
  fi
  local files
  files="$(find scripts -name '*.sh' -print 2>/dev/null || true)"
  if [[ -z "$files" ]]; then
    echo "  ... skipped (no shell scripts)"
    return 0
  fi
  # shellcheck disable=SC2086
  shellcheck -S error $files
}

run_step "Dependency install" maybe_npm_install
run_step "Python dependencies" maybe_python_deps
if [[ -f scripts/dev-gateway.py ]]; then
  run_step "Local development gateway" python3 scripts/dev-gateway.py . --stage manual
else
  run_step "Typecheck" maybe_npm_typecheck
  run_step "Shell lint" maybe_shellcheck
  run_step "Python tests" maybe_python_tests
  run_step "JavaScript tests" maybe_npm_test
  run_step "Repository validators" python3 validators/run_all.py .
fi

echo "[ci:local] all green"
