"""SP_013 eval-rigor tests — the grader's new statistical + structural checks.

Covers the rigor upgrades from research/evaluation-and-ground-truth-best-practices.md:
Wilson confidence intervals, macro-per-predicate recall, the shared-normalize value
match, WikiContradict 3-class contradiction scoring + both-claim-id assertion, the
name-collision entity_id assertion, and As-of Correctness. No DB — drives the frozen
contract types and small fakes only, so the oracle stays author-independent.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Optional

import pytest

from helixpay.contracts import (
    AnswerBundle,
    Citation,
    Claim,
    Contradiction,
    Entity,
)
from eval.models import (
    ContradictionClass,
    ExtractionReport,
    FactVerdict,
    GoldenContradiction,
    Question,
    Verdict,
    wilson_interval,
)
from eval.run import (
    DEFAULT_GOLDEN,
    as_of_correctness,
    check_answers,
    check_entity_collisions,
    load_golden,
    score_contradiction,
    _values_match,
)


# --------------------------------------------------------------------------- #
# Wilson score interval (research P0 #1 — report an interval, not a bare ratio)
# --------------------------------------------------------------------------- #
def test_wilson_interval_brackets_point_estimate():
    low, high = wilson_interval(found=24, total=30)
    p = 24 / 30
    assert 0.0 <= low < p < high <= 1.0
    # 80% over n=30 is wide — the whole point (a few-fact "bar" is noise).
    assert (high - low) > 0.20


def test_wilson_interval_edge_cases():
    assert wilson_interval(0, 0) == (0.0, 0.0)          # n=0 must not divide-by-zero
    low0, high0 = wilson_interval(0, 30)                # p=0 → non-zero upper bound
    assert low0 == 0.0 and 0.0 < high0 < 0.2
    low1, high1 = wilson_interval(30, 30)               # p=1 → non-unit lower bound
    assert 0.8 < low1 < 1.0 and high1 == 1.0


def test_wilson_interval_bounds_are_clamped_to_unit():
    for found in range(0, 6):
        low, high = wilson_interval(found, 5)
        assert 0.0 <= low <= high <= 1.0


# --------------------------------------------------------------------------- #
# Macro-per-predicate recall (research P0 #4 — micro hides rare-predicate misses)
# --------------------------------------------------------------------------- #
def test_macro_recall_weights_predicates_equally():
    # 4 facts on a common predicate (all found) + 1 fact on a rare predicate (missed).
    # micro = 4/5 = 0.80; macro = mean(1.0, 0.0) = 0.50 — macro exposes the rare miss.
    verdicts = [
        FactVerdict("a", Verdict.found, predicate="revenue"),
        FactVerdict("b", Verdict.found, predicate="revenue"),
        FactVerdict("c", Verdict.found, predicate="revenue"),
        FactVerdict("d", Verdict.found, predicate="revenue"),
        FactVerdict("e", Verdict.missing, predicate="dotted_line_to"),
    ]
    report = ExtractionReport(verdicts=verdicts)
    assert math.isclose(report.recall, 0.8)
    assert math.isclose(report.macro_recall, 0.5)
    per_pred = report.per_predicate_recall
    assert math.isclose(per_pred["revenue"][2], 1.0)
    assert math.isclose(per_pred["dotted_line_to"][2], 0.0)


def test_macro_recall_zero_when_empty():
    assert ExtractionReport(verdicts=[]).macro_recall == 0.0


# --------------------------------------------------------------------------- #
# Value match routes through the SHARED normalizer (review C1)                 #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "golden,claimed",
    [
        ("SGD 14.2M", "14.2M"),          # currency + magnitude (shared numeric path)
        ("SGD 14.2M", "$14.2 million"),  # word-magnitude
        ("−SGD 2.1M", "-2.1M"),          # unicode minus folded
        ("3,424", "3424"),               # digit-grouping commas
        ("45.1%", "45.1 %"),             # percent + spacing
    ],
)
def test_values_match_numeric_via_shared_normalize(golden, claimed):
    assert _values_match(golden, claimed) is True


@pytest.mark.parametrize(
    "golden,claimed",
    [
        ("end of Q3 2026", "the GA target is end of Q3 2026 per the board deck"),  # substring fallback
        ("Sara Wijaya", "sara wijaya"),  # case-insensitive text
    ],
)
def test_values_match_text_fallback(golden, claimed):
    assert _values_match(golden, claimed) is True


def test_values_match_rejects_genuine_mismatch():
    assert _values_match("14.2M", "13.9M") is False     # the synthetic-fixture trap
    assert _values_match("end of June 2026", "end of Q3 2026") is False


@pytest.mark.parametrize("golden,claimed", [("41", "241"), ("22", "422"), ("412", "4120")])
def test_values_match_no_numeric_substring_false_positive(golden, claimed):
    # post-impl H1: a short number must NOT match a larger number via the text substring
    # fallback ("41" in "241"). The commit-count collision probes depend on this.
    assert _values_match(golden, claimed) is False


# --------------------------------------------------------------------------- #
# 3-class contradiction scoring + both-claim-id assertion (research P1 #5)     #
# --------------------------------------------------------------------------- #
def _golden_contradiction():
    return GoldenContradiction(
        id="confluence-ga-timeline",
        kind="temporal",
        subject="Project Confluence",
        predicate="ga_target",
        claim_a="md-allhands-confluence-june",
        claim_b="pdf-boarddeck-confluence-q3",
        expected="surfaced",
    )


def test_contradiction_correct_when_both_ids_present():
    bundle = AnswerBundle(
        answer="Sources disagree: June vs Q3.",
        citations=[
            Citation(source_uri="data/all-hands-2026-04-15.md", as_of=date(2026, 4, 15)),
            Citation(source_uri="data/board-deck-q1-2026.pdf", as_of=date(2026, 5, 12)),
        ],
        contradictions=[
            Contradiction(predicate="ga_target", kind="temporal", claim_a_id=11, claim_b_id=22)
        ],
    )
    v = score_contradiction(_golden_contradiction(), bundle)
    assert v.verdict is ContradictionClass.correct
    assert v.both_ids_present is True


def test_contradiction_partial_when_one_side_only():
    # A contradiction row exists for the right predicate but only one claim id is set
    # (one side dropped) → Partial, both_ids_present False.
    bundle = AnswerBundle(
        answer="GA is end of Q3.",
        contradictions=[Contradiction(predicate="ga_target", kind="temporal", claim_a_id=11)],
    )
    v = score_contradiction(_golden_contradiction(), bundle)
    assert v.verdict is ContradictionClass.partial
    assert v.both_ids_present is False


def test_contradiction_incorrect_when_silently_merged():
    # No contradiction surfaced on the predicate at all → silent merge → Incorrect.
    bundle = AnswerBundle(answer="GA is end of Q3 2026.", contradictions=[])
    v = score_contradiction(_golden_contradiction(), bundle)
    assert v.verdict is ContradictionClass.incorrect
    assert v.both_ids_present is False


def test_contradiction_requires_both_ids_distinct():
    # Same id on both sides is NOT two sides — partial, not correct.
    bundle = AnswerBundle(
        answer="x",
        contradictions=[Contradiction(predicate="ga_target", claim_a_id=11, claim_b_id=11)],
    )
    v = score_contradiction(_golden_contradiction(), bundle)
    assert v.both_ids_present is False
    assert v.verdict is ContradictionClass.partial


def test_contradiction_is_subject_aware():
    # post-impl MEDIUM: a contradiction on the right predicate but the WRONG subject must
    # NOT score CORRECT. With the golden subject resolved to id 5, a row on subject 999
    # is not a match → Incorrect; the same row on subject 5 → Correct.
    wrong_subject = AnswerBundle(
        answer="x",
        contradictions=[
            Contradiction(predicate="ga_target", subject_entity_id=999, claim_a_id=1, claim_b_id=2)
        ],
    )
    v = score_contradiction(_golden_contradiction(), wrong_subject, subject_entity_id=5)
    assert v.verdict is ContradictionClass.incorrect

    right_subject = AnswerBundle(
        answer="x",
        contradictions=[
            Contradiction(predicate="ga_target", subject_entity_id=5, claim_a_id=1, claim_b_id=2)
        ],
    )
    v2 = score_contradiction(_golden_contradiction(), right_subject, subject_entity_id=5)
    assert v2.verdict is ContradictionClass.correct


# --------------------------------------------------------------------------- #
# Name-collision entity_id assertion (research P1 #7)                          #
# --------------------------------------------------------------------------- #
class _CollisionRepo:
    """Resolves a bare name to different entities depending on the context's source —
    models a roster-first resolver that keeps the two Marias / two Tans distinct."""

    def __init__(self, by_source: dict[tuple[str, str], int]):
        self._by_source = by_source  # (name.lower(), source_uri) -> entity_id

    def resolve_entity(self, name, entity_type=None, context=None):
        src = (context or {}).get("source_uri", "")
        eid = self._by_source.get((name.lower(), src))
        return Entity(id=eid, canonical_name=name, entity_type="person") if eid else None


def test_entity_collisions_pass_when_distinct():
    golden = load_golden(DEFAULT_GOLDEN)
    assert golden.entity_collisions, "the grown golden set must carry collision probes"
    repo = _CollisionRepo(
        {
            ("maria santos", "data/interviews/customer_success/Maria_Santos.md"): 1,
            ("maria silva", "data/org-chart.md"): 2,
            ("daniel tan", "data/org-chart.md"): 3,
            ("tan wei ming", "data/code/contributors-analysis-q1-2026.md"): 4,
        }
    )
    verdicts = check_entity_collisions(repo, golden.entity_collisions)
    assert verdicts and all(v.passed for v in verdicts)


def test_entity_collisions_fail_when_collapsed():
    # Both Marias resolve to the SAME id → the trap collapsed → fail.
    repo = _CollisionRepo(
        {
            ("maria santos", "data/interviews/customer_success/Maria_Santos.md"): 9,
            ("maria silva", "data/org-chart.md"): 9,
        }
    )
    golden = load_golden(DEFAULT_GOLDEN)
    marias = [c for c in golden.entity_collisions if c.id == "two-marias"]
    verdicts = check_entity_collisions(repo, marias)
    assert verdicts and not verdicts[0].passed


def test_entity_collisions_fail_when_unresolved():
    repo = _CollisionRepo({})  # nothing resolves
    golden = load_golden(DEFAULT_GOLDEN)
    verdicts = check_entity_collisions(repo, golden.entity_collisions[:1])
    assert not verdicts[0].passed


# --------------------------------------------------------------------------- #
# As-of Correctness — freshness distinct from contradiction (research P1 #6)   #
# --------------------------------------------------------------------------- #
class _StubEngine:
    def __init__(self, bundle):
        self._bundle = bundle

    def ask(self, q):
        return self._bundle


def test_as_of_correctness_counts_only_freshness_questions():
    fresh_q = Question(
        id="q-fresh",
        q="latest revenue?",
        checks=["uses_freshest_as_of", "cites_source", "no_false_contradiction"],
    )
    contra_q = Question(
        id="q-contra",
        q="do they agree?",
        checks=["surfaces_contradiction", "uses_freshest_as_of"],
    )
    # one freshest as_of, single coherent date → uses_freshest_as_of passes
    bundle = AnswerBundle(
        answer="14.2M",
        citations=[Citation(source_uri="data/dashboards/april-2026-kpi-dashboard.html", as_of=date(2026, 3, 31))],
    )
    answers = check_answers(_StubEngine(bundle), [fresh_q, contra_q])
    passed, total = as_of_correctness([fresh_q, contra_q], answers)
    # only the freshness question (no surfaces_contradiction) is counted
    assert total == 1
    assert passed == 1
