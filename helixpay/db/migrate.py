"""Apply the ontology schema (idempotent).

Run as a module:  python -m helixpay.db.migrate
Exit codes (GL-ERROR-LOGGING): 0 success · 1 database/SQL failure · 2 config error.

Each DDL statement is applied individually so a failure names the offending
statement (truncated) without ever logging the connection string / password.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

import psycopg

from helixpay.config import MissingEnvError, database_url
from helixpay.db.connection import connect

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

log = logging.getLogger("helixpay.db.migrate")


def _statements(sql: str) -> list[str]:
    """Split a comment-stripped SQL script into top-level statements.

    Safe for this schema: no dollar-quoted bodies and no ``--``/``;`` inside string
    literals, so line-comment stripping + split on ``;`` is correct.
    """
    cleaned_lines = []
    for line in sql.splitlines():
        idx = line.find("--")
        if idx != -1:
            line = line[:idx]
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines)
    return [stmt.strip() for stmt in cleaned.split(";") if stmt.strip()]


def apply_schema(url: Optional[str] = None, schema_path: Path = SCHEMA_PATH) -> int:
    """Apply every statement in ``schema_path``. Returns the count applied.

    Raises ``psycopg.Error`` on a DDL/connection failure (caller maps to exit code).
    """
    statements = _statements(schema_path.read_text(encoding="utf-8"))
    with connect(url) as conn:
        with conn.cursor() as cur:
            for stmt in statements:
                try:
                    cur.execute(stmt)
                except psycopg.Error:
                    conn.rollback()
                    log.error("DDL failed on statement: %.120s", stmt.replace("\n", " "))
                    raise
        conn.commit()
    return len(statements)


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        url = database_url()
    except MissingEnvError as exc:
        log.error("config error: %s", exc)  # names the missing var, not a value
        return 2
    try:
        count = apply_schema(url)
    except psycopg.OperationalError:
        log.error("database connection failed (check DATABASE_URL host/credentials)")
        return 1
    except psycopg.Error as exc:
        log.error("schema apply failed: %s", exc.__class__.__name__)
        return 1
    log.info("schema applied: %d statements", count)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
