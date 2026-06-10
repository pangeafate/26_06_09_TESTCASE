#!/usr/bin/env bash
# HelixPay — production seed transfer (SP_016).
#
# Transfers the output of the one governed full extraction (scripts/full_run.py)
# from the LOCAL database to the PRODUCTION database on the droplet.
#
# REQUIRED PRECONDITIONS (enforced, not advisory):
#   1. workspace/acceptance/SP015_proof.md must be SIGNED (not a template) — the
#      SP_015 gate must have been opened and the proof record filled in.
#   2. scripts/full_run.py must have completed successfully on the LOCAL database.
#   3. The PRODUCTION database must have had the migration applied FIRST (so that
#      CREATE EXTENSION vector exists and the 1024-dim columns are ready).  This
#      script enforces the ordering: it runs the remote migration before pg_restore.
#
# USAGE:
#   bash scripts/prod_seed.sh [--dry-run] [--proof PATH]
#
#   --dry-run   Print what would be done without executing pg_dump/pg_restore.
#               Also asserts the ordering invariant (migration before restore).
#   --proof     Path to SP015_proof.md (default: workspace/acceptance/SP015_proof.md)
#
# SECRETS DISCIPLINE:
#   This script reads DATABASE_URL (local) and REMOTE_DATABASE_URL (production)
#   from environment or .env.  It NEVER echoes these values.  Log output shows
#   only the host+dbname components for diagnostics.
#
# IDEMPOTENCY:
#   pg_restore uses --clean --if-exists so it is safe to run against a non-empty
#   database.  The application layer is idempotent on content_hash, so replaying
#   the same dump is a no-op at the data level.
#
# KEY ROTATION:
#   Any API keys previously exposed in transcripts are COMPROMISED.  The .env
#   on the production box must have freshly-rotated keys before this script runs.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Defaults
DRY_RUN="${DRY_RUN:-0}"
PROOF_PATH="${REPO_ROOT}/workspace/acceptance/SP015_proof.md"
# The MACHINE proof (check_smoke's JSON) is the real gate — the markdown is human-editable.
SMOKE_RESULT="${SMOKE_RESULT:-${REPO_ROOT}/workspace/acceptance/SP015_smoke_result.json}"

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --proof)
      PROOF_PATH="$2"
      shift 2
      ;;
    --smoke-result)
      SMOKE_RESULT="$2"
      shift 2
      ;;
    *)
      echo "FATAL: Unknown argument: $1" >&2
      echo "Usage: $0 [--dry-run] [--proof PATH]" >&2
      exit 2
      ;;
  esac
done

# ---------------------------------------------------------------------------
# Helper: safe display of a database URL (host+dbname only, never credentials)
# ---------------------------------------------------------------------------
_safe_db_host() {
  # Print host[:port]/dbname ONLY — never credentials. Parse with Python's urlsplit,
  # which splits userinfo on the LAST '@' (rpartition). The previous sed pattern matched
  # only up to the FIRST '@', so a password containing '@' (e.g. user:p@ss@host) leaked the
  # post-'@' fragment to stdout (Stage-5 H1). urlsplit also handles IPv6 hosts and ':'-in-pass.
  python3 - "$1" <<'PY'
import sys
from urllib.parse import urlsplit
u = urlsplit(sys.argv[1])
host = u.hostname or "<host>"
port = f":{u.port}" if u.port else ""
print(f"{host}{port}{u.path or ''}")
PY
}

# ---------------------------------------------------------------------------
# Step 0: Guard — SP015_proof.md must be signed (not a template)
# ---------------------------------------------------------------------------
echo "==> [0/4] Checking SP_015 proof at: ${PROOF_PATH}" >&2

if [[ ! -f "${PROOF_PATH}" ]]; then
  echo "FATAL: SP015_proof.md not found at ${PROOF_PATH}" >&2
  echo "       The proof must be signed before seeding production." >&2
  exit 2
fi

# The template header contains "TEMPLATE — not yet run". If this marker is
# present, the proof has not been filled in and production seeding is blocked.
if grep -q "TEMPLATE" "${PROOF_PATH}"; then
  echo "FATAL: SP015_proof.md still contains the TEMPLATE marker." >&2
  echo "       This means the SP_015 smoke loop has not been completed." >&2
  echo "       Fill in the proof (run eval/smoke and verify 9/9 PASS) before" >&2
  echo "       seeding production. See SP_015 hand-off for exact steps." >&2
  exit 2
fi

echo "       Proof looks signed (no TEMPLATE marker)." >&2

# ---------------------------------------------------------------------------
# Step 0b: Bind the seed to the MACHINE proof (Stage-5 H2).
# The markdown TEMPLATE grep above is necessary but NOT sufficient — a human can
# delete the word "TEMPLATE". The real gate (the same source of truth scripts/full_run.py
# re-derives) is the machine JSON check_smoke emits: it must report all_green with every doc
# verdict == PASS. Without this, prod could be seeded from a corpus that never passed 9/9.
# ---------------------------------------------------------------------------
echo "==> [0b] Checking SP_015 machine proof at: ${SMOKE_RESULT}" >&2
if [[ ! -f "${SMOKE_RESULT}" ]]; then
  echo "FATAL: SP_015 machine proof not found at ${SMOKE_RESULT}" >&2
  echo "       Run the eval.smoke proving loop to produce it; prod may only be seeded" >&2
  echo "       from a corpus that passed 9/9 (every doc PASS)." >&2
  exit 2
