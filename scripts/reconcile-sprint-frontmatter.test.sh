#!/usr/bin/env bash
#
# SP_082 — Regression tests for scripts/reconcile-sprint-frontmatter.py.
#
# Builds a disposable git repo with a realistic scenario and asserts the
# reconciler produces the expected frontmatter.
#
# Scenarios covered:
#   1. false/false sprint frontmatter + a diff that does NOT touch
#      DATA_SCHEMA / CODEBASE_STRUCTURE → reconciler no-op.
#   2. true/true frontmatter + diff that does NOT touch those files →
#      reconciler flips to false/false (the recurring CI failure mode).
#   3. false/false frontmatter + diff that DOES touch those files →
#      reconciler flips to true/true.
#   4. PROGRESS.md content edit without last-reconciled bump → reconciler
#      bumps to today.
#   5. Future-dated current marker with a same-day sprint diff base →
#      reconciler resets to a date that is still newer than the base marker.
#   6. Future-dated diff-base marker with an already-corrected current
#      marker → reconciler keeps today instead of ratcheting forward.
#   7. No active sprint in PROGRESS.md → reconciler exits 0 with a
#      "nothing to do" message.
#
# Usage: scripts/reconcile-sprint-frontmatter.test.sh

set -euo pipefail

SCRIPT="$(cd "$(dirname "$0")" && pwd)/reconcile-sprint-frontmatter.py"

if [ ! -f "${SCRIPT}" ]; then
  echo "test: reconciler not found at ${SCRIPT}" >&2
  exit 2
fi

# Minimal validate_doc_freshness.py fixture copy so the reconciler's
# sys.path insert can resolve it. We'll copy the real validator into the
# fixture's validators/ subdir.
REAL_VALIDATOR="$(cd "$(dirname "$0")/.." && pwd)/validators/validate_doc_freshness.py"
# SP_719 — validate_doc_freshness.py now does `from _common import
# find_active_sprint`; the fixture must vendor _common.py too or the
# synthetic-repo validator import fails (ModuleNotFoundError: _common).
REAL_COMMON="$(cd "$(dirname "$0")/.." && pwd)/validators/_common.py"
# SP_736 — validate_doc_freshness.py also does `from _diff_scope import
# scope_gate`; vendor _diff_scope.py too or the synthetic-repo validator
# import fails (ModuleNotFoundError: _diff_scope).
REAL_DIFF_SCOPE="$(cd "$(dirname "$0")/.." && pwd)/validators/_diff_scope.py"

mk_fixture_repo() {
  # $1 = initial sprint frontmatter, $2 = meta-doc deltas from baseline
  local tmp
  tmp=$(mktemp -d)
  cd "${tmp}"

  # Stand up a minimal repo the validator helpers will recognize.
  git init -q
  git config user.email "test@example.local"
  git config user.name "SP_082 test"

  mkdir -p workspace/sprints validators scripts
  cp "${REAL_VALIDATOR}" validators/validate_doc_freshness.py
  cp "${REAL_COMMON}" validators/_common.py  # SP_719 import dep
  cp "${REAL_DIFF_SCOPE}" validators/_diff_scope.py  # SP_736 import dep

  # Empty baseline meta-docs.
  cat > PROGRESS.md <<'EOF'
---
status: living
last-reconciled: 2026-04-01
authoritative-for: [active-sprint, sprint-history]
---

# Progress

## Active Sprint

**Current:** SP_999
**Started:** 2026-04-20
**Stage:** Implementation
EOF
  cat > DATA_SCHEMA.md <<'EOF'
---
last-reconciled: 2026-04-01
---
# Data Schema baseline.
EOF
  cat > CODEBASE_STRUCTURE.md <<'EOF'
---
last-reconciled: 2026-04-01
---
# Structure baseline.
EOF
  cat > FEATURE_LIST.md <<'EOF'
---
last-reconciled: 2026-04-01
---
# Features baseline.
EOF

  # First commit: baseline.
  git add -A && git commit -q -m "baseline"

  # Now add the sprint plan with the initial frontmatter.
  cat > workspace/sprints/SP_999.md <<EOF
---
sprint_id: SP_999
features: [F-TEST]
user_stories: []
${1}
status: In Progress
last-reconciled: 2026-04-20
---

# SP_999
EOF
  # SP_618 — existing scenarios are status: In Progress (refusal-exempt).
  # New scenarios using run_sp618_scenario explicitly set status: Complete
  # to exercise the refusal contract.
  git add workspace/sprints/SP_999.md && git commit -q -m "add SP_999 plan"

  # Apply caller-requested meta-doc deltas on top.
  eval "$2"

  echo "${tmp}"
}

