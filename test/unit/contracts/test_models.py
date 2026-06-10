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


# --------------------------------------------------------------------------- #
# SP_009 provenance v2 — additive, backward-compatible fields.
# --------------------------------------------------------------------------- #
def test_claim_evidence_and_offsets_default_none():
    # New provenance fields exist and default to None (an old payload without them
    # still validates — backward compat).
    c = Claim(predicate="revenue", object_value="SGD 14.2M")
    assert c.evidence is None and c.char_start is None and c.char_end is None


def test_claim_carries_evidence_span_and_offsets():
    c = Claim(
        predicate="revenue",
        object_value="SGD 14.2M",
        evidence="Q1 2026 Revenue: SGD 14.2M",
        char_start=10,
        char_end=36,
    )
    assert c.evidence == "Q1 2026 Revenue: SGD 14.2M"
    assert (c.char_start, c.char_end) == (10, 36)
    # round-trips through pydantic JSON (structured-output path)
    assert Claim.model_validate_json(c.model_dump_json()) == c


def test_claim_old_payload_without_new_fields_still_validates():
    # A round-1 extractor payload (no evidence/offsets) must validate unchanged.
    old = {"predicate": "revenue", "object_value": "SGD 14.2M", "as_of": "2026-03-31"}
    c = Claim.model_validate(old)
    assert c.evidence is None and c.char_start is None and c.char_end is None


def test_link_document_id_default_none_and_settable():
    link = Link(from_entity_id=1, to_entity_id=2, link_type="reports_to")
    assert link.document_id is None
    link2 = Link(from_entity_id=1, to_entity_id=2, link_type="reports_to", document_id=7)
    assert link2.document_id == 7
    # old payload (no document_id) validates
    assert Link.model_validate({"from_entity_id": 1, "to_entity_id": 2, "link_type": "owns"}).document_id is None


def test_contradiction_link_refs_default_none_and_settable():
    cc = Contradiction(predicate="reports_to", link_a_id=5, link_b_id=8, kind="source_disagreement")
    assert cc.link_a_id == 5 and cc.link_b_id == 8
    # claims-only contradiction still works (link refs default None)
    cc2 = Contradiction(predicate="revenue", claim_a_id=1, claim_b_id=2, kind="value_conflict")
    assert cc2.link_a_id is None and cc2.link_b_id is None


def test_citation_link_id_anchor():
    # Link citations need an anchor; Citation gains link_id (additive, defaults None).
    cit = Citation(source_uri="data/org-chart.md", link_id=3)
    assert cit.link_id == 3
    assert Citation(source_uri="data/x.md").link_id is None  # backward compat