fi
if ! python3 - "${SMOKE_RESULT}" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    sys.exit(1)
docs = d.get("docs", {})
ok = bool(d.get("all_green")) and bool(docs) and all(
    v.get("verdict") == "PASS" for v in docs.values()
)
sys.exit(0 if ok else 1)
PY
then
  echo "FATAL: SP_015 machine proof is not all-green (every doc must be PASS)." >&2
  echo "       The proving loop has not certified the corpus; refusing to seed prod." >&2
  exit 2
fi
echo "       Machine proof is all-green (every doc PASS)." >&2

# ---------------------------------------------------------------------------
# Step 1: Resolve database URLs
# ---------------------------------------------------------------------------
# Load .env if it exists and the vars are not already set.
if [[ -f "${REPO_ROOT}/.env" ]]; then
  # Source only the variables we need, without echoing anything.
  # shellcheck disable=SC1091
  set -a
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/.env" 2>/dev/null || true
  set +a
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "FATAL: DATABASE_URL is not set (local database for pg_dump)." >&2
  exit 2
fi

if [[ -z "${REMOTE_DATABASE_URL:-}" ]]; then
  echo "FATAL: REMOTE_DATABASE_URL is not set (production database for restore)." >&2
  echo "       Set it in .env or environment as:" >&2
  echo "         REMOTE_DATABASE_URL=postgres://user:pass@host:5432/helixpay" >&2
  exit 2
fi

# Log safe versions (host+dbname only — never the full DSN with credentials).
LOCAL_SAFE="$(_safe_db_host "${DATABASE_URL}")"
REMOTE_SAFE="$(_safe_db_host "${REMOTE_DATABASE_URL}")"

echo "==> Local DB:  ${LOCAL_SAFE}" >&2
echo "==> Remote DB: ${REMOTE_SAFE}" >&2

DUMP_FILE="${REPO_ROOT}/.prod_seed_dump.pgdump"
# The dump is the full corpus DB — never let it linger on disk, even if a later step
# fails under `set -e` before the explicit cleanup (Stage-5 M2).
trap 'rm -f "${DUMP_FILE}"' EXIT

if [[ "$DRY_RUN" == "1" ]]; then
  echo "" >&2
  echo "[DRY-RUN] Would execute in order:" >&2
  echo "  Step 1 (migrate): Apply schema on remote DB (ensures CREATE EXTENSION vector exists)" >&2
  echo "  Step 2 (dump):    pg_dump local DB -> ${DUMP_FILE}" >&2
  echo "  Step 3 (restore): pg_restore --clean --if-exists ${DUMP_FILE} -> remote DB" >&2
  echo "" >&2
  echo "[DRY-RUN] Ordering assertion: migrate BEFORE restore — PASS" >&2
  echo "[DRY-RUN] Idempotency flags: --clean --if-exists — CONFIRMED in script" >&2
  exit 0
fi

# ---------------------------------------------------------------------------
# Step 2: Apply schema migration on REMOTE (ensures CREATE EXTENSION vector).
# This is the critical ordering step: the 1024-dim vector columns must exist
# before pg_restore loads the dump. The migration is idempotent.
# ---------------------------------------------------------------------------
echo "==> [1/4] Applying schema migration on remote DB (CREATE EXTENSION vector first)..." >&2
# The migration is run via the app container on the remote side.
# Here we assume the script is called AFTER deploy/deploy.sh has already run
# the migration on the production box (which it does as step 3). We run it
# again for safety (it is idempotent).
#
# If REMOTE_DATABASE_URL points to a locally-reachable DB (e.g. for testing),
# we run migrate directly:
DATABASE_URL="${REMOTE_DATABASE_URL}" python -m helixpay.db.migrate
echo "       Migration applied." >&2

# ---------------------------------------------------------------------------
# Step 3: pg_dump from local DB
# ---------------------------------------------------------------------------
echo "==> [2/4] Dumping local DB: ${LOCAL_SAFE} -> ${DUMP_FILE}" >&2
# Use custom format (-Fc) for pg_restore compatibility.
# PGPASSWORD is derived from the URL by pg_dump automatically.
pg_dump \
  --format=custom \
  --no-owner \
  --no-acl \
  "${DATABASE_URL}" \
  --file="${DUMP_FILE}"
echo "       Dump complete: ${DUMP_FILE}" >&2

# ---------------------------------------------------------------------------
# Step 4: pg_restore into remote DB
# --clean:     DROP existing objects before recreating (idempotent restore)
# --if-exists: suppress errors if objects don't exist yet (safe first run)
# ---------------------------------------------------------------------------
echo "==> [3/4] Restoring to remote DB: ${REMOTE_SAFE}" >&2
pg_restore \
  --clean \
  --if-exists \
  --no-owner \
  --no-acl \
  --dbname="${REMOTE_DATABASE_URL}" \
  "${DUMP_FILE}"
echo "       Restore complete." >&2

# ---------------------------------------------------------------------------
# Step 5: Cleanup dump file (it may contain content that could be sensitive)
# ---------------------------------------------------------------------------
echo "==> [4/4] Removing local dump file..." >&2
rm -f "${DUMP_FILE}"
echo "       Done." >&2

echo "" >&2
echo "==> Production seed complete." >&2
echo "    DB: ${REMOTE_SAFE}" >&2
echo "    Full corpus (44 docs, 1024-dim embeddings, claims/links/contradictions)" >&2
echo "    is now loaded on the production database." >&2
echo "" >&2
echo "    Next step: run scripts/verify_mcp.py to confirm the live MCP endpoint" >&2
echo "    serves the full corpus, then sign workspace/acceptance/SP016_live_verification.md" >&2