run() {
  local label="$1"
  local initial="$2"
  local delta="$3"
  local expected_schema="$4"
  local expected_structure="$5"
  local expect_bump_progress="$6"

  local repo
  repo=$(mk_fixture_repo "${initial}" "${delta}")

  cd "${repo}"
  # Run reconciler.
  local out
  if ! out=$(python3 "${SCRIPT}" . 2>&1); then
    echo "✗ ${label}: reconciler exited non-zero" >&2
    echo "${out}" >&2
    cd - > /dev/null
    rm -rf "${repo}"
    return 1
  fi

  # Assert frontmatter bools.
  if ! grep -q "^schema_touched: ${expected_schema}$" workspace/sprints/SP_999.md; then
    echo "✗ ${label}: expected schema_touched=${expected_schema}, got:" >&2
    grep "schema_touched" workspace/sprints/SP_999.md >&2
    cd - > /dev/null
    rm -rf "${repo}"
    return 1
  fi
  if ! grep -q "^structure_touched: ${expected_structure}$" workspace/sprints/SP_999.md; then
    echo "✗ ${label}: expected structure_touched=${expected_structure}, got:" >&2
    grep "structure_touched" workspace/sprints/SP_999.md >&2
    cd - > /dev/null
    rm -rf "${repo}"
    return 1
  fi

  # Assert PROGRESS.md last-reconciled.
  # SP_082 forced-bump semantics: when PROGRESS.md is in the diff, the
  # value MUST strictly increase (not just "reach today"). So "yes"
  # here means "bumped past baseline"; "no" means "unchanged".
  local progress_date
  progress_date=$(grep "^last-reconciled:" PROGRESS.md | head -1 | awk '{print $2}')
  case "${expect_bump_progress}" in
    yes)
      if [ "${progress_date}" = "2026-04-01" ]; then
        echo "✗ ${label}: expected PROGRESS.md last-reconciled to increase, still ${progress_date}" >&2
        cd - > /dev/null
        rm -rf "${repo}"
        return 1
      fi
      ;;
    no)
      if [ "${progress_date}" != "2026-04-01" ]; then
        echo "✗ ${label}: PROGRESS.md last-reconciled unexpectedly bumped to ${progress_date}" >&2
        cd - > /dev/null
        rm -rf "${repo}"
        return 1
      fi
      ;;
  esac

  cd - > /dev/null
  rm -rf "${repo}"
  printf '  ✓ %s\n' "${label}"
}

echo "reconcile-sprint-frontmatter regression tests:"

# Scenario 1: both false + no meta-doc change — reconciler no-op on bools;
# no touched docs so no last-reconciled bump.
run "already false/false + no meta-doc delta → no-op" \
  "schema_touched: false
structure_touched: false" \
  ":" \
  "false" "false" "no"

# Scenario 2: true/true declared + no meta-doc change — the recurring CI
# failure mode. Reconciler must flip both to false.
run "true/true + no meta-doc delta → flipped to false/false" \
  "schema_touched: true
structure_touched: true" \
  ":" \
  "false" "false" "no"

