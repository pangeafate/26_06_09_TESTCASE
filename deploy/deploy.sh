#!/usr/bin/env bash
# HelixPay — idempotent deploy on the droplet (138.197.187.49).
#
# Run ON the box (or via CI over SSH) from the repo root. Re-running converges:
# compose rebuilds only what changed; migrate and seed are idempotent on
# natural keys. Re-running is safe.
#
# IMPORTANT — SP_016 decoupling: this script does NOT run the full extraction CLI.
# The full corpus ingestion is governed by scripts/full_run.py (SP_015 gate) and must
# ONLY be triggered after:
#   1. workspace/acceptance/SP015_proof.md is signed (9/9 archetypes), AND
#   2. scripts/verify_mcp.py confirms the live MCP endpoint is reachable.
# Running the extraction CLI ('make ingest') directly in production is prohibited —
# it bypasses the guard and triggers a paid, unrepeatable extraction.
#
# KEY ROTATION REQUIRED: any API keys previously exposed in transcripts or history
# are COMPROMISED and must NOT be used. Generate fresh keys before creating .env
# on the box. See deploy/README.md § "Secrets on the box".
#
# Prereqs on the box:
#   * Docker + Docker Compose v2
#   * System nginx vhost from deploy/nginx.conf (already provisioned, SP_006)
#   * .env (chmod 600, NOT in git) with freshly-rotated:
#       ANTHROPIC_API_KEY, VOYAGE_API_KEY,
#       DATABASE_URL (host 'db'), POSTGRES_PASSWORD
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  echo "FATAL: .env not found. Copy .env.example to .env (chmod 600) and fill in freshly-rotated keys." >&2
  exit 2
fi

# Sanity: warn if .env has wrong permissions (group/other readable → secrets exposed).
if [[ "$(stat -f '%A' .env 2>/dev/null || stat -c '%a' .env 2>/dev/null)" != "600" ]]; then
  echo "WARNING: .env is not chmod 600 — tighten permissions before running on a shared box." >&2
fi

echo "==> Pulling latest source..."
# NOTE (CI path): when run via the CI deploy job, the box already has the latest
# code (pushed by the same commit). git pull is a no-op in that case.
git pull --ff-only || echo "    (skipped git pull — not a clean fast-forward)"

echo "==> Building + starting containers..."
docker compose up -d --build

echo "==> Waiting for db to become healthy..."
until [ "$(docker compose ps db --format '{{.Health}}')" = "healthy" ]; do
  printf '.'; sleep 1
done
echo " healthy"

echo "==> Applying schema (idempotent — CREATE EXTENSION vector runs first)..."
docker compose run --rm app python -m helixpay.db.migrate

echo "==> Seeding deterministic backbone (idempotent on natural keys)..."
docker compose run --rm app python -m helixpay.seed.run_seed

echo "==> Health check (loopback)..."
curl -fsS http://127.0.0.1:8000/health && echo "  OK"

echo ""
echo "==> Deploy complete. App serving the seeded backbone on 127.0.0.1:8000."
echo "    TLS proxy serves it publicly at https://helixpay.serverado.app"
echo "    MCP at /mcp (streamable-HTTP)."
echo ""
echo "    To load the full corpus, follow the governed path:"
echo "      1. Confirm workspace/acceptance/SP015_proof.md is signed (9/9 archetypes)"
echo "      2. Run: python scripts/verify_mcp.py   (must exit 0)"
echo "      3. Run: python scripts/full_run.py     (the one governed extraction)"
echo "      4. Run: bash scripts/prod_seed.sh      (dump → restore on this box)"
