"""Grounding assembly + the no-uncited-claims enforcement guard."""

from __future__ import annotations

import math
from datetime import date

from helixpay.contracts import Chunk, Citation, Claim, Contradiction, Link
from helixpay.query.consensus import rollup
from helixpay.query.synthesis import (
    FALLBACK_ANSWER,
    SYNTH_SCHEMA,
    build_grounding,
    enforce_citations,
    render_consensus,
    render_contradictions,
    render_prompt,
)


def _claim(cid, pred, val, evidence=None):
    return Claim(
        id=cid,
        subject_entity_id=1,
        predicate=pred,
        object_value=val,
        as_of=date(2026, 3, 31),
        evidence=evidence,
    )


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
    repo.add_claim_row(
        _claim(10, "revenue", "SGD 14.2M"),
        Citation(source_uri="data/dash.html", as_of=date(2026, 3, 31)),
    )
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
    assert "Unrelated uncited" not in answer  # uncited dropped
    assert cited_ids == [10]
    assert len(citations) == 1 and citations[0].source_uri == "data/dash.html"
    assert conf == 0.8


def test_chunk_citation_is_accepted_when_source_resolves(repo):
    # SP_012 Feature 1: a [S#]-grounded sentence is now a REAL Citation (chunk_id),
    # not the dropped-to-fallback string — get_chunk_sources closes the hole.
    chunk = Chunk(id=5, document_id=1, ordinal=0, text="some context")
    repo.add_chunk_source(
        5, Citation(source_uri="data/notes.md", snippet="some context")
    )
    _, facts = build_grounding([], [chunk])
    output = {
        "sentences": [{"text": "A sentence grounded in a source.", "cites": ["S1"]}]
    }
    answer, citations, cited_ids, conf = enforce_citations(output, facts, repo)
    assert "grounded in a source" in answer
    assert cited_ids == []  # no CLAIM ids (trace stays claim-only)
    assert len(citations) == 1
    assert citations[0].chunk_id == 5 and citations[0].claim_id is None


def test_chunk_citation_with_no_resolvable_source_is_dropped(repo):
    # If get_chunk_sources yields nothing for the chunk, the sentence cannot be cited
    # and is dropped — no fabricated citation.
    chunk = Chunk(id=9, document_id=1, ordinal=0, text="orphan context")
    _, facts = build_grounding([], [chunk])
    output = {
        "sentences": [{"text": "Grounded only in an unsourced chunk.", "cites": ["S1"]}]
    }
    answer, citations, cited_ids, conf = enforce_citations(output, facts, repo)
    assert (
        answer == FALLBACK_ANSWER
        and citations == []
        and cited_ids == []
        and conf == 0.0
    )


def test_link_citation_is_accepted(repo):
    # SP_012 Feature 2: a relationship-grounded sentence cites a real link Citation.
    link = Link(id=3, from_entity_id=1, to_entity_id=2, link_type="reports_to")
    repo.link_citations[3] = Citation(source_uri="data/org-chart.md", link_id=3)
    _, facts = build_grounding([], [], [link], name_map={1: "Alice", 2: "Bob"})
    output = {"sentences": [{"text": "Alice reports to Bob.", "cites": ["L1"]}]}
    answer, citations, cited_ids, conf = enforce_citations(output, facts, repo)
    assert "Alice reports to Bob" in answer
    assert cited_ids == []
    assert len(citations) == 1 and citations[0].link_id == 3


def test_build_grounding_renders_link_markers_with_names():
    link = Link(id=3, from_entity_id=1, to_entity_id=2, link_type="reports_to")
    text, facts = build_grounding([], [], [link], name_map={1: "Alice", 2: "Bob"})
    assert facts["L1"].kind == "link" and facts["L1"].ref_id == 3
    assert "reports_to: Alice → Bob" in text
    # unknown entity id falls back to #id (graph.py id→name Protocol friction)
    text2, _ = build_grounding([], [], [link], name_map={})
    assert "#1" in text2 and "#2" in text2