# Scenario 3: false/false declared + DATA_SCHEMA and CODEBASE_STRUCTURE
# actually edited. Reconciler must flip to true/true.
run "false/false + DATA_SCHEMA+STRUCTURE edits → flipped to true/true" \
  "schema_touched: false
structure_touched: false" \
  "echo 'adding a row' >> DATA_SCHEMA.md && echo 'new layer' >> CODEBASE_STRUCTURE.md && git add -A && git commit -q -m 'touch meta docs'" \
  "true" "true" "no"

# Scenario 4: PROGRESS.md content edited without last-reconciled bump —
# reconciler bumps it (force-bump to max(current+1day, today) to satisfy
# validator F-4 "must strictly increase on content change").
run "PROGRESS.md content edit → last-reconciled strictly increased" \
  "schema_touched: false
structure_touched: false" \
  "echo 'some update' >> PROGRESS.md && git add PROGRESS.md && git commit -q -m 'progress note'" \
  "false" "false" "yes"

# Scenario 5: PROGRESS.md content edit + current last-reconciled already
# in the future (clock skew, hand-edit, or prior reconciler bug). The
# reconciler now performs a CORRECTIVE RESET back to today rather than
# incrementing the future date forward. F-4 accepts this rollback when
# the previous value was > today.
run "future-dated last-reconciled → corrective reset to today" \
  "schema_touched: false
structure_touched: false" \
  "sed -i.bak 's/last-reconciled: 2026-04-01/last-reconciled: 2099-12-31/' PROGRESS.md && rm -f PROGRESS.md.bak && echo 'content edit' >> PROGRESS.md && git add PROGRESS.md && git commit -q -m 'future-dated progress'" \
  "false" "false" "yes"

# Scenario 6: draft-plan base already has today's marker, but the current
# file was future-dated by a prior run. Resetting directly to today would
# make F-4 see content changes without a last-reconciled bump. Reconciler
# must choose a marker newer than the diff base and validator must pass.
run_future_marker_same_day_base() {
  local tmp
  tmp=$(mktemp -d)
  cd "${tmp}"

  local today tomorrow
  today=$(python3 - <<'PY'
import datetime as dt
print(dt.date.today().isoformat())
PY
)
  tomorrow=$(python3 - <<'PY'
import datetime as dt
print((dt.date.today() + dt.timedelta(days=1)).isoformat())
PY
)

  git init -q
  git config user.email "test@example.local"
  git config user.name "SP_082 test"

  mkdir -p workspace/sprints validators scripts
  cp "${REAL_VALIDATOR}" validators/validate_doc_freshness.py
  cp "${REAL_COMMON}" validators/_common.py  # SP_719 import dep
  cp "${REAL_DIFF_SCOPE}" validators/_diff_scope.py  # SP_736 import dep

  cat > PROGRESS.md <<EOF
---
status: living
last-reconciled: ${today}
authoritative-for: [active-sprint, sprint-history]
---

# Progress

## Active Sprint

**Current:** SP_999
EOF
  cat > DATA_SCHEMA.md <<EOF
---
status: living
last-reconciled: ${today}
authoritative-for: [schema]
---

# Data Schema baseline.
EOF
  cat > CODEBASE_STRUCTURE.md <<EOF
---
status: living
last-reconciled: ${today}
authoritative-for: [directory-layout]
---

# Structure baseline.
EOF
  cat > FEATURE_LIST.md <<EOF
---
status: living
last-reconciled: ${today}
authoritative-for: [features]
---

# Features baseline.
EOF
  git add PROGRESS.md DATA_SCHEMA.md CODEBASE_STRUCTURE.md FEATURE_LIST.md validators/validate_doc_freshness.py validators/_common.py validators/_diff_scope.py
  git commit -q -m "baseline"

  cat > workspace/sprints/SP_999.md <<EOF
---
sprint_id: SP_999
features: []
user_stories: []
schema_touched: true
structure_touched: false
status: Complete
last-reconciled: ${today}
---

# SP_999
EOF
  git add workspace/sprints/SP_999.md && git commit -q -m "add SP_999 plan"

  sed -i.bak 's/last-reconciled: .*/last-reconciled: 2099-12-31/' DATA_SCHEMA.md
  rm -f DATA_SCHEMA.md.bak
  echo 'new schema note' >> DATA_SCHEMA.md
  git add DATA_SCHEMA.md && git commit -q -m "future-dated schema"

  local out
  if ! out=$(python3 "${SCRIPT}" . 2>&1); then
    echo "✗ future marker + same-day base: reconciler exited non-zero" >&2
    echo "${out}" >&2
    cd - > /dev/null
    rm -rf "${tmp}"
    return 1
  fi

  local data_date
  data_date=$(grep "^last-reconciled:" DATA_SCHEMA.md | head -1 | awk '{print $2}')
  if [ "${data_date}" != "${tomorrow}" ]; then
    echo "✗ future marker + same-day base: expected DATA_SCHEMA.md marker ${tomorrow}, got ${data_date}" >&2
    cd - > /dev/null
    rm -rf "${tmp}"
    return 1
  fi

  if ! out=$(python3 validators/validate_doc_freshness.py . --no-lockfile 2>&1); then
    echo "✗ future marker + same-day base: validator failed after reconcile" >&2
    echo "${out}" >&2
    cd - > /dev/null
    rm -rf "${tmp}"
    return 1
  fi

  cd - > /dev/null
  rm -rf "${tmp}"
  printf '  ✓ %s\n' "future marker + same-day base → bumped past base"
}

