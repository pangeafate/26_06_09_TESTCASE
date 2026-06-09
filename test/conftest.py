"""Shared pytest configuration.

DB integration tests are marked ``db`` and are auto-skipped when ``DATABASE_URL``
is unset — there is NO fallback connection string anywhere (secrets from env only).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def pytest_collection_modifyitems(config, items):
    if os.environ.get("DATABASE_URL"):
        return
    skip_db = pytest.mark.skip(reason="DATABASE_URL not set — skipping DB integration test")
    for item in items:
        if "db" in item.keywords:
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
