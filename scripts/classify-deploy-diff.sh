#!/bin/bash
# Classify a deploy's changed-file set as docs_only or code.
#
# Usage: classify-deploy-diff.sh <BEFORE_SHA> <AFTER_SHA>
#
# Returns on stdout:
#   "docs_only"  iff every changed file matches the docs-only regex
#   "code"       in every other case (incl. new branch, missing args,
#                git error — fail-closed)
#
# docs-only regex includes: docs/, *.md, workspace/, rules/, and principles/.
set -uo pipefail

BEFORE="${1:-}"
AFTER="${2:-}"

# Missing AFTER_SHA: can't compute a diff. Fail-closed.
if [ -z "$AFTER" ]; then
  echo "code"
  exit 0
fi

# Missing or zero BEFORE_SHA: new branch, force-push, or first commit.
# We cannot reason about the diff; assume code-touching.
if [ -z "$BEFORE" ] || [ "$BEFORE" = "0000000000000000000000000000000000000000" ]; then
  echo "code"
  exit 0
fi

# Run the diff. On any git error, fail-closed to "code".
CHANGED=$(git diff --name-only "$BEFORE..$AFTER" 2>/dev/null) || {
  echo "code"
  exit 0
}

# If there are no changes at all (rare; reflective deploy of same SHA),
# still report "code" — the regression sweep should run on retry.
if [ -z "$CHANGED" ]; then
  echo "code"
  exit 0
fi

# Filter out the docs-class entries; anything remaining is code.
NON_DOCS=$(echo "$CHANGED" | grep -Ev '^(docs/|.*\.md$|workspace/|rules/|principles/)' || true)
if [ -z "$NON_DOCS" ]; then
  echo "docs_only"
else
  echo "code"
fi
