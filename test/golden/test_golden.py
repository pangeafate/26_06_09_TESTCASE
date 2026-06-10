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
from helixpay.seed.metric_vocab import canonical_key

_ROOT = Path(__file__).resolve().parent.parent.parent
_DATA = _ROOT / "data"


@pytest.fixture(scope="module")
def golden():
    return load_golden(DEFAULT_GOLDEN)


@pytest.fixture(scope="module")
def questions():
    return load_questions(DEFAULT_QUESTIONS)


def test_at_least_thirty_bar_facts(golden):
    # SP_013 grew the set so the recall bar is statistically meaningful (research P0 #1:
    # "a dozen facts cannot support a recall bar"). Wilson intervals are reported on top.
    assert len(golden.bar_facts) >= 30


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


# --------------------------------------------------------------------------- #
# SP_013 — golden-set growth shape: per-format coverage, synonyms, collisions  #
# --------------------------------------------------------------------------- #
def test_each_format_has_at_least_two_bar_facts(golden):
    # The growth must broaden, not just lengthen — ≥2 bar facts per source format
    # (image excepted: caption-only, informational).
    from collections import Counter

    counts = Counter(f.format for f in golden.bar_facts)
    for fmt in KNOWN_FORMATS - {"image"}:
        assert counts.get(fmt, 0) >= 2, f"format {fmt!r} has <2 bar facts ({counts.get(fmt, 0)})"


def test_predicate_synonyms_canonicalize_to_one_key(golden):
    # ARR ≡ "annual recurring revenue" → one canonical key, or contradiction detection
    # silently no-ops (research §F; CLAUDE.md ontology rules). Asserted against the
    # seeded metric_vocab (the in-memory source of truth seeded into the DB table).
    assert golden.predicate_synonyms, "the grown set must carry predicate-synonym probes"
    assert any(s.id == "arr-synonym" for s in golden.predicate_synonyms), "ARR is the headline probe"
    for syn in golden.predicate_synonyms:
        target = canonical_key(syn.canonical)
        for alias in syn.aliases:
            assert canonical_key(alias) == target, (
                f"{syn.id}: alias {alias!r} → {canonical_key(alias)!r} != {target!r}"
            )


def test_entity_collisions_reference_real_names_and_sources(golden):
    assert golden.entity_collisions, "the grown set must carry name-collision probes"
    ids = {c.id for c in golden.entity_collisions}
    assert {"two-marias", "two-tans"} <= ids
    for c in golden.entity_collisions:
        assert len(c.names) >= 2, f"{c.id}: a collision needs ≥2 colliding names"
        assert len(c.contexts) == len(c.names), f"{c.id}: one context per name"
        for ctx in c.contexts:
            uri = ctx.get("source_uri", "")
            assert (_ROOT / uri).is_file(), f"{c.id}: missing context source {uri}"


def test_collision_group_facts_exist_for_each_collision(golden):
    # Each declared collision should have per-side golden claims tagged with its group,
    # so the recall check exercises the same names the collision probe asserts.
    groups = {f.collision_group for f in golden.facts if f.collision_group}
    assert "maria" in groups and "tan" in groups
