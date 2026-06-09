"""Minimal hand-written query fixture (writes only through the Repository).

A few live rows so Agent 3 can build ``ask()`` against a real DB before extraction
lands — including one deliberate value-conflict contradiction (Q1 revenue: the
dashboard says SGD 14.2M, the board deck says SGD 13.9M) with both sources, so the
contradiction-surfacing path has something real to return.
"""

from __future__ import annotations

from datetime import date

from helixpay.contracts import Chunk, Claim, Contradiction, Document, Entity

_Q1 = date(2026, 3, 31)
_EMB = [0.01] * 1024  # non-zero placeholder so cosine ops are defined


def load_fixture(repo) -> dict:
    """Insert the fixture rows. Idempotent (rides the Repository's upserts)."""
    revenue_id = repo.upsert_entity(
        Entity(canonical_name="Revenue", entity_type="metric", attributes={"unit": "SGD"}, seeded=True)
    )

    doc_dash = repo.upsert_document(
        Document(
            source_uri="data/dashboards/april-2026-kpi-dashboard.html",
            source_type="html",
            title="HelixPay April 2026 KPI Dashboard",
            as_of=_Q1,
            content_hash="fixture:dashboard-q1-revenue",
        )
    )
    dash_chunks = repo.add_chunks(
        [Chunk(document_id=doc_dash, ordinal=0, text="Q1 2026 Revenue (SGD) 14.2M (−11% vs plan).")],
        [_EMB],
    )

    doc_board = repo.upsert_document(
        Document(
            source_uri="data/board-deck-q1-2026.pdf",
            source_type="pdf",
            title="HelixPay Board Deck Q1 2026",
            as_of=_Q1,
            content_hash="fixture:board-deck-q1-revenue",
        )
    )
    board_chunks = repo.add_chunks(
        [Chunk(document_id=doc_board, ordinal=0, text="Q1 revenue closed at SGD 13.9M against a 16M target.")],
        [_EMB],
    )

    claim_a = repo.add_claim(
        Claim(
            subject_entity_id=revenue_id,
            predicate="revenue",
            object_value="SGD 14.2M",
            as_of=_Q1,
            confidence=0.9,
            source_chunk_id=dash_chunks[0],
            document_id=doc_dash,
        )
    )
    claim_b = repo.add_claim(
        Claim(
            subject_entity_id=revenue_id,
            predicate="revenue",
            object_value="SGD 13.9M",
            as_of=_Q1,
            confidence=0.8,
            source_chunk_id=board_chunks[0],
            document_id=doc_board,
        )
    )
    repo.add_contradiction(
        Contradiction(
            subject_entity_id=revenue_id,
            predicate="revenue",
            claim_a_id=claim_a,
            claim_b_id=claim_b,
            kind="value_conflict",
            note="Q1 2026 revenue: dashboard 14.2M vs board deck 13.9M.",
        )
    )
    return {
        "revenue_entity_id": revenue_id,
        "claim_a_id": claim_a,
        "claim_b_id": claim_b,
    }


__all__ = ["load_fixture"]
