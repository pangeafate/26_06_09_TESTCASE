"""Unit tests for the pure claim/link assembly + supersession decision (SP_018).

Covers ``helixpay.ingest.assemble`` — the domain rules lifted out of
``pipeline._ingest_document`` / ``_maybe_supersede``: building contract ``Claim``/``Link``
rows from extraction output, the self-loop drop, and the same-source supersession
predicate. No Repository, no DB.
"""

from __future__ import annotations

from datetime import date

from helixpay.contracts import Claim
from helixpay.ingest.assemble import build_claim, build_link, should_supersede
from helixpay.ingest.extract.schemas import ClaimOut, RelationOut

DOC_AS_OF = date(2025, 1, 1)


# --------------------------------------------------------------------------- #
# build_claim
# --------------------------------------------------------------------------- #
def test_build_claim_uses_claim_as_of_when_present():
    co = ClaimOut(subject="Acme", predicate="arr", object_value="5", as_of="2025-03-01", confidence=0.8)
    claim = build_claim(
        co, subject_id=7, predicate="ARR", chunk_id=3, document_id=9, doc_as_of=DOC_AS_OF
    )
    assert isinstance(claim, Claim)
    assert claim.subject_entity_id == 7
    assert claim.predicate == "ARR"  # canonicalized predicate passed in by caller
    assert claim.object_value == "5"
    assert claim.as_of == date(2025, 3, 1)  # claim's own as_of wins
    assert claim.confidence == 0.8
    assert claim.source_chunk_id == 3 and claim.document_id == 9


def test_build_claim_falls_back_to_doc_as_of():
    co = ClaimOut(subject="Acme", predicate="arr", object_value="5", as_of=None)
    claim = build_claim(
        co, subject_id=1, predicate="arr", chunk_id=1, document_id=1, doc_as_of=DOC_AS_OF
    )
    assert claim.as_of == DOC_AS_OF  # a date, not the isoformat string


# --------------------------------------------------------------------------- #
# build_link
# --------------------------------------------------------------------------- #
def test_build_link_builds_a_link():
    rel = RelationOut(from_entity="Maria", to_entity="HelixPay", link_type="member_of", as_of="2025-02-01")
    link = build_link(rel, from_id=2, to_id=5, chunk_id=4, doc_as_of=DOC_AS_OF)
    assert link is not None
    assert link.from_entity_id == 2 and link.to_entity_id == 5
    assert link.link_type == "member_of"
    assert link.as_of == date(2025, 2, 1)
    assert link.source_chunk_id == 4


def test_build_link_drops_self_loop_as_none():
    rel = RelationOut(from_entity="A", to_entity="A", link_type="reports_to")
    assert build_link(rel, from_id=9, to_id=9, chunk_id=1, doc_as_of=DOC_AS_OF) is None


def test_build_link_falls_back_to_doc_as_of():
    rel = RelationOut(from_entity="X", to_entity="Y", link_type="owns", as_of=None)
    link = build_link(rel, from_id=1, to_id=2, chunk_id=1, doc_as_of=DOC_AS_OF)
    assert link is not None and link.as_of == DOC_AS_OF


# --------------------------------------------------------------------------- #
# should_supersede
# --------------------------------------------------------------------------- #
def _existing(value, as_of, *, cid=1, superseded_by=None):
    return Claim(id=cid, predicate="arr", object_value=value, as_of=as_of, superseded_by=superseded_by)


def _new(value, as_of):
    return Claim(predicate="arr", object_value=value, as_of=as_of)


def test_supersede_true_for_strictly_older_conflicting_same_source():
    existing = _existing("5", date(2025, 1, 1))
    new = _new("9", date(2025, 4, 1))
    assert should_supersede(existing, new, prior_uri="data/x.md", source_uri="data/x.md") is True


def test_no_supersede_when_new_has_no_as_of():
    existing = _existing("5", date(2025, 1, 1))
    new = _new("9", None)
    assert should_supersede(existing, new, prior_uri="data/x.md", source_uri="data/x.md") is False


def test_no_supersede_when_already_superseded():
    existing = _existing("5", date(2025, 1, 1), superseded_by=42)
    new = _new("9", date(2025, 4, 1))
    assert should_supersede(existing, new, prior_uri="data/x.md", source_uri="data/x.md") is False


def test_no_supersede_when_existing_not_strictly_older():
    existing = _existing("5", date(2025, 4, 1))
    new = _new("9", date(2025, 4, 1))  # equal as_of -> not strictly older
    assert should_supersede(existing, new, prior_uri="data/x.md", source_uri="data/x.md") is False


def test_no_supersede_when_values_do_not_conflict():
    existing = _existing("5", date(2025, 1, 1))
    new = _new("5", date(2025, 4, 1))  # same value
    assert should_supersede(existing, new, prior_uri="data/x.md", source_uri="data/x.md") is False


def test_no_supersede_across_different_sources_thats_a_contradiction():
    existing = _existing("5", date(2025, 1, 1))
    new = _new("9", date(2025, 4, 1))
    assert should_supersede(existing, new, prior_uri="data/other.md", source_uri="data/x.md") is False


def test_no_supersede_when_existing_has_no_id():
    # the pure contract promises to handle an unpersisted existing claim
    existing = _existing("5", date(2025, 1, 1), cid=None)
    new = _new("9", date(2025, 4, 1))
    assert should_supersede(existing, new, prior_uri="data/x.md", source_uri="data/x.md") is False
