"""Unit tests for the per-item coerce→validate→record-loss step (SP_018 RDD/SRP split).

Covers ``helixpay.ingest.extract.validate.validate_items`` — the body lifted out of
``ChunkExtractor._coerce_and_validate``. Uses a real ``LossLedger`` (an in-memory
accumulator) and the real coercion rules; no LLM.
"""

from __future__ import annotations

from helixpay.ingest.extract.ledger import LossLedger
from helixpay.ingest.extract.schemas import ClaimOut, RelationOut
from helixpay.ingest.extract.validate import validate_items

URI = "data/doc.md"


def test_valid_claim_passes_through_and_counts_emitted():
    ledger = LossLedger()
    raw = [{"subject": "Acme", "predicate": "ARR", "object_value": "5", "confidence": 0.8}]
    out = validate_items(raw, ClaimOut, "claim", URI, ledger)
    assert len(out) == 1 and isinstance(out[0], ClaimOut)
    assert ledger.per_source[URI].items_emitted == 1


def test_unmappable_subject_type_is_dropped_and_counted():
    ledger = LossLedger()
    raw = [{"subject": "x", "predicate": "p", "subject_type": "wizard"}]
    out = validate_items(raw, ClaimOut, "claim", URI, ledger)
    assert out == []
    assert ledger.per_source[URI].items_dropped >= 1
    assert ledger.per_source[URI].dropped_by_reason["unmappable_enum"] >= 1


def test_successful_as_of_coercion_is_recorded_and_item_kept():
    ledger = LossLedger()
    raw = [{"subject": "Acme", "predicate": "ARR", "object_value": "5", "as_of": "Q1 2025"}]
    out = validate_items(raw, ClaimOut, "claim", URI, ledger)
    assert len(out) == 1
    assert out[0].as_of is not None  # quarter coerced to an ISO date
    assert ledger.per_source[URI].coerced_by_kind["as_of"] >= 1


def test_validation_error_item_is_dropped_and_counted():
    ledger = LossLedger()
    # empty predicate survives coercion but fails the strict ClaimOut validator
    raw = [{"subject": "Acme", "predicate": "  ", "object_value": "5"}]
    out = validate_items(raw, ClaimOut, "claim", URI, ledger)
    assert out == []
    assert ledger.per_source[URI].dropped_by_reason.get("validation_error", 0) >= 1


def test_unparseable_as_of_is_dropped_by_coercion_and_counted():
    ledger = LossLedger()
    raw = [{"subject": "Acme", "predicate": "ARR", "object_value": "5", "as_of": "next-quarter-ish"}]
    out = validate_items(raw, ClaimOut, "claim", URI, ledger)
    assert out == []
    assert ledger.per_source[URI].dropped_by_reason.get("unparseable_as_of", 0) >= 1


def test_relations_validate_through_the_same_path():
    ledger = LossLedger()
    raw = [{"from_entity": "Maria", "to_entity": "HelixPay", "link_type": "member_of"}]
    out = validate_items(raw, RelationOut, "relation", URI, ledger)
    assert len(out) == 1 and isinstance(out[0], RelationOut)
