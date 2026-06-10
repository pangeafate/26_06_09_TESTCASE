# Deploy — HelixPay

Infra & deploy artifacts (SP_006 + SP_016). One compose file serves local and
production; the database is never exposed and the app is bound to the loopback,
fronted by the existing TLS reverse proxy.

## Local (the grader's path)

```bash
cp .env.example .env          # fill in the two API keys + a Postgres password
make up                       # build, start db+app, wait for health, migrate, seed
make ingest                   # idempotent ingestion over ./data
make demo                     # eval harness against the running app
make test                     # product test suite
```

App: <http://localhost:8000> · health: `/health` · MCP (streamable-HTTP): `/mcp`.

## Production (droplet `helixpay.serverado.app`)

**Live URL: <https://helixpay.serverado.app>** (MCP at `/mcp`). DNS + nginx vhost + TLS
are already provisioned (SP_006, 2026-06-09). The URL returns 502 until the integrated
app is deployed. Box: `ssh -i ~/.ssh/id_rsa root@138.197.187.49`; proxy is system nginx.

Deploy is **CI/CD-first** (Rule 11). Direct host access is emergency-only reconnaissance.

### SP_016 — deploy/ingest decoupling (IMPORTANT)

`deploy/deploy.sh` does **NOT** run `helixpay ingest ./data`. The full corpus extraction
is governed by `scripts/full_run.py` (SP_015 gate) and runs ONLY after:

1. `workspace/acceptance/SP015_proof.md` is signed (9/9 archetypes).
2. `scripts/verify_mcp.py` exits 0 (live MCP endpoint reachable).

Running `make ingest` or `helixpay ingest ./data` directly in production is prohibited —
it bypasses the guard and triggers a paid, unrepeatable extraction.

### Secrets on the box

**KEY ROTATION REQUIRED:** any API keys previously exposed in transcripts or repo history
are **COMPROMISED** and must **NOT** be used in production. Generate fresh keys before
creating `.env` on the box.

```bash
# On the box:
cp /opt/helixpay/.env.example /opt/helixpay/.env
chmod 600 /opt/helixpay/.env
# Edit with a text editor — fill in freshly-rotated ANTHROPIC_API_KEY, VOYAGE_API_KEY,
# POSTGRES_PASSWORD, and DATABASE_URL (host=db, db=helixpay).
# NEVER commit .env. NEVER paste a connection string in any markdown file.
```

### Operator deployment procedure (full Phase A → B → C)

Full procedure in `workspace/acceptance/SP016_live_verification.md`. Summary:

1. **Rotate keys** → `.env` on box (chmod 600).
2. **Push `main`** → CI `gateway` job (tests) → CI `deploy` job (rsync + `deploy.sh`).
   - `deploy.sh` sequence: `docker compose up -d --build` → wait db healthy →
     `python -m helixpay.db.migrate` → `python -m helixpay.seed.run_seed` → `/health`.
3. **Verify**: `HELIXPAY_PROD_MCP_URL=https://helixpay.serverado.app/mcp python scripts/verify_mcp.py`
4. **Sign SP015_proof.md** (if not done) after 9/9 smoke proof.
5. **Full extraction**: `python scripts/full_run.py` (local, governed, paid ~1h).
6. **Transfer to production**: `bash scripts/prod_seed.sh` (dump → restore).
7. **Live eval**: `python -m eval.run --level 2` against live endpoint.
8. **Sign** `workspace/acceptance/SP016_live_verification.md`.

### CI/CD workflow

`.github/workflows/deploy.yml` — on push to `main`:
- Job `gateway`: runs `dev-rules-ci.yml` (validators, lint, unit tests).
- Job `deploy` (gated on `gateway`): rsync + `deploy.sh` via SSH.
  - SSH key: `secrets.DEPLOY_SSH_KEY` (GitHub Actions secret — never hardcoded).
  - Host: `secrets.DROPLET_HOST` (GitHub Actions secret — never hardcoded).
  - Verifies `/health` returns 200 after deploy.

## Invariants enforced by `deploy/tests/test_infra_contract.py`

- the `db` service publishes **no** host port (never publicly reachable);
- the `app` binds exactly `127.0.0.1:8000:8000` (loopback only);
- db has a `pg_isready` healthcheck + the named `pgdata` volume; app waits on
  `service_healthy`;
- secrets reach the app via `env_file: .env` only — none baked into compose;
- the Makefile exposes `up | ingest | demo | test | fmt`;
- `.env.example` documents the three secrets with placeholder (non-real) values;
- the Dockerfile is Python 3.12 and serves the frozen ASGI app `helixpay.api.app:app`
  on port 8000;
- **SP_016**: `deploy.sh` performs up+migrate+seed and contains **no** `helixpay ingest`;
- **SP_016**: `.github/workflows/deploy.yml` exists and gates the deploy job on CI.

Run with `uv run pytest deploy/tests`.
