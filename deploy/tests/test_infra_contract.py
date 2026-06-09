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
