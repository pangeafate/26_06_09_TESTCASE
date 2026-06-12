"""Read-only SQL for the extraction audit (helixpay.audit).

Raw SQL lives in ``helixpay/db/`` (CLAUDE.md §7: no raw SQL outside this package). This
module is deliberately SEPARATE from ``PostgresRepository`` (which SP_009 owns) so the
audit adds no surface to the frozen repository — and it imports nothing from
``helixpay.audit`` (infrastructure stays standalone; the capability depends inward on it).

Every query is a ``SELECT``; the connection is put in read-only mode, so an audit can
never write. Functions return plain ``dict`` rows (``dict_row`` factory); mapping rows to
audit value types happens up in the audit layer.
"""

from __future__ import annotations

import contextlib
from typing import Any, Iterator, Optional

from helixpay.db.connection import DictConnection, connect

# A fixed allow-list — these names are interpolated into COUNT(*) below, never user input.
_CORE_TABLES = (
    "documents",
    "chunks",
    "entities",
    "entity_aliases",
    "metric_vocab",
    "claims",
    "links",
    "contradictions",
)

_EVIDENCE_COLUMNS = ("evidence", "char_start", "char_end")


@contextlib.contextmanager
def read_only_connection(url: Optional[str] = None) -> Iterator[DictConnection]:
    """A context-managed connection forced read-only (best effort, driver-enforced)."""
    conn = connect(url)
    try:
        with contextlib.suppress(Exception):
            # Settable only before a transaction opens; we are right after connect().
            conn.read_only = True
        yield conn
    finally:
        conn.close()


def has_evidence_columns(conn: DictConnection) -> bool:
    """True when the SP_009 provenance-v2 columns exist on ``claims``."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM information_schema.columns "
            "WHERE table_name = 'claims' AND column_name = ANY(%s)",
            (list(_EVIDENCE_COLUMNS),),
        )
        row = cur.fetchone()
        if row is None:  # count(*) always returns one row
            raise RuntimeError("has_evidence_columns: count(*) returned no row")
        return row["n"] == len(_EVIDENCE_COLUMNS)


def table_counts(conn: DictConnection) -> dict[str, int]:
    counts: dict[str, int] = {}
    with conn.cursor() as cur:
        for table in _CORE_TABLES:
            cur.execute(f"SELECT count(*) AS n FROM {table}")  # noqa: S608 - fixed allow-list
            row = cur.fetchone()
            if row is None:  # count(*) always returns one row
                raise RuntimeError(f"table_counts: count(*) on {table} returned no row")
            counts[table] = row["n"]
    return counts


def fetch_claim_rows(
    conn: DictConnection, *, evidence_present: bool
) -> list[dict[str, Any]]:
    """Every claim flattened with its chunk text, document source_uri and subject entity.
    When the evidence columns are absent the projection substitutes NULLs so callers see a
    stable row shape.

    NOTE: materializes the full ``claims`` table (LEFT-joined to chunks/documents/entities)
    into memory — fine for a bounded company corpus (low thousands of claims; a dev-tooling
    census, not a serving path), but a future 100k-claim store should add a server-side
    cursor / batching here."""
    if evidence_present:
        evidence_select = "c.evidence, c.char_start, c.char_end,"
    else:
        evidence_select = (
            "NULL::text AS evidence, NULL::int AS char_start, NULL::int AS char_end,"
        )
    sql = (
        "SELECT c.id, c.subject_entity_id, e.canonical_name AS subject_name, "
        "       e.entity_type AS subject_type, c.predicate, c.object_value, c.as_of, "
        "       c.confidence, c.superseded_by, c.source_chunk_id, c.document_id, "
        f"      {evidence_select} "
        "       ch.text AS chunk_text, d.source_uri AS document_source_uri "
        "FROM claims c "
        "LEFT JOIN chunks ch ON ch.id = c.source_chunk_id "
        "LEFT JOIN documents d ON d.id = c.document_id "
        "LEFT JOIN entities e ON e.id = c.subject_entity_id"
    )
    with conn.cursor() as cur:
        cur.execute(sql)
        return [dict(r) for r in cur.fetchall()]


def fetch_contradiction_rows(conn: DictConnection) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, subject_entity_id, predicate, claim_a_id, claim_b_id, "
            "       link_a_id, link_b_id, kind FROM contradictions"
        )
        return [dict(r) for r in cur.fetchall()]


def fetch_entity_rows(conn: DictConnection) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, canonical_name, entity_type, seeded FROM entities")
        return [dict(r) for r in cur.fetchall()]


def fetch_vocab_rows(conn: DictConnection) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("SELECT canonical_key, aliases FROM metric_vocab")
        return [dict(r) for r in cur.fetchall()]


__all__ = [
    "read_only_connection",
    "has_evidence_columns",
    "table_counts",
    "fetch_claim_rows",
    "fetch_contradiction_rows",
    "fetch_entity_rows",
    "fetch_vocab_rows",
]
