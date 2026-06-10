"""Temporal resolver: freshest-wins, None-safe ordering, as_of_coverage."""

from __future__ import annotations

from datetime import date

from helixpay.contracts import Citation, Claim
from helixpay.query.temporal import (
    ROSTER_AS_OF,
    as_of_coverage,
    freshest_per_predicate,
    order_by_freshness,
)


def _claim(cid: int, pred: str, val: str, as_of):
    return Claim(id=cid, subject_entity_id=1, predicate=pred, object_value=val, as_of=as_of)


def test_order_by_freshness_none_is_oldest():
    claims = [
        _claim(1, "revenue", "a", date(2026, 3, 31)),
        _claim(2, "revenue", "b", None),
        _claim(3, "revenue", "c", date(2026, 4, 22)),
    ]
    ordered = [c.id for c in order_by_freshness(claims)]
    assert ordered == [3, 1, 2]  # 04-22, 03-31, then the undated one last


def test_freshest_per_predicate_picks_latest():
    claims = [
        _claim(1, "revenue", "SGD 13.9M", date(2026, 3, 31)),
        _claim(2, "revenue", "SGD 14.2M", date(2026, 4, 22)),
        _claim(3, "headcount", "120", date(2026, 4, 1)),
    ]
    freshest = freshest_per_predicate(claims)
    assert freshest["revenue"].id == 2
    assert freshest["headcount"].id == 3


def test_as_of_coverage_flags_staleness_against_roster():
    cits = [
        Citation(source_uri="data/dashboards/x.html", as_of=date(2026, 3, 31)),
        Citation(source_uri="data/board-deck.pdf", as_of=date(2026, 3, 31)),
    ]
    cov = as_of_coverage(cits)
    assert cov["earliest"] == "2026-03-31"
    assert cov["latest"] == "2026-03-31"
    assert cov["stale"] is True  # not newer than the 2026-04-15 roster snapshot
    assert cov["sources"]["data/board-deck.pdf"] == "2026-03-31"


def test_as_of_coverage_fresh_when_newer_than_roster():
    cits = [Citation(source_uri="data/board-update.md", as_of=date(2026, 4, 22))]
    cov = as_of_coverage(cits)
    assert cov["latest"] == "2026-04-22"
    assert cov["stale"] is False
    assert ROSTER_AS_OF == date(2026, 4, 15)


def test_as_of_coverage_on_roster_date_is_not_stale():
    # Evidence dated exactly on the roster snapshot is current, not stale.
    cits = [Citation(source_uri="data/org-chart.md", as_of=date(2026, 4, 15))]
    cov = as_of_coverage(cits)
    assert cov["latest"] == "2026-04-15"
    assert cov["stale"] is False


def test_as_of_coverage_empty():
    cov = as_of_coverage([])
    assert cov == {"earliest": None, "latest": None, "sources": {}, "stale": False}