run_future_marker_same_day_base

run_future_base_already_reset_current() {
  local tmp
  tmp=$(mktemp -d)
  cd "${tmp}"

  local today tomorrow
  today=$(python3 - <<'PY'
import datetime as dt
print(dt.date.today().isoformat())
PY
)
  tomorrow=$(python3 - <<'PY'
import datetime as dt
print((dt.date.today() + dt.timedelta(days=1)).isoformat())
PY
)

  git init -q
  git config user.email "test@example.local"
  git config user.name "SP_082 test"

  mkdir -p workspace/sprints validators scripts
  cp "${REAL_VALIDATOR}" validators/validate_doc_freshness.py
  cp "${REAL_COMMON}" validators/_common.py
  cp "${REAL_DIFF_SCOPE}" validators/_diff_scope.py

  cat > PROGRESS.md <<EOF
---
status: living
last-reconciled: ${today}
authoritative-for: [active-sprint, sprint-history]
---

# Progress

## Active Sprint

**Current:** SP_999
EOF
  cat > DATA_SCHEMA.md <<EOF
---
status: living
last-reconciled: ${tomorrow}
authoritative-for: [schema]
---

# Data Schema baseline.
EOF
  cat > CODEBASE_STRUCTURE.md <<EOF
---
status: living
last-reconciled: ${today}
authoritative-for: [directory-layout]
---

# Structure baseline.
EOF
  cat > FEATURE_LIST.md <<EOF
---
status: living
last-reconciled: ${today}
authoritative-for: [features]
---

# Features baseline.
EOF
  git add PROGRESS.md DATA_SCHEMA.md CODEBASE_STRUCTURE.md FEATURE_LIST.md validators/validate_doc_freshness.py validators/_common.py validators/_diff_scope.py
  git commit -q -m "baseline with future schema marker"

  cat > workspace/sprints/SP_999.md <<EOF
---
sprint_id: SP_999
features: []
user_stories: []
schema_touched: true
structure_touched: false
status: Complete
last-reconciled: ${today}
---

# SP_999
EOF
  git add workspace/sprints/SP_999.md
  git commit -q -m "add SP_999 plan"

  sed -i.bak "s/last-reconciled: ${tomorrow}/last-reconciled: ${today}/" DATA_SCHEMA.md
  rm -f DATA_SCHEMA.md.bak
  echo 'schema note after corrective reset' >> DATA_SCHEMA.md
  git add DATA_SCHEMA.md
  git commit -q -m "reset schema marker to today"

  local out
  if ! out=$(python3 "${SCRIPT}" . 2>&1); then
    echo "✗ future base + already reset current: reconciler exited non-zero" >&2
    echo "${out}" >&2
    cd - > /dev/null
    rm -rf "${tmp}"
    return 1
  fi

  local data_date
  data_date=$(grep "^last-reconciled:" DATA_SCHEMA.md | head -1 | awk '{print $2}')
  if [ "${data_date}" != "${today}" ]; then
    echo "✗ future base + already reset current: expected DATA_SCHEMA.md marker ${today}, got ${data_date}" >&2
    cd - > /dev/null
    rm -rf "${tmp}"
    return 1
  fi

  if ! out=$(python3 validators/validate_doc_freshness.py . --no-lockfile 2>&1); then
    echo "✗ future base + already reset current: validator failed after reconcile" >&2
    echo "${out}" >&2
    cd - > /dev/null
    rm -rf "${tmp}"
    return 1
  fi

  cd - > /dev/null
  rm -rf "${tmp}"
  printf '  ✓ %s\n' "future base + already reset current → no ratchet"
}

