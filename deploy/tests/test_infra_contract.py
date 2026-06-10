"""Infra contract tests (SP_006, Agent 5) — TDD over the deploy artifacts.

These assert the *safety and contract invariants* of the infra, not behaviour:

  - the Postgres ``db`` service is **never** publicly exposed;
  - the ``app`` service is reachable only on the loopback ``127.0.0.1:8000``;
  - the db has a healthcheck + a named ``pgdata`` volume; the app waits for it;
  - secrets reach the app via ``.env`` only — no values are baked into compose;
  - the ``Makefile`` exposes the grader contract ``up | ingest | demo | test | fmt``;
  - ``.env.example`` names the three secrets and carries **no real values**;
  - the ``Dockerfile`` is Python 3.12 and launches the frozen ASGI app on 8000.

They parse the raw YAML/text (pyyaml is a pinned dep), so they run with no Docker
daemon and stay fast/hermetic. They live under ``deploy/`` — Agent 5's own
``touches_paths`` — and out of the product ``test/`` tree, so ``make test`` stays the
pure product suite and these never collide with another agent.

Run:  ``uv run pytest deploy/tests``
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yml"
DOCKERFILE = ROOT / "Dockerfile"
MAKEFILE = ROOT / "Makefile"
ENV_EXAMPLE = ROOT / ".env.example"

# The frozen entrypoints Agent 5 builds on (SPEC §5, AGENT_5_infra.md).
ASGI_APP = "helixpay.api.app:app"
LOOPBACK_PORT = "127.0.0.1:8000:8000"
SECRET_VARS = ("ANTHROPIC_API_KEY", "VOYAGE_API_KEY", "DATABASE_URL")
MAKE_TARGETS = ("up", "ingest", "demo", "test", "fmt")


def _compose() -> dict:
    assert COMPOSE.exists(), "docker-compose.yml missing"
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# docker-compose.yml
# --------------------------------------------------------------------------- #
def test_compose_parses_and_has_two_services() -> None:
    services = _compose().get("services", {})
    assert "db" in services, "compose must define a 'db' service"
    assert "app" in services, "compose must define an 'app' service"


def test_db_is_never_publicly_exposed() -> None:
    """The single most important safety invariant: the database has no host port
    mapping, so it is unreachable from outside the compose network."""
    db = _compose()["services"]["db"]
    ports = db.get("ports") or []
    assert ports == [], f"db must publish no host ports; found {ports!r}"


def test_db_uses_pgvector_pg16() -> None:
    assert _compose()["services"]["db"]["image"] == "pgvector/pgvector:pg16"


def test_db_has_healthcheck_and_named_volume() -> None:
    compose = _compose()
    db = compose["services"]["db"]
    hc = db.get("healthcheck", {})
    assert "pg_isready" in str(hc.get("test", "")), "db needs a pg_isready healthcheck"
    mounts = "".join(str(v) for v in db.get("volumes", []))
    assert "pgdata" in mounts, "db must persist on the named 'pgdata' volume"
    assert "pgdata" in (compose.get("volumes") or {}), "'pgdata' volume must be declared"


def test_app_binds_loopback_only() -> None:
    """App is reachable only on 127.0.0.1:8000 — the existing TLS proxy fronts it;
    binding to 0.0.0.0 would expose the app publicly, bypassing TLS."""
    ports = _compose()["services"]["app"].get("ports") or []
    flat = [str(p) for p in ports]
    assert flat == [LOOPBACK_PORT], f"app must bind exactly {LOOPBACK_PORT!r}; got {flat!r}"
    for p in flat:
        assert p.startswith("127.0.0.1:"), f"app port {p!r} is not loopback-bound"


def test_app_waits_for_healthy_db_and_uses_env_file() -> None:
    app = _compose()["services"]["app"]
    depends = app.get("depends_on", {})
    # long-form depends_on with a health condition
    assert isinstance(depends, dict), "app depends_on must use the long form with a condition"
    assert depends.get("db", {}).get("condition") == "service_healthy", (
        "app must wait for db 'service_healthy'"
    )
    env_file = app.get("env_file")
    assert env_file and ".env" in str(env_file), "app must load secrets via env_file: .env"


def test_compose_bakes_no_real_secrets() -> None:
    """No API key value is hardcoded in compose — secrets come from .env only."""
    text = COMPOSE.read_text(encoding="utf-8")
    assert "sk-ant-" not in text, "no real Anthropic key may appear in compose"
    assert "pa-" not in text.replace("pgdata", ""), "no real Voyage key may appear in compose"


# --------------------------------------------------------------------------- #
# Dockerfile
# --------------------------------------------------------------------------- #
def test_dockerfile_python_312_and_serves_frozen_asgi_app() -> None:
    assert DOCKERFILE.exists(), "Dockerfile missing"
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "python:3.12" in text, "Dockerfile must base on Python 3.12"
    assert "uv" in text, "Dockerfile must use uv to install the package"
    assert "uvicorn" in text, "Dockerfile entrypoint must launch uvicorn"
    assert ASGI_APP in text, f"Dockerfile must serve the frozen ASGI app {ASGI_APP!r}"
    assert "8000" in text, "Dockerfile must serve on port 8000"


# --------------------------------------------------------------------------- #
# Makefile
# --------------------------------------------------------------------------- #
def test_makefile_exposes_grader_contract() -> None:
    assert MAKEFILE.exists(), "Makefile missing"
    text = MAKEFILE.read_text(encoding="utf-8")
    for target in MAKE_TARGETS:
        assert f"\n{target}:" in f"\n{text}", f"Makefile must define a '{target}:' target"


def test_makefile_ingest_uses_frozen_command() -> None:
    text = MAKEFILE.read_text(encoding="utf-8")
    assert "helixpay ingest ./data" in text, "make ingest must call the frozen CLI command"


# --------------------------------------------------------------------------- #
# .env.example
# --------------------------------------------------------------------------- #
def test_env_example_lists_secrets_without_values() -> None:
    assert ENV_EXAMPLE.exists(), ".env.example missing"
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for var in SECRET_VARS:
        assert var in text, f".env.example must document {var}"
    # No real secret material shipped.
    assert "sk-ant-api" not in text, ".env.example must not ship a real Anthropic key"
    # A Voyage live key looks like 'pa-<base64>'; the placeholder must not be one.
    for line in text.splitlines():
        if line.startswith("VOYAGE_API_KEY="):
            val = line.split("=", 1)[1].strip()
            assert not val.startswith("pa-") or val.endswith("..."), (
                "VOYAGE_API_KEY in .env.example must be a placeholder, not a real key"
            )


# --------------------------------------------------------------------------- #
# deploy/ vhost
# --------------------------------------------------------------------------- #
def test_vhost_routes_to_loopback() -> None:
    caddy = ROOT / "deploy" / "Caddyfile"
    nginx = ROOT / "deploy" / "nginx.conf"
    assert caddy.exists() or nginx.exists(), "a Caddy or nginx vhost must be provided"
    blob = ""
    if caddy.exists():
        blob += caddy.read_text(encoding="utf-8")
    if nginx.exists():
        blob += nginx.read_text(encoding="utf-8")
    assert "127.0.0.1:8000" in blob, "vhost must reverse-proxy to the app loopback port"


# --------------------------------------------------------------------------- #
# SP_016 — deploy decoupling + CI job invariants
# --------------------------------------------------------------------------- #

DEPLOY_SH = ROOT / "deploy" / "deploy.sh"
DEPLOY_YML = ROOT / ".github" / "workflows" / "deploy.yml"


def test_deploy_sh_performs_up_migrate_seed() -> None:
    """deploy.sh must include the three canonical post-compose steps."""
    assert DEPLOY_SH.exists(), "deploy/deploy.sh missing"
    text = DEPLOY_SH.read_text(encoding="utf-8")
    assert "docker compose up" in text, "deploy.sh must run docker compose up"
    assert "helixpay.db.migrate" in text, "deploy.sh must apply schema via python -m helixpay.db.migrate"
    assert "helixpay.seed.run_seed" in text, "deploy.sh must seed via python -m helixpay.seed.run_seed"


def test_deploy_sh_contains_no_unguarded_ingest() -> None:
    """SP_016 key invariant: the full ingest must be removed from deploy.sh so that
    deploying the app never triggers an unguarded paid extraction.  The sanctioned
    path is scripts/full_run.py (behind the SP_015 gate)."""
    assert DEPLOY_SH.exists(), "deploy/deploy.sh missing"
    text = DEPLOY_SH.read_text(encoding="utf-8")
    # Must not invoke the 'helixpay ingest' CLI command directly.
    assert "helixpay ingest" not in text, (
        "deploy.sh must not run 'helixpay ingest' — that is an unguarded paid extraction. "
        "Full corpus ingestion goes via scripts/full_run.py (SP_015 gate) only."
    )
    # Must not call 'ingest ./data' via any other mechanism.
    assert "ingest ./data" not in text, (
        "deploy.sh must not contain 'ingest ./data' — remove the unguarded extraction step."
    )


def test_deploy_sh_health_check_present() -> None:
    """deploy.sh must verify the app is alive after startup."""
    assert DEPLOY_SH.exists(), "deploy/deploy.sh missing"
    text = DEPLOY_SH.read_text(encoding="utf-8")
    assert "/health" in text, "deploy.sh must curl /health as a liveness gate"


def test_deploy_sh_never_echoes_secrets() -> None:
    """deploy.sh must never echo the .env contents or any secret value.
    Specifically it must not echo $ANTHROPIC_API_KEY, $VOYAGE_API_KEY, or $DATABASE_URL."""
    assert DEPLOY_SH.exists(), "deploy/deploy.sh missing"
    text = DEPLOY_SH.read_text(encoding="utf-8")
    for secret_var in ("ANTHROPIC_API_KEY", "VOYAGE_API_KEY", "DATABASE_URL"):
        # Allow referencing the var in comments or -f checks; disallow echoing its value.
        # A line like `echo "... $SECRET_VAR ..."` would be a violation.
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "echo" in stripped and f"${secret_var}" in stripped:
                raise AssertionError(
                    f"deploy.sh must not echo ${secret_var} — secrets must never be logged"
                )


def test_deploy_yml_exists_and_gates_on_ci() -> None:
    """The CD workflow must exist and the deploy job must declare a 'needs' dependency
    on the CI/test job so that a failing test suite blocks the deploy."""
    assert DEPLOY_YML.exists(), ".github/workflows/deploy.yml must exist (CI/CD-first deploy)"
    text = DEPLOY_YML.read_text(encoding="utf-8")
    # The deploy job must name a 'needs:' that references the gateway/test job.
    assert "needs:" in text, "deploy.yml deploy job must declare 'needs:' to gate on the CI job"
    assert "gateway" in text or "test" in text or "ci" in text.lower(), (
        "deploy.yml must reference the CI/gateway job by name in 'needs:'"
    )


def test_deploy_yml_uses_secrets_not_inline_values() -> None:
    """All sensitive values in the deploy workflow must come from GitHub secrets,
    never as literal values in the YAML."""
    assert DEPLOY_YML.exists(), ".github/workflows/deploy.yml must exist"
    text = DEPLOY_YML.read_text(encoding="utf-8")
    assert "secrets.DEPLOY_SSH_KEY" in text, (
        "deploy.yml must use secrets.DEPLOY_SSH_KEY (never a literal key)"
    )
    assert "secrets.DROPLET_HOST" in text, (
        "deploy.yml must use secrets.DROPLET_HOST (never a literal IP)"
    )
    # Hard-coded IP must not appear in the workflow.
    assert "138.197.187.49" not in text, (
        "deploy.yml must not hardcode the droplet IP — use secrets.DROPLET_HOST"
    )
