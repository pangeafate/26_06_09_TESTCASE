"""Harness-logic tests — the grader itself, with no DB.

A ``FakeRepo`` returns canned claims/links and a ``StubEngine`` returns canned
AnswerBundles, so we can assert the harness grades correctly: FOUND/MISMATCH/MISSING
verdicts, recall/precision arithmetic, per-check evaluation, and the /goal exit logic.
These drive only the frozen contract types — never a build slice.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import pytest

from helixpay.contracts import (
    AnswerBundle,
    Citation,
    Claim,
    Contradiction,
    Entity,
    Link,
)
from eval.models import GoldenFact, GoldenSet, Question, Verdict
from eval.run import (
    check_answers,
    check_extraction,
    evaluate_check,
    goal_verdict,
    normalize_value,
)


# --------------------------------------------------------------------------- #
# Fakes (implement only the Repository surface the harness touches)           #
# --------------------------------------------------------------------------- #
class FakeRepo:
    def __init__(self):
        self._entities: dict[str, Entity] = {}
        self._claims: dict[int, list[Claim]] = {}
        self._links: list[Link] = []
        self._sources: dict[int, list[Citation]] = {}
        self._next = 1

    def add_entity(self, name: str) -> int:
        eid = self._next
        self._next += 1
        self._entities[name.lower()] = Entity(id=eid, canonical_name=name, entity_type="other")
        return eid

    def add_claim(self, subject_id: int, c: Claim, citation: Optional[Citation] = None):
        c.id = self._next
        self._next += 1
        self._claims.setdefault(subject_id, []).append(c)
        if citation:
            self._sources[c.id] = [citation]

    def add_link(self, link: Link):
        self._links.append(link)

    # -- Repository surface -------------------------------------------------- #
    def resolve_entity(self, name, entity_type=None, context=None):
        return self._entities.get(name.lower())

    def canonical_predicate(self, raw: str) -> str:
        return {"annual recurring revenue": "arr", "arr": "arr"}.get(raw.lower(), raw)

    def get_claims(self, subject_id: int, predicate=None):
        claims = self._claims.get(subject_id, [])
        if predicate is None:
            return list(claims)
        return [c for c in claims if c.predicate == predicate]

    def get_links(self, link_type=None):
        if link_type is None:
            return list(self._links)
        return [l for l in self._links if l.link_type == link_type]

    def get_sources(self, claim_ids):
        out: list[Citation] = []
        for cid in claim_ids:
            out.extend(self._sources.get(cid, []))
        return out


class StubEngine:
    def __init__(self, bundle: AnswerBundle):
        self._bundle = bundle

    def ask(self, question: str) -> AnswerBundle:
        return self._bundle


# --------------------------------------------------------------------------- #
# normalize_value                                                             #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "a,b",
    [
        ("SGD 14.2M", "14.2M"),
        ("SGD 14.2M", "$14.2 million"),
        ("R$22.0M", "22.0m"),
        ("412", "412"),
    ],
)
def test_normalize_value_matches_equivalent_forms(a, b):
    na, nb = normalize_value(a), normalize_value(b)
    assert na in nb or nb in na


# --------------------------------------------------------------------------- #
# extraction verdicts                                                         #
# --------------------------------------------------------------------------- #
def _claim_fact(**kw):
    base = dict(id="t", format="pdf", kind="claim", subject="HelixPay",
                predicate="revenue", value="SGD 14.2M", as_of=date(2026, 3, 31),
                source_uri="data/q1-2026-results.pdf")
    base.update(kw)
    return GoldenFact.model_validate(base)


def test_extraction_found():
    repo = FakeRepo()
    sid = repo.add_entity("HelixPay")
    repo.add_claim(
        sid,
        Claim(subject_entity_id=sid, predicate="revenue", object_value="SGD 14.2M", as_of=date(2026, 3, 31)),
        Citation(source_uri="data/q1-2026-results.pdf", as_of=date(2026, 3, 31)),
    )
    report = check_extraction(repo, GoldenSet(facts=[_claim_fact()], contradictions=[]))
    assert report.verdicts[0].verdict is Verdict.found
    assert report.recall == 1.0 and report.precision == 1.0


def test_extraction_mismatch_on_wrong_value():
    repo = FakeRepo()
    sid = repo.add_entity("HelixPay")
    repo.add_claim(
        sid,
        Claim(subject_entity_id=sid, predicate="revenue", object_value="SGD 13.9M", as_of=date(2026, 3, 31)),
        Citation(source_uri="data/q1-2026-results.pdf", as_of=date(2026, 3, 31)),
    )
    report = check_extraction(repo, GoldenSet(facts=[_claim_fact()], contradictions=[]))
    assert report.verdicts[0].verdict is Verdict.mismatch
    assert report.recall == 0.0 and report.precision == 0.0


def test_extraction_missing_when_subject_unresolved():
    repo = FakeRepo()  # no entity added
    report = check_extraction(repo, GoldenSet(facts=[_claim_fact()], contradictions=[]))
    assert report.verdicts[0].verdict is Verdict.missing


def test_extraction_mismatch_on_wrong_as_of():
    repo = FakeRepo()
    sid = repo.add_entity("HelixPay")
    repo.add_claim(
        sid,
        Claim(subject_entity_id=sid, predicate="revenue", object_value="SGD 14.2M", as_of=date(2025, 12, 31)),
        Citation(source_uri="data/q1-2026-results.pdf", as_of=date(2025, 12, 31)),
    )
    report = check_extraction(repo, GoldenSet(facts=[_claim_fact()], contradictions=[]))
    assert report.verdicts[0].verdict is Verdict.mismatch


def _reports_to_fact() -> GoldenFact:
    """Daniel Tan reports_to Arjun Kapoor — a directional link golden fact."""
    return GoldenFact.model_validate(
        {"id": "l", "format": "md", "kind": "link", "link_type": "reports_to",
         "from": "Daniel Tan", "to": "Arjun Kapoor", "subject": "Daniel Tan",
         "predicate": "reports_to", "value": "Arjun Kapoor", "as_of": "2026-04-15",
         "source_uri": "data/org-chart.md"}
    )


def test_link_fact_found_when_direction_matches():
    repo = FakeRepo()
    a = repo.add_entity("Daniel Tan")
    b = repo.add_entity("Arjun Kapoor")
    repo.add_link(Link(from_entity_id=a, to_entity_id=b, link_type="reports_to"))
    report = check_extraction(repo, GoldenSet(facts=[_reports_to_fact()], contradictions=[]))
    assert report.verdicts[0].verdict is Verdict.found


def test_link_fact_reversed_direction_is_mismatch():
    repo = FakeRepo()
    a = repo.add_entity("Daniel Tan")
    b = repo.add_entity("Arjun Kapoor")
    repo.add_link(Link(from_entity_id=b, to_entity_id=a, link_type="reports_to"))  # reversed
    report = check_extraction(repo, GoldenSet(facts=[_reports_to_fact()], contradictions=[]))
    assert report.verdicts[0].verdict is Verdict.mismatch


def test_recall_excludes_non_bar_facts():
    repo = FakeRepo()
    bar = _claim_fact(id="bar")
    info = _claim_fact(id="info", recall_bar=False, format="image",
                       source_uri="data/images/revenue-trend-q1-2026.jpeg")
    report = check_extraction(repo, GoldenSet(facts=[bar, info], contradictions=[]))
    assert report.total == 1  # only the bar fact is graded


# --------------------------------------------------------------------------- #
# answer checks                                                               #
# --------------------------------------------------------------------------- #
def test_citation_checks_fail_on_uncited_answer():
    empty = AnswerBundle(answer="x")
    assert evaluate_check("cites_source", empty) is False
    assert evaluate_check("states_as_of", empty) is False


def test_citation_checks_pass_on_cited_answer():
    cited = AnswerBundle(
        answer="x",
        citations=[Citation(source_uri="data/org-chart.md", as_of=date(2026, 4, 15))],
    )
    assert evaluate_check("cites_source", cited) is True
    assert evaluate_check("states_as_of", cited) is True
    assert evaluate_check("resolves_hierarchy", cited) is True


def test_contradiction_bundle_surfaces_and_attributes_each_side():
    with_c = AnswerBundle(
        answer="x",
        citations=[
            Citation(source_uri="data/all-hands-2026-04-15.md", as_of=date(2026, 4, 15)),
            Citation(source_uri="data/board-deck-q1-2026.pdf", as_of=date(2026, 5, 12)),
        ],
        contradictions=[Contradiction(predicate="ga_target", kind="temporal")],
    )
    assert evaluate_check("surfaces_contradiction", with_c) is True
    assert evaluate_check("attributes_each_side", with_c) is True
    assert evaluate_check("cites_multiple_sources", with_c) is True
    assert evaluate_check("no_false_contradiction", with_c) is False


def test_agreeable_answer_has_no_false_contradiction():
    without = AnswerBundle(answer="agree", citations=[Citation(source_uri="a")])
    assert evaluate_check("no_false_contradiction", without) is True
    assert evaluate_check("surfaces_contradiction", without) is False


def test_unknown_check_raises():
    with pytest.raises(ValueError):
        evaluate_check("nonsense", AnswerBundle(answer="x"))


def test_check_answers_records_latency_and_failure():
    good = StubEngine(
        AnswerBundle(answer="x", citations=[Citation(source_uri="data/org-chart.md", as_of=date(2026, 4, 15))])
    )
    q = Question(id="q1", q="?", checks=["cites_source", "states_as_of"])
    res = check_answers(good, [q])
    assert res[0].gating_passed is True
    assert res[0].latency_s >= 0.0

    class Boom:
        def ask(self, question):
            raise RuntimeError("no engine")

    res2 = check_answers(Boom(), [q])
    assert res2[0].error is not None
    assert res2[0].gating_passed is False


# --------------------------------------------------------------------------- #
# /goal verdict                                                               #
# --------------------------------------------------------------------------- #
def _both_found_extr():
    from eval.models import ExtractionReport, FactVerdict
    return ExtractionReport(verdicts=[FactVerdict("a", Verdict.found), FactVerdict("b", Verdict.found)])


def _passing_answer():
    from eval.models import AnswerResult, CheckResult
    return AnswerResult(
        "q",
        checks=[CheckResult("cites_source", True, True),
                CheckResult("surfaces_contradiction", True, True)],
        surfaced_contradiction=True,
    )


def test_goal_verdict_green_when_recall_and_contradiction_pass():
    v = goal_verdict(_both_found_extr(), [_passing_answer()], recall_bar=0.8)
    assert v.passed is True


def test_goal_verdict_red_when_recall_below_bar():
    from eval.models import ExtractionReport, FactVerdict
    extr_low = ExtractionReport(verdicts=[FactVerdict("a", Verdict.found), FactVerdict("b", Verdict.missing)])
    assert goal_verdict(extr_low, [_passing_answer()], recall_bar=0.8).passed is False


def test_goal_verdict_contradiction_ok_false_when_none_surfaced():
    from eval.models import AnswerResult, CheckResult
    no_c = AnswerResult("q", checks=[CheckResult("cites_source", True, True)], surfaced_contradiction=False)
    assert goal_verdict(_both_found_extr(), [no_c], recall_bar=0.8).contradiction_ok is False
