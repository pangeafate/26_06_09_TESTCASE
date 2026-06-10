"""Grounding assembly + the no-uncited-claims enforcement guard."""

from __future__ import annotations

from datetime import date

from helixpay.contracts import Chunk, Citation, Claim
from helixpay.query.synthesis import (
    FALLBACK_ANSWER,
    SYNTH_SCHEMA,
    build_grounding,
    enforce_citations,
    render_prompt,
)


def _claim(cid, pred, val):
    return Claim(id=cid, subject_entity_id=1, predicate=pred, object_value=val, as_of=date(2026, 3, 31))


def test_build_grounding_markers_and_index():
    claims = [_claim(10, "revenue", "SGD 14.2M"), _claim(11, "revenue", "SGD 13.9M")]
    chunks = [Chunk(id=5, document_id=1, ordinal=0, text="Q1 revenue closed at 13.9M")]
    text, facts = build_grounding(claims, chunks)
    assert set(facts) == {"C1", "C2", "S1"}
    assert facts["C1"].kind == "claim" and facts["C1"].ref_id == 10
    assert facts["S1"].kind == "chunk" and facts["S1"].ref_id == 5
    assert "[C1]" in text and "[S1]" in text


def test_render_prompt_fills_template():
    p = render_prompt("What was Q1 revenue?", "[C1] (claim) revenue: SGD 14.2M")
    assert "What was Q1 revenue?" in p
    assert "[C1] (claim) revenue: SGD 14.2M" in p


def test_enforce_keeps_cited_drops_uncited(repo):
    repo.add_claim_row(_claim(10, "revenue", "SGD 14.2M"),
                       Citation(source_uri="data/dash.html", as_of=date(2026, 3, 31)))
    _, facts = build_grounding([repo.claims[10]], [])
    output = {
        "sentences": [
            {"text": "Q1 revenue was SGD 14.2M.", "cites": ["C1"]},
            {"text": "Unrelated uncited sentence.", "cites": []},
        ],
        "confidence": 0.8,
    }
    answer, citations, cited_ids, conf = enforce_citations(output, facts, repo)
    assert "SGD 14.2M" in answer
    assert "Unrelated uncited" not in answer          # uncited dropped
    assert cited_ids == [10]
    assert len(citations) == 1 and citations[0].source_uri == "data/dash.html"
    assert conf == 0.8


def test_chunk_only_citation_is_not_accepted(repo):
    chunk = Chunk(id=5, document_id=1, ordinal=0, text="some context")
    _, facts = build_grounding([], [chunk])
    output = {"sentences": [{"text": "A claim backed only by a chunk.", "cites": ["S1"]}]}
    answer, citations, cited_ids, conf = enforce_citations(output, facts, repo)
    assert answer == FALLBACK_ANSWER       # nothing claim-backed survived
    assert citations == [] and cited_ids == [] and conf == 0.0


def test_all_uncited_degrades_safely(repo):
    _, facts = build_grounding([_claim(10, "revenue", "x")], [])
    output = {"sentences": [{"text": "No citation here.", "cites": []}]}
    answer, citations, cited_ids, conf = enforce_citations(output, facts, repo)
    assert answer == FALLBACK_ANSWER and citations == [] and conf == 0.0


def test_enforce_is_robust_to_malformed_output(repo):
    # Adversarial / malformed structured output must not crash and must not
    # fabricate a citation (security hardening).
    _, facts = build_grounding([_claim(10, "revenue", "x")], [])
    for bad in (
        {},                                            # no sentences key
        {"sentences": "oops"},                         # wrong type
        {"sentences": ["plain string", None, 42]},     # non-dict items
        {"sentences": [{"text": 5, "cites": "C1"}]},   # wrong field types
        {"sentences": [{"text": "x", "cites": ["C999", "S1"]}]},  # unknown/non-claim markers
        {"sentences": [{"text": "x", "cites": ["C1"]}], "confidence": "high"},  # bad confidence
    ):
        answer, citations, cited_ids, conf = enforce_citations(bad, facts, repo)
        assert isinstance(answer, str)
        assert isinstance(conf, float)
        assert all(c.source_uri for c in citations)    # never a fabricated citation


def test_render_prompt_single_pass_no_reexpansion():
    # A question containing the other placeholder literal must not be re-expanded.
    p = render_prompt("what about {grounding}?", "FACTS")
    assert "what about {grounding}?" in p
    assert p.count("FACTS") == 1


def test_schema_shape():
    assert SYNTH_SCHEMA["type"] == "object"
    assert "sentences" in SYNTH_SCHEMA["properties"]
