"""Shared pytest configuration.

DB integration tests are marked ``db`` and are auto-skipped when ``DATABASE_URL``
is unset — there is NO fallback connection string anywhere (secrets from env only).

When ``HELIXPAY_REQUIRE_DB`` is truthy (set by CI), an absent ``DATABASE_URL`` is a
**hard, loud failure** instead of a silent skip — so a misconfigured CI database
can never masquerade as a green run by quietly skipping the integration suite.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

import pytest

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _require_db_violation(env: Mapping[str, str]) -> str | None:
    """Return an error message when the DB is *required but absent*, else ``None``.

    Pure (env-in, message-out) so it is unit-testable without a database. The DB is
    required when ``HELIXPAY_REQUIRE_DB`` is truthy; it is absent when ``DATABASE_URL``
    is unset/empty. Every other combination (no flag, or url present) returns ``None``
    and preserves the normal skip/run behavior.
    """
    require = env.get("HELIXPAY_REQUIRE_DB", "").strip().lower() not in ("", "0", "false", "no")
    if require and not env.get("DATABASE_URL"):
        return (
            "HELIXPAY_REQUIRE_DB is set but DATABASE_URL is unset — refusing to "
            "silently skip the DB integration suite. Provision the database (or unset "
            "HELIXPAY_REQUIRE_DB) and retry."
        )
    return None


def pytest_configure(config):
    violation = _require_db_violation(os.environ)
    if violation is not None:
        raise pytest.UsageError(violation)


def pytest_collection_modifyitems(config, items):
    if os.environ.get("DATABASE_URL"):
        return
    skip_db = pytest.mark.skip(reason="DATABASE_URL not set — skipping DB integration test")
    for item in items:
        # Match the actual ``db`` MARKER, not the loose keyword set — ``item.keywords``
        # also contains ancestor names (e.g. the ``test/unit/db/`` directory), which would
        # false-skip pure unit tests that merely live under a path containing "db".
        if item.get_closest_marker("db") is not None:
            item.add_marker(skip_db)


@pytest.fixture
def db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")
    return url


@pytest.fixture
def pg_repo(db_url):
    """A PostgresRepository on a freshly-migrated, empty schema."""
    from helixpay.db.connection import connect
    from helixpay.db.migrate import apply_schema
    from helixpay.db.repository import PostgresRepository

    apply_schema(db_url)
    conn = connect(db_url)
    with conn.cursor() as cur:
        cur.execute(
            "TRUNCATE contradictions, claims, links, entity_aliases, chunks, documents, entities "
            "RESTART IDENTITY CASCADE"
        )
        cur.execute("TRUNCATE metric_vocab")
    conn.commit()
    repo = PostgresRepository(conn)
    try:
        yield repo
    finally:
        conn.close()