run_future_base_already_reset_current

# ----------------------------------------------------------------------
# SP_618 — DM-reconciler-1: reconciler refuses status: Complete flip when
# frontmatter claims are unmet by the diff. Forward direction: declared
# features/user_stories/schema_touched/structure_touched without the
# corresponding meta-doc in the diff. Inverse direction: DATA_SCHEMA.md
# or CODEBASE_STRUCTURE.md in diff but the boolean claim is false.
# Refusal: exit 1 + stderr "reconcile: REFUSE —" prefix. No last-reconciled
# bumps performed on refusal.
# ----------------------------------------------------------------------

run_sp618_scenario() {
  # $1=label, $2=plan-frontmatter-snippet, $3=meta-doc-delta,
  # $4=expected-exit (0 or 1), $5=expected-stderr-substring-or-empty
  local label="$1"
  local plan_extra="$2"
  local delta="$3"
  local expected_exit="$4"
  local expected_stderr="$5"

  local tmp
  tmp=$(mktemp -d)
  cd "${tmp}"

  git init -q
  git config user.email "test@example.local"
  git config user.name "SP_618 test"

  mkdir -p workspace/sprints validators scripts
  cp "${REAL_VALIDATOR}" validators/validate_doc_freshness.py
  cp "${REAL_COMMON}" validators/_common.py  # SP_719 import dep
  cp "${REAL_DIFF_SCOPE}" validators/_diff_scope.py  # SP_736 import dep

  cat > PROGRESS.md <<'EOF'
---
status: living
last-reconciled: 2026-04-01
authoritative-for: [active-sprint, sprint-history]
---

# Progress

## Active Sprint

**Current:** SP_999
EOF
  for doc in DATA_SCHEMA.md CODEBASE_STRUCTURE.md FEATURE_LIST.md USER_STORIES.md; do
    cat > "${doc}" <<EOF
---
last-reconciled: 2026-04-01
---
# ${doc} baseline.
EOF
  done

  git add -A && git commit -q -m "baseline"

  cat > workspace/sprints/SP_999.md <<EOF
---
sprint_id: SP_999
${plan_extra}
last-reconciled: 2026-04-20
---

# SP_999
EOF
  git add workspace/sprints/SP_999.md && git commit -q -m "add SP_999 plan"

  eval "${delta}"

  local out
  local actual_exit
  local cli_args="${6:-}"  # optional: extra args like --dry-run
  if out=$(python3 "${SCRIPT}" ${cli_args} . 2>&1); then
    actual_exit=0
  else
    actual_exit=$?
  fi

  local fail=""
  if [ "${actual_exit}" != "${expected_exit}" ]; then
    fail="exit ${actual_exit} (expected ${expected_exit})"
  fi
  if [ -n "${expected_stderr}" ] && ! echo "${out}" | grep -q "${expected_stderr}"; then
    fail="${fail} stderr missing '${expected_stderr}'"
  fi

  cd - > /dev/null
  rm -rf "${tmp}"

  if [ -n "${fail}" ]; then
    echo "✗ ${label}: ${fail}" >&2
    echo "  output: ${out}" >&2
    return 1
  fi
  printf '  ✓ %s\n' "${label}"
}

