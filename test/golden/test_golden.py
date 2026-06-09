"""Shape + coverage tests for the golden set and the question set.

A wrong oracle is worse than none, so these assert the ground truth itself is
well-formed: every fact has the required fields, every source_uri points at a real
raw file, every format is covered on the recall bar, the planted contradiction is
present with two distinct dated sources, and every question check is in the closed
vocabulary. No DB required.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from eval.models import KNOWN_CHECKS, KNOWN_FORMATS
from eval.run import DEFAULT_GOLDEN, DEFAULT_QUESTIONS, load_golden, load_questions

_ROOT = Path(__file__).resolve().parent.parent.parent
_DATA = _ROOT / "data"


@pytest.fixture(scope="module")
def golden():
    return load_golden(DEFAULT_GOLDEN)


@pytest.fixture(scope="module")
def questions():
    return load_questions(DEFAULT_QUESTIONS)


def test_at_least_twelve_bar_facts(golden):
    assert len(golden.bar_facts) >= 12


def test_every_source_uri_exists(golden):
    for f in golden.facts:
        assert (_ROOT / f.source_uri).is_file(), f"{f.id}: missing {f.source_uri}"


def test_every_fact_has_core_fields(golden):
    for f in golden.facts:
        assert f.subject and f.predicate and f.value and f.source_uri, f.id
        assert isinstance(f.as_of, date) or f.as_of is None, f.id


def test_every_format_covered_on_the_bar(golden):
    fmts = {f.format for f in golden.bar_facts}
    # every format except image (caption-only, informational) is on the recall bar
    required = KNOWN_FORMATS - {"image"}
    missing = required - fmts
    assert not missing, f"formats not on the recall bar: {missing}"


def test_link_facts_have_endpoints(golden):
    for f in golden.facts:
        if f.kind.value == "link":
            assert f.from_ and f.to and f.link_type, f"{f.id}: link missing from/to/link_type"


def test_image_facts_are_informational_only(golden):
    for f in golden.facts:
        if f.format == "image":
            assert f.recall_bar is False, f"{f.id}: image facts must be recall_bar:false (§11)"


def test_planted_contradiction_present_with_two_dated_sources(golden):
    by_id = {f.id: f for f in golden.facts}
    confl = next((c for c in golden.contradictions if c.id == "confluence-ga-timeline"), None)
    assert confl is not None, "the real planted contradiction must be captured"
    a, b = by_id[confl.claim_a], by_id[confl.claim_b]
    assert a.source_uri != b.source_uri, "contradiction sides must be different sources"
    assert a.as_of != b.as_of, "contradiction sides must carry different as_of dates"
    assert a.value != b.value, "contradiction sides must assert conflicting values"


def test_no_revenue_contradiction_is_claimed(golden):
    # The honest-oracle correction: revenue is consistent in raw data; no golden
    # contradiction may be keyed on revenue (guards against re-introducing the
    # synthetic fixture conflict as ground truth).
    for c in golden.contradictions:
        assert c.predicate != "revenue", f"{c.id}: revenue is consistent in raw data"


def test_questions_present_and_checks_known(questions):
    assert len(questions) >= 5
    for q in questions:
        assert q.q.strip(), q.id
        assert q.checks, f"{q.id}: no checks"
        for chk in q.checks:
            assert chk in KNOWN_CHECKS, f"{q.id}: unknown check '{chk}'"


def test_a_question_exercises_the_real_contradiction(questions):
    confl_qs = [q for q in questions if "surfaces_contradiction" in q.checks]
    assert confl_qs, "at least one question must require surfacing a contradiction"
    assert any(q.contradiction_ref == "confluence-ga-timeline" for q in confl_qs)


def test_fact_and_question_ids_unique(golden, questions):
    fids = [f.id for f in golden.facts]
    qids = [q.id for q in questions]
    assert len(fids) == len(set(fids)), "duplicate golden fact id"
    assert len(qids) == len(set(qids)), "duplicate question id"


def test_honest_no_false_contradiction_guard_exists(questions):
    # At least one question must reward the truthful "the sources agree" answer,
    # so the system is penalized for hallucinating a revenue conflict.
    assert any("no_false_contradiction" in q.checks for q in questions)
