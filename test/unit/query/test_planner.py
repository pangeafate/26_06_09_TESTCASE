"""Planner route classification across the §8 question shapes."""

from __future__ import annotations

from helixpay.query.planner import Route, route


def test_hierarchy_with_freshness_routes_both_and_flags_freshness():
    p = route("Who does the Head of Engineering report to, as of the latest org chart?")
    assert p.wants_hierarchy is True
    assert p.wants_freshness is True
    assert p.route == Route.both


def test_pure_hierarchy_routes_structured():
    p = route("Who does the Head of Engineering report to?")
    assert p.wants_hierarchy is True
    assert p.wants_freshness is False
    assert p.route == Route.structured


def test_metric_question_probes_contradictions_and_routes_both():
    p = route("What was HelixPay's ARR in Q1 2026?")
    assert p.wants_contradictions is True
    assert p.route == Route.both


def test_metric_negative_phrasing_still_probes_contradictions():
    # No "disagree"/"conflict" word — but a metric question must still probe (C1/L2).
    p = route("What was Q1 revenue?")
    assert p.wants_contradictions is True
    assert p.route == Route.both


def test_explicit_disagreement_question_probes_contradictions():
    p = route("Do the dashboards and the board deck disagree on any key metrics?")
    assert p.wants_contradictions is True
    assert p.route == Route.both


def test_cross_document_synthesis_routes_both():
    p = route("Summarize the CEO's priorities.")
    assert p.route == Route.both


def test_customer_ownership_routes_both():
    p = route("List the customers mentioned and who owns each relationship.")
    assert p.route == Route.both