# Scenario 7 (SP_618 #2 — clean_complete_satisfied): Complete + features
# non-empty + FEATURE_LIST.md DOES touch → exit 0.
run_sp618_scenario "clean_complete_features_satisfied" \
  "features: [F-618]
user_stories: []
schema_touched: false
structure_touched: false
status: Complete" \
  "echo 'feat added' >> FEATURE_LIST.md && git add -A && git commit -q -m 'feat'" \
  "0" \
  ""

# Scenario 8 (SP_618 #3 — clean_complete_empty_features): Complete +
# features:[] empty list + no meta-doc edit → exit 0 vacuously.
run_sp618_scenario "clean_complete_empty_features" \
  "features: []
user_stories: []
schema_touched: false
structure_touched: false
status: Complete" \
  ":" \
  "0" \
  ""

# Scenario 9 (SP_618 #5 — clean_abandoned_unmet): Abandoned + claims unmet
# → exit 0 (refusal gated on Complete only).
run_sp618_scenario "clean_abandoned_unmet" \
  "features: [F-618]
user_stories: []
schema_touched: false
structure_touched: false
status: Abandoned" \
  ":" \
  "0" \
  ""

# Scenario 10 (SP_618 #1 — RED→GREEN baseline): Complete + features unmet
# → exit 1 with REFUSE prefix.
run_sp618_scenario "refuse_complete_features_unmet" \
  "features: [F-618]
user_stories: []
schema_touched: false
structure_touched: false
status: Complete" \
  ":" \
  "1" \
  "reconcile: REFUSE"

# Scenario 11 (SP_618 #7 — multi_unmet_forward): Complete + features AND
# schema_touched unmet → exit 1 lists BOTH.
run_sp618_scenario "refuse_complete_multi_unmet_forward" \
  "features: [F-618]
user_stories: []
schema_touched: true
structure_touched: false
status: Complete" \
  ":" \
  "1" \
  "FEATURE_LIST.md not in diff"

run_sp618_scenario "refuse_complete_multi_unmet_forward_schema_listed" \
  "features: [F-618]
user_stories: []
schema_touched: true
structure_touched: false
status: Complete" \
  ":" \
  "1" \
  "DATA_SCHEMA.md not in diff"

# Scenario 12 (SP_618 #8 — inverse_schema): Complete + schema_touched:false
# but DATA_SCHEMA.md IS in diff → exit 1 (inverse refusal).
run_sp618_scenario "refuse_complete_inverse_schema" \
  "features: []
user_stories: []
schema_touched: false
structure_touched: false
status: Complete" \
  "echo 'schema row' >> DATA_SCHEMA.md && git add -A && git commit -q -m 'schema'" \
  "1" \
  "DATA_SCHEMA.md in diff but schema_touched not set"

# Scenario 13 (SP_618 #9 — dry_run_still_refuses): Complete + claim unmet
# + --dry-run flag → still exit 1 (refusal not bypassed by dry-run).
run_sp618_scenario "dry_run_still_refuses" \
  "features: [F-618]
user_stories: []
schema_touched: false
structure_touched: false
status: Complete" \
  ":" \
  "1" \
  "reconcile: REFUSE" \
  "--dry-run"

echo ""
echo "reconcile-sprint-frontmatter regression: all cases passed."
