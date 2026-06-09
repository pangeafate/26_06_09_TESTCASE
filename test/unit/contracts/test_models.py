"""Contract model construction + invariants (no DB)."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from helixpay.contracts import (
    AnswerBundle,
    Citation,
    Claim,
    Contradiction,
    Entity,
    Link,
    LinkType,
)


def test_link_type_has_dotted_line():
    # The Stage-3 review addition (C2): dotted-line org links are first-class.
    assert LinkType.dotted_line_to.value == "dotted_line_to"
    assert {"reports_to", "dotted_line_to", "owns", "member_of", "mentions"} <= {lt.value for lt in LinkType}


def test_citation_requires_source_uri():
    with pytest.raises(ValidationError):
        Citation()  # type: ignore[call-arg]
    c = Citation(source_uri="data/org-chart.md", as_of=date(2026, 4, 15), snippet="…")
    assert c.source_uri == "data/org-chart.md"


def test_answer_bundle_defaults_surface_contradictions():
    ab = AnswerBundle(answer="hi")
    assert ab.citations == []
    assert ab.contradictions == []        # present-and-empty, never hidden
    assert ab.as_of_coverage == {}
    assert ab.confidence == 0.0


def test_claim_is_optional_open():
    # Claims coexist; a claim needs only a predicate to exist (subject/object optional
    # because extraction may resolve them in a later pass).
    c = Claim(predicate="revenue", object_value="SGD 14.2M", as_of=date(2026, 3, 31))
    assert c.superseded_by is None and c.valid_to is None


def test_entity_attributes_default_independent():
    a = Entity(canonical_name="A", entity_type="person")
    b = Entity(canonical_name="B", entity_type="person")
    a.attributes["x"] = 1
    assert b.attributes == {}  # no shared mutable default


def test_contradiction_pairs_two_claims():
    cc = Contradiction(predicate="revenue", claim_a_id=1, claim_b_id=2, kind="value_conflict")
    assert cc.claim_a_id == 1 and cc.claim_b_id == 2
