"""Unit tests for the pure citation-resolution core (SP_018 RDD/SRP split).

These exercise ``helixpay.query.citations`` directly — no Repository, no LLM. They
cover the logic that previously lived inside ``synthesis.enforce_citations``: ref-id
bucketing, sentence keep/drop, citation + claim-id dedup, the fallback path, and the
post-dedup confidence math (incl. adversarial / non-finite input).
"""

from __future__ import annotations

import math

import pytest

from helixpay.contracts import Citation
from helixpay.query.citations import (
    FALLBACK_ANSWER,
    collect_ref_ids,
    resolve_cited_sentences,
)
from helixpay.query.synthesis import GroundingFact


def _fact(marker, kind, ref_id, evidence=None):
    return GroundingFact(
        marker=marker, kind=kind, ref_id=ref_id, text="t", evidence=evidence
    )


def _cite(*, claim_id=None, chunk_id=None, link_id=None, uri="u", snippet="s"):
    return Citation(
        source_uri=uri,
        snippet=snippet,
        claim_id=claim_id,
        chunk_id=chunk_id,
        link_id=link_id,
    )


# --------------------------------------------------------------------------- #
# collect_ref_ids
# --------------------------------------------------------------------------- #
def test_collect_buckets_by_kind_first_seen_and_deduped():
    facts = {
        "C1": _fact("C1", "claim", 10),
        "C2": _fact("C2", "claim", 11),
        "S1": _fact("S1", "chunk", 20),
        "L1": _fact("L1", "link", 30),
    }
    sentences = [
        {"text": "a", "cites": ["C1", "S1"]},
        {"text": "b", "cites": ["C2", "C1", "L1"]},  # C1 repeat -> deduped
    ]
    claim_ids, chunk_ids, link_ids = collect_ref_ids(sentences, facts)
    assert claim_ids == [10, 11]  # first-seen order, C1 not duplicated
    assert chunk_ids == [20]
    assert link_ids == [30]


def test_collect_ignores_unknown_markers_and_null_ref_ids():
    facts = {
        "C1": _fact("C1", "claim", None),  # null ref_id -> skipped
        "S1": _fact("S1", "chunk", 5),
    }
    sentences = [{"text": "a", "cites": ["C1", "NOPE", "S1"]}]
    claim_ids, chunk_ids, link_ids = collect_ref_ids(sentences, facts)
    assert claim_ids == []
    assert chunk_ids == [5]
    assert link_ids == []


def test_collect_robust_to_non_list_sentences():
    assert collect_ref_ids("garbage", {}) == ([], [], [])
    assert collect_ref_ids([{"text": "x"}], {}) == ([], [], [])  # no cites key


# --------------------------------------------------------------------------- #
# resolve_cited_sentences
# --------------------------------------------------------------------------- #
def test_keeps_only_sentences_whose_markers_resolve():
    facts = {"C1": _fact("C1", "claim", 1), "C2": _fact("C2", "claim", 2)}
    sentences = [
        {"text": "kept", "cites": ["C1"]},
        {"text": "dropped — unresolved cite", "cites": ["C2"]},  # 2 not in claim_cites
    ]
    claim_cites = {1: _cite(claim_id=1)}
    answer, citations, cited_claim_ids, conf = resolve_cited_sentences(
        sentences, facts, claim_cites, {}, {}, raw_confidence=0.7
    )
    assert answer == "kept"
    assert [c.claim_id for c in citations] == [1]
    assert cited_claim_ids == [1]
    assert conf == 0.7


def test_chunk_and_link_citations_merge_but_cited_claim_ids_stays_claim_only():
    facts = {
        "C1": _fact("C1", "claim", 1),
        "S1": _fact("S1", "chunk", 9),
        "L1": _fact("L1", "link", 7),
    }
    sentences = [{"text": "x", "cites": ["C1", "S1", "L1"]}]
    answer, citations, cited_claim_ids, _ = resolve_cited_sentences(
        sentences,
        facts,
        {1: _cite(claim_id=1)},
        {9: _cite(chunk_id=9)},
        {7: _cite(link_id=7)},
        raw_confidence=0.5,
    )
    assert answer == "x"
    assert len(citations) == 3  # all three kinds merged into citations
    assert cited_claim_ids == [1]  # claim-only


def test_citation_dedup_across_sentences():
    facts = {"C1": _fact("C1", "claim", 1)}
    sentences = [
        {"text": "one", "cites": ["C1"]},
        {"text": "two", "cites": ["C1"]},
    ]
    _, citations, cited_claim_ids, _ = resolve_cited_sentences(
        sentences, facts, {1: _cite(claim_id=1)}, {}, {}, raw_confidence=0.5
    )
    assert len(citations) == 1  # same cite not repeated
    assert cited_claim_ids == [1]


def test_empty_text_sentence_is_dropped_even_if_cite_resolves():
    facts = {"C1": _fact("C1", "claim", 1)}
    sentences = [{"text": "   ", "cites": ["C1"]}]
    answer, citations, cited_claim_ids, conf = resolve_cited_sentences(
        sentences, facts, {1: _cite(claim_id=1)}, {}, {}, raw_confidence=0.9
    )
    assert answer == FALLBACK_ANSWER
    assert citations == [] and cited_claim_ids == [] and conf == 0.0


def test_nothing_resolves_returns_fallback_with_no_fabricated_citations():
    facts = {"C1": _fact("C1", "claim", 1)}
    sentences = [{"text": "x", "cites": ["C1"]}]
    answer, citations, cited_claim_ids, conf = resolve_cited_sentences(
        sentences, facts, {}, {}, {}, raw_confidence=0.8  # empty cite maps
    )
    assert answer == FALLBACK_ANSWER
    assert citations == [] and cited_claim_ids == [] and conf == 0.0


def test_non_finite_confidence_falls_back_to_count_based():
    facts = {"C1": _fact("C1", "claim", 1)}
    sentences = [{"text": "x", "cites": ["C1"]}]
    _, citations, _, conf = resolve_cited_sentences(
        sentences, facts, {1: _cite(claim_id=1)}, {}, {}, raw_confidence=float("nan")
    )
    # fallback: min(0.9, 0.3 + 0.15 * len(citations)) with 1 citation -> 0.45
    assert math.isfinite(conf)
    assert conf == pytest.approx(0.45)


def test_infinite_confidence_falls_back_like_nan():
    facts = {"C1": _fact("C1", "claim", 1)}
    sentences = [{"text": "x", "cites": ["C1"]}]
    _, _, _, conf = resolve_cited_sentences(
        sentences, facts, {1: _cite(claim_id=1)}, {}, {}, raw_confidence=float("inf")
    )
    assert math.isfinite(conf)
    assert conf == pytest.approx(0.45)  # count-based fallback, not clamped to 1.0


def test_confidence_clamped_into_unit_range():
    facts = {"C1": _fact("C1", "claim", 1)}
    sentences = [{"text": "x", "cites": ["C1"]}]
    _, _, _, conf = resolve_cited_sentences(
        sentences, facts, {1: _cite(claim_id=1)}, {}, {}, raw_confidence=5.0
    )
    assert conf == 1.0
