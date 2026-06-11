"""DB-gated audit integration: the read-only audit runs against a live corpus and
flags a known-bad claim. Auto-skipped unless DATABASE_URL is set (see test/conftest.py).
"""

from __future__ import annotations

from datetime import date

import pytest

from helixpay.audit.run import run_audit
from helixpay.contracts import Chunk, Claim, Document, Entity

pytestmark = pytest.mark.db

_CHUNK_TEXT = "Q1 2026 Revenue: SGD 14.2M as of 2026-03-31"


def _claim_with_evidence(repo, *, evidence: str, char_start, char_end) -> int:
    doc = repo.upsert_document(
        Document(
            source_uri="data/dash.html",
            source_type="html",
            content_hash="hash-audit",
            raw_text=_CHUNK_TEXT,
            as_of=date(2026, 3, 31),
        )
    )
    chunk_id = repo.add_chunks(
        [Chunk(document_id=doc, ordinal=0, text=_CHUNK_TEXT)], [[0.1] * 1024]
    )[0]
    e = repo.upsert_entity(Entity(canonical_name="HelixPay", entity_type="other"))
    return repo.add_claim(
        Claim(
            subject_entity_id=e,
            predicate="revenue",
            object_value="SGD 14.2M",
            as_of=date(2026, 3, 31),
            confidence=0.9,
            source_chunk_id=chunk_id,
            document_id=doc,
            evidence=evidence,
            char_start=char_start,
            char_end=char_end,
        )
    )


def test_audit_runs_readonly_and_reports_shape(pg_repo):
    _claim_with_evidence(
        pg_repo, evidence="Revenue: SGD 14.2M", char_start=8, char_end=26
    )
    pg_repo.conn.commit()

    report = run_audit(pg_repo.conn, sample_size=10, seed=1)
    assert report.total_claims == 1
    assert report.evidence_columns_present is True
    assert report.counts["claims"] == 1
    assert {t.name for t in report.traps} == {
        "confluence_ga_surfaces",
        "no_false_revenue_contradiction",
        "two_marias_distinct",
    }
    # A well-grounded revenue claim with no revenue contradiction: that trap passes.
    no_false = next(
        t for t in report.traps if t.name == "no_false_revenue_contradiction"
    )
    assert no_false.passed


def test_audit_flags_ungrounded_evidence(pg_repo):
    # evidence that is NOT a substring of the chunk → an ERROR-level violation.
    _claim_with_evidence(
        pg_repo, evidence="Revenue: SGD 99.9M", char_start=None, char_end=None
    )
    pg_repo.conn.commit()

    report = run_audit(pg_repo.conn, sample_size=10, seed=1)
    cats = report.violations_by_category()
    assert cats.get("evidence_not_in_chunk", 0) == 1
    assert report.error_count() >= 1


def test_read_only_connection_rejects_writes():
    import psycopg

    from helixpay.config import database_url
    from helixpay.db import audit_queries

    with audit_queries.read_only_connection(database_url()) as conn:
        # has_evidence_columns is a read — fine.
        audit_queries.has_evidence_columns(conn)
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            with conn.cursor() as cur:
                cur.execute("CREATE TEMP TABLE _audit_should_fail (x int)")
