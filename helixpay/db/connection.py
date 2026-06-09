"""Postgres connection helpers (psycopg 3).

The only knob is ``DATABASE_URL`` (read via ``helixpay.config``). Nothing here logs
the URL — it carries the password.
"""

from __future__ import annotations

import contextlib
from typing import Any, Iterator, Optional

import psycopg
from psycopg.rows import dict_row

from helixpay.config import database_url

# Every connection here uses dict rows.
DictConnection = psycopg.Connection[dict[str, Any]]


def connect(url: Optional[str] = None) -> DictConnection:
    """Open a connection (dict rows). Caller owns closing it."""
    return psycopg.connect(url or database_url(), row_factory=dict_row)


@contextlib.contextmanager
def connection(url: Optional[str] = None) -> Iterator[DictConnection]:
    """Context-managed connection that always closes."""
    conn = connect(url)
    try:
        yield conn
    finally:
        conn.close()


__all__ = ["connect", "connection"]
