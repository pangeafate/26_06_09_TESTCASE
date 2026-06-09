# shellcheck shell=bash
# Single source of truth for the docs-only paths-ignore regex.
#
# This bash library exports the docs-exclusion regex used by:
#   - CI/deploy workflow changed-file classifiers.
#   - validators/_diff_scope.py.
#   - optional parity tests.
#
# A Python copy lives at `validators/_diff_scope.py:34` (`DOC_EXCLUDE_RE`).
# Different language; we can't source bash from Python — the parity test
# enforces equality across all three representations (bash sourced lib +
# Python `_diff_scope.DOC_EXCLUDE_RE` + a hard-coded golden literal).
#
# CALLER POSTURE: this library does NOT call `set -u`/`set -e`/`set -o pipefail`
# itself; callers own posture. Both production callers (deploy.yml:46,
# ci.yml:56) already run with `set -uo pipefail`. The lib references only
# its own locals + the guard sentinel; no unbound deref under `-u`.
#
# IDEMPOTENT SOURCE: wrap-once guarded by DEV_DOCS_ONLY_PATHS_LIB_LOADED.
# `readonly DOCS_ONLY_PATHS_REGEX` would otherwise fail on the second
# `source` (read-only re-assignment). Guard checks before re-assignment.

if [[ -z "${DEV_DOCS_ONLY_PATHS_LIB_LOADED:-}" ]]; then
  # The literal regex. ANY change here REQUIRES same-PR-edit of
  # validators/_diff_scope.py:34 + the hard-coded golden literal in
  # test/shell/docs-only-paths-parity.test.sh (3-way parity invariant).
  readonly DOCS_ONLY_PATHS_REGEX='(^|/)[^/]+\.md$|^docs/|^workspace/|^rules/|^principles/'

  # is_path_docs_only <path> → rc 0 if path matches the docs-only regex
  # (i.e. docs-only file), rc 1 otherwise.
  is_path_docs_only() {
    local path="$1"
    printf '%s\n' "$path" | grep -qE "$DOCS_ONLY_PATHS_REGEX"
  }

  readonly DEV_DOCS_ONLY_PATHS_LIB_LOADED=1
fi
