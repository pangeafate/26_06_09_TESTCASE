"""``/health`` is green and dependency-free — no secrets, no engine, no LLM keys.

This is what compose probes; it must never require ``DATABASE_URL`` / ``ANTHROPIC_API_KEY``.
The app is imported at module load with no env set, proving construction is secret-free.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from helixpay.api.app import create_app


def test_health_is_green_without_any_secret():
    with TestClient(create_app()) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
