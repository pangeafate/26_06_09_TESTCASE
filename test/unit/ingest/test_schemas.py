"""Structured-output schemas are validated against the frozen contracts."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from helixpay.ingest.extract.schemas import ClaimOut, ExtractionOut, RelationOut


def test_valid_extraction_builds():
    out = ExtractionOut(
        claims=[
            ClaimOut(
                subject="HelixPay",
                subject_type="metric",
                predicate="ARR",
                object_value="SGD 14.2M",
                as_of="2026-03-31",
                confidence=0.9,
                evidence="Q1 2026 ARR was SGD 14.2M",
            )
        ],
        relations=[
            RelationOut(from_entity="Sara Wijaya", to_entity="Daniel Tan", link_type="reports_to")
        ],
    )
    assert out.claims[0].predicate == "ARR"
    assert out.claims[0].as_of_date() == date(2026, 3, 31)
    assert out.relations[0].link_type == "reports_to"


def test_subject_type_must_be_a_contract_enum():
    with pytest.raises(ValidationError):
        ClaimOut(subject="X", subject_type="department", predicate="p", object_value="v")


def test_link_type_must_be_a_contract_enum():
    with pytest.raises(ValidationError):
        RelationOut(from_entity="a", to_entity="b", link_type="manages")


def test_bad_as_of_is_rejected():
    with pytest.raises(ValidationError):
        ClaimOut(subject="X", predicate="p", object_value="v", as_of="last quarter")


def test_empty_predicate_is_rejected():
    with pytest.raises(ValidationError):
        ClaimOut(subject="X", predicate="   ", object_value="v")


def test_confidence_is_clamped_to_unit_interval():
    hi = ClaimOut(subject="X", predicate="p", object_value="v", confidence=1.4)
    lo = ClaimOut(subject="X", predicate="p", object_value="v", confidence=-0.2)
    assert hi.confidence == 1.0
    assert lo.confidence == 0.0


def test_none_as_of_is_allowed_and_returns_none():
    c = ClaimOut(subject="X", predicate="p", object_value="v")
    assert c.as_of is None
    assert c.as_of_date() is None


# (Removed ``test_hypothetical_defaults_false`` — it re-asserted a pydantic field
# default guaranteed by the ``ClaimOut`` model definition; SP_030 Item 4.)
