#!/usr/bin/env bash
# Generic repository invariant linter.
#
# Projects should extend this file with domain-specific invariants. The default
# checks are intentionally portable.
set -euo pipefail

ROOT="${1:-$(pwd)}"
SRC="${ROOT}/src"
FAIL=0

if [ ! -d "${SRC}" ]; then
  echo "lint-invariants: src/ not found at ${SRC}; nothing to lint"
  exit 0
fi

# Refuse string-literal caller branches in tool/skill handlers. Caller
# identity may be used for attribution and caller-vs-resource ownership checks,
# but behavior should be driven by data policy instead of hardcoded names.
CALLER_BRANCH_PATTERN='(if|switch)[^[:cntrl:]]{0,120}(agent_id|agentId|caller_id|callerId|principal_id|principalId)[^[:cntrl:]]{0,80}(===|==|case)[^[:cntrl:]]*['"'"'"][A-Za-z0-9_.:-]+['"'"'"]'
CALLER_HITS=$(grep -RnE --include='*.ts' --include='*.tsx' --include='*.js' --include='*.py' \
  "${CALLER_BRANCH_PATTERN}" "${SRC}" || true)

if [ -n "${CALLER_HITS}" ]; then
  echo "lint-invariants: hardcoded caller-identity branch found:" >&2
  echo "${CALLER_HITS}" >&2
  echo "Use data-driven policy and shared authorization hooks." >&2
  FAIL=1
fi

# Refuse positive instructions asking users to paste secrets into chat or
# tracked docs. Negative guidance such as "never paste a token" is allowed.
SECRET_REQUEST_PATTERN='(paste|type|enter|send|share|message)[^[:cntrl:]]{0,80}(api[ _-]?key|token|secret|credential|password)[^[:cntrl:]]{0,80}(chat|message|here|thread)|((api[ _-]?key|token|secret|credential|password)[^[:cntrl:]]{0,80}(paste|type|enter|send|share|message)[^[:cntrl:]]{0,80}(chat|message|here|thread))'
SECRET_ALLOW_PATTERN='never|do not|don'\''t|must not|must never|refuse|forbidden|out-of-band|one-time|upload form|environment variable|secret manager'
SECRET_HITS=""
while IFS= read -r file; do
  line_no=0
  while IFS= read -r line || [ -n "${line}" ]; do
    line_no=$((line_no + 1))
    if printf '%s\n' "${line}" | grep -Eiq "${SECRET_REQUEST_PATTERN}"; then
      if ! printf '%s\n' "${line}" | grep -Eiq "${SECRET_ALLOW_PATTERN}"; then
        SECRET_HITS="${SECRET_HITS}${file#${ROOT}/}:${line_no}: ${line}"$'\n'
      fi
    fi
  done < "${file}"
done < <(find "${ROOT}" -path "${ROOT}/.git" -prune -o -path "${ROOT}/.venv" -prune -o \( -name '*.md' -o -name '*.ts' -o -name '*.tsx' -o -name '*.js' -o -name '*.py' \) -type f -print)

if [ -n "${SECRET_HITS}" ]; then
  echo "lint-invariants: credential prompt anti-pattern found:" >&2
  echo "${SECRET_HITS}" >&2
  echo "Route secrets through a secret manager, environment setup, or approved upload flow." >&2
  FAIL=1
fi

if [ "${FAIL}" -eq 0 ]; then
  echo "lint-invariants: clean"
fi

exit "${FAIL}"
