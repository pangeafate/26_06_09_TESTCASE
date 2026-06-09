"""HelixQueryEngine wiring: Protocol conformance + end-to-end with fakes."""

from __future__ import annotations

from datetime import date

import pytest

from helixpay.contracts import (
    AnswerBundle,
    Citation,
    Claim,
    Contradiction,
    Entity,
    Link,
    OrgNode,
    QueryEngine,
)
from helixpay.query import HelixQueryEngine
from helixpay.query.clients import Embedder, Synthesizer

from fakes import FakeEmbedder, FakeSynthesizer


def _revenue_world(repo):
    rid = repo.add_entity(Entity(canonical_name="Revenue", entity_type="metric"))
    repo.vocab = {"revenue": "revenue"}
    repo.add_claim_row(
        Claim(id=10, subject_entity_id=rid, predicate="revenue", object_value="SGD 14.2M", as_of=date(2026, 3, 31)),
        Citation(source_uri="data/dashboards/april.html", as_of=date(2026, 3, 31)),
    )
    repo.add_claim_row(
        Claim(id=11, subject_entity_id=rid, predicate="revenue", object_value="SGD 13.9M", as_of=date(2026, 3, 31)),
        Citation(source_uri="data/board-deck.pdf", as_of=date(2026, 3, 31)),
    )
    repo.contradictions = [
        Contradiction(id=1, subject_entity_id=rid, predicate="revenue",
                      claim_a_id=10, claim_b_id=11, kind="value_conflict"),
    ]
    return rid


def _engine(repo, synth=None):
    return HelixQueryEngine(repo, FakeEmbedder(), synth or FakeSynthesizer(), k=8)


def test_fakes_satisfy_seam_protocols():
    assert isinstance(FakeEmbedder(), Embedder)
    assert isinstance(FakeSynthesizer(), Synthesizer)


def test_engine_satisfies_queryengine_protocol(repo):
    engine = _engine(repo)
    assert isinstance(engine, QueryEngine)


def test_engine_methods_return_contract_types(repo):
    _revenue_world(repo)
    repo.org_tree = OrgNode(entity_id=1, name="Wei Chen", children=[], dotted_reports=[])
    engine = _engine(repo)
    assert isinstance(engine.ask("hello"), AnswerBundle)
    assert isinstance(engine.get_entity("Revenue"), dict)         # EntityDetail is a TypedDict
    assert isinstance(engine.get_org_chart(), dict)               # OrgNode is a TypedDict
    assert isinstance(engine.find_contradictions(), list)


def test_ask_surfaces_contradiction_with_both_sides_and_citations(repo):
    _revenue_world(repo)
    synth = FakeSynthesizer({
        "sentences": [
            {"text": "The dashboard reports SGD 14.2M.", "cites": ["C1"]},
            {"text": "The board deck reports SGD 13.9M.", "cites": ["C2"]},
            {"text": "These two sources disagree.", "cites": ["C1", "C2"]},
        ],
        "confidence": 0.7,
    })
    bundle = _engine(repo, synth).ask("What was HelixPay's Q1 2026 revenue?")
    # contradiction surfaced with both sides attributed
    assert len(bundle.contradictions) == 1
    assert bundle.contradictions[0].claim_a_id == 10
    assert bundle.contradictions[0].claim_b_id == 11
    # both conflicting claims cited (zero uncited claims, both values attributed)
    assert "14.2M" in bundle.answer and "13.9M" in bundle.answer
    uris = {c.source_uri for c in bundle.citations}
    assert uris == {"data/dashboards/april.html", "data/board-deck.pdf"}
    assert bundle.as_of_coverage["latest"] == "2026-03-31"
    assert bundle.confidence == 0.7


def test_ask_keeps_contradiction_even_when_answer_uncited(repo):
    # Contradictions are first-class — surfaced even if synthesis cited nothing.
    _revenue_world(repo)
    synth = FakeSynthesizer({"sentences": [{"text": "Vague uncited claim.", "cites": []}]})
    bundle = _engine(repo, synth).ask("What was Q1 revenue?")
    assert bundle.answer == "I could not find sufficient cited evidence to answer that."
    assert bundle.citations == []
    assert len(bundle.contradictions) == 1          # never hidden


def test_ask_populates_trace(repo):
    _revenue_world(repo)
    synth = FakeSynthesizer({"sentences": [{"text": "SGD 14.2M.", "cites": ["C1"]}], "confidence": 0.6})
    engine = _engine(repo, synth)
    engine.ask("What was HelixPay's Q1 2026 revenue?")
    assert engine.last_trace["route"] == "both"
    assert 10 in engine.last_trace["cited_claim_ids"]
    assert engine.last_trace["contradiction_ids"] == [1]


def test_ask_surfaces_contradiction_even_when_subject_entity_unresolved(repo):
    # The "Revenue" entity is NOT registered (resolve_entity returns None), but a
    # value_conflict on predicate "revenue" exists. The topic path must surface it
    # and both sides must still be citeable (reviews code-C1 + code-C2 together).
    sid = 5  # subject id with no entity name → resolve_entity("revenue") is None
    repo.vocab = {"revenue": "revenue"}
    repo.add_claim_row(
        Claim(id=10, subject_entity_id=sid, predicate="revenue", object_value="SGD 14.2M", as_of=date(2026, 3, 31)),
        Citation(source_uri="data/dash.html", as_of=date(2026, 3, 31)),
    )
    repo.add_claim_row(
        Claim(id=11, subject_entity_id=sid, predicate="revenue", object_value="SGD 13.9M", as_of=date(2026, 3, 31)),
        Citation(source_uri="data/board.pdf", as_of=date(2026, 3, 31)),
    )
    repo.contradictions = [
        Contradiction(id=1, subject_entity_id=sid, predicate="revenue", claim_a_id=10, claim_b_id=11),
    ]
    synth = FakeSynthesizer({"sentences": [
        {"text": "Dashboard 14.2M.", "cites": ["C1"]},
        {"text": "Board 13.9M.", "cites": ["C2"]},
    ]})
    bundle = _engine(repo, synth).ask("What was Q1 revenue?")
    assert len(bundle.contradictions) == 1
    assert {c.source_uri for c in bundle.citations} == {"data/dash.html", "data/board.pdf"}


def test_find_contradictions_by_topic(repo):
    _revenue_world(repo)
    got = _engine(repo).find_contradictions("revenue")
    assert [c.id for c in got] == [1]


def test_get_org_chart_root(repo):
    repo.add_entity(Entity(canonical_name="Wei Chen", entity_type="person", attributes={"role": "CEO"}))
    repo.org_tree = OrgNode(entity_id=1, name="Wei Chen", children=[], dotted_reports=[])
    tree = _engine(repo).get_org_chart()
    assert tree["name"] == "Wei Chen" and tree["role"] == "CEO"