def test_verbatim_snippet_uses_claim_evidence(repo):
    # SP_012 Feature 5: the citation quotes the claim's verbatim evidence span, not the
    # repository's chunk-prefix snippet.
    claim = _claim(
        10, "revenue", "SGD 14.2M", evidence="Q1 revenue closed at SGD 14.2M"
    )
    repo.add_claim_row(
        claim, Citation(source_uri="data/dash.html", snippet="Q1 revenue closed")
    )
    _, facts = build_grounding([repo.claims[10]], [])
    output = {"sentences": [{"text": "Revenue was SGD 14.2M.", "cites": ["C1"]}]}
    _, citations, _, _ = enforce_citations(output, facts, repo)
    assert (
        citations[0].snippet == "Q1 revenue closed at SGD 14.2M"
    )  # evidence span, overridden


def test_grounding_fact_carries_evidence():
    claim = _claim(10, "revenue", "x", evidence="the verbatim span")
    _, facts = build_grounding([claim], [])
    assert facts["C1"].evidence == "the verbatim span"


def test_render_consensus_references_claim_markers():
    claims = [
        _claim(10, "runway", "18 months"),
        _claim(11, "runway", "18 months"),
        _claim(12, "runway", "24 months"),
    ]
    _, facts = build_grounding(claims, [])
    groups = rollup(claims, lambda p: p)
    block = render_consensus(groups, facts)
    assert "runway" in block
    assert "2 source" in block  # corroborating count
    assert "dissent" in block.lower()
    assert "[C1, C2]" in block or "[C1" in block  # consensus cites real markers


def test_render_contradictions_types_and_attributes():
    claims = [_claim(10, "revenue", "14.2M"), _claim(11, "revenue", "13.9M")]
    _, facts = build_grounding(claims, [])
    con = Contradiction(
        id=1,
        subject_entity_id=1,
        predicate="revenue",
        claim_a_id=10,
        claim_b_id=11,
        kind="value_conflict",
    )
    block = render_contradictions([(con, "value")], facts)
    assert "value conflict" in block.lower()
    assert "[C1]" in block and "[C2]" in block  # both sides attributed to markers


def test_render_contradictions_skips_one_sided_conflict(repo):
    # Only one side resolves a grounding marker (claim 10 present; claim 99 absent).
    # A half-attributed line ("[C1] vs") is worse than silence — the conflict still
    # rides on AnswerBundle.contradictions. So the block must be empty here.
    claims = [_claim(10, "revenue", "14.2M")]
    _, facts = build_grounding(claims, [])
    con = Contradiction(id=1, predicate="revenue", claim_a_id=10, claim_b_id=99, kind="value_conflict")
    assert render_contradictions([(con, "value")], facts) == ""


def test_renderers_empty_when_nothing_to_show():
    _, facts = build_grounding([], [])
    assert render_consensus([], facts) == ""
    assert render_contradictions([], facts) == ""


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
        {},  # no sentences key
        {"sentences": "oops"},  # wrong type
        {"sentences": ["plain string", None, 42]},  # non-dict items
        {"sentences": [{"text": 5, "cites": "C1"}]},  # wrong field types
        {
            "sentences": [{"text": "x", "cites": ["C999", "S1"]}]
        },  # unknown/non-claim markers
        {"sentences": [{"text": "x", "cites": ["L999"]}]},  # unknown link marker
        {"sentences": [{"text": "x", "cites": ["S999"]}]},  # unknown chunk marker
        {
            "sentences": [{"text": "x", "cites": ["C1"]}],
            "confidence": "high",
        },  # bad confidence
        {
            "sentences": [{"text": "x", "cites": ["C1"]}],
            "confidence": float("inf"),
        },  # non-finite
        {
            "sentences": [{"text": "x", "cites": ["C1"]}],
            "confidence": 99.0,
        },  # out of range
    ):
        answer, citations, cited_ids, conf = enforce_citations(bad, facts, repo)
        assert isinstance(answer, str)
        assert isinstance(conf, float)
        assert (
            math.isfinite(conf) and 0.0 <= conf <= 1.0
        )  # always a sane, clamped confidence
        assert all(c.source_uri for c in citations)  # never a fabricated citation


def test_render_prompt_single_pass_no_reexpansion():
    # A question containing the other placeholder literal must not be re-expanded.
    p = render_prompt("what about {grounding}?", "FACTS")
    assert "what about {grounding}?" in p
    assert p.count("FACTS") == 1


def test_schema_shape():
    assert SYNTH_SCHEMA["type"] == "object"
    assert "sentences" in SYNTH_SCHEMA["properties"]
