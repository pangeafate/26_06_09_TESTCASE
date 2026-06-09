# Deploy — HelixPay

Infra & deploy artifacts (SP_006, Agent 5). One compose file serves local and
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

## Production (droplet `138.197.187.49`)

**Live URL: <https://helixpay.serverado.app>** (MCP at `/mcp`). DNS + nginx vhost + TLS
are already provisioned (2026-06-09) — see [`HANDOFF.md`](./HANDOFF.md). The URL currently
returns 502 until the integrated app is deployed (step 3). Box: `ssh -i ~/.ssh/id_rsa
root@138.197.187.49`; the proxy is **system nginx** (use [`nginx.conf`](./nginx.conf)).

The box already has Docker + the nginx TLS proxy + DNS pointing at it. Deploy is
CI/CD-first (governance Rule 11); direct host access is emergency-only.

1. **Vhost** — wire the subdomain to the loopback app with whichever proxy is
   installed:
   - **Caddy:** add [`Caddyfile`](./Caddyfile) (auto-TLS). Replace
     `helixpay.example.com` with the real subdomain — or use
     `helixpay.138.197.187.49.sslip.io` for an instant TLS URL with no DNS work.
   - **nginx:** paste [`nginx.conf`](./nginx.conf) into the existing TLS
     `server { }` block for the subdomain.
   Either way the MCP endpoint lands at `https://<subdomain>/mcp`.

2. **Secrets** — create `/path/to/repo/.env` on the box (`chmod 600`, never
   committed) from `.env.example`. `DATABASE_URL` must use host `db` and a password
   matching `POSTGRES_PASSWORD`.

3. **Deploy** — from the repo root on the box (or via CI over SSH):
   ```bash
   ./deploy/deploy.sh
   ```
   It pulls, `docker compose up -d --build`, waits for db health, migrates, seeds,
   ingests `./data` once, and curls `/health`. Idempotent — re-running converges
   and is the moving-target demo (drop a new file into `data/`, re-run).

## Invariants enforced by `deploy/tests/test_infra_contract.py`

- the `db` service publishes **no** host port (never publicly reachable);
- the `app` binds exactly `127.0.0.1:8000:8000` (loopback only);
- db has a `pg_isready` healthcheck + the named `pgdata` volume; app waits on
  `service_healthy`;
- secrets reach the app via `env_file: .env` only — none baked into compose;
- the Makefile exposes `up | ingest | demo | test | fmt`;
- `.env.example` documents the three secrets with placeholder (non-real) values;
- the Dockerfile is Python 3.12 and serves the frozen ASGI app `helixpay.api.app:app`
  on port 8000.

Run them with `uv run pytest deploy/tests`.
