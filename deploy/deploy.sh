#!/usr/bin/env bash
# HelixPay — idempotent deploy on the droplet (138.197.187.49).
#
# Run ON the box (or via CI over SSH) from the repo root. Re-running converges:
# compose rebuilds only what changed; migrate, seed, and ingest are all idempotent
# (migrate/seed on natural keys, ingest on content_hash) — which doubles as the
# moving-target demo: drop a new file into data/, re-run, watch it converge.
#
# Prereqs on the box:
#   * Docker + Docker Compose v2
#   * the existing TLS reverse proxy (Caddy or nginx) with the vhost from this dir
#   * a .env (chmod 600, NOT in git) with ANTHROPIC_API_KEY, VOYAGE_API_KEY,
#     DATABASE_URL (host 'db'), POSTGRES_PASSWORD
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  echo "FATAL: .env not found. Copy .env.example to .env (chmod 600) and fill it in." >&2
  exit 2
fi

echo "==> Pulling latest source..."
git pull --ff-only || echo "    (skipped git pull — not a clean fast-forward)"

echo "==> Building + starting containers..."
docker compose up -d --build

echo "==> Waiting for db to become healthy..."
until [ "$(docker compose ps db --format '{{.Health}}')" = "healthy" ]; do
  printf '.'; sleep 1
done
echo " healthy"

echo "==> Applying schema + seeding the deterministic backbone (idempotent)..."
docker compose run --rm app python -m helixpay.db.migrate
docker compose run --rm app python -m helixpay.seed.run_seed

echo "==> Ingesting ./data (idempotent on content_hash)..."
docker compose run --rm app helixpay ingest ./data

echo "==> Health check (loopback)..."
curl -fsS http://127.0.0.1:8000/health && echo "  OK"

echo "==> Done. App on 127.0.0.1:8000; the TLS proxy serves it publicly; MCP at /mcp."
