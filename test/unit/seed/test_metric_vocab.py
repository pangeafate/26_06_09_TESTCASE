"""Metric-vocabulary canonicalization (pure)."""

from __future__ import annotations

import pytest

from helixpay.seed.metric_vocab import METRIC_VOCAB, canonical_key


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("ARR", "arr"),
        ("annual recurring revenue", "arr"),
        ("Annual Recurring Revenue", "arr"),
        ("revenue", "revenue"),
        ("Q1 revenue", "revenue"),
        ("NPS", "nps"),
        ("net promoter score", "nps"),
        ("burn", "monthly_burn"),
        ("ARR churn", "churn"),
        ("headcount", "headcount"),
    ],
)
def test_known_aliases_canonicalize(raw, expected):
    assert canonical_key(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        # SP_010: GA / launch synonyms must land on ga_target so the planted Confluence
        # contradiction pairs up.
        ("ga_target", "ga_target"),
        ("GA", "ga_target"),
        ("general availability", "ga_target"),
        ("launch", "ga_target"),
        ("go-live", "ga_target"),
        ("release date", "ga_target"),
        # migration/cutover synonyms → completion_target
        ("completion_target", "completion_target"),
        ("cutover", "completion_target"),
        ("migration completion", "completion_target"),
    ],
)
def test_target_predicate_synonyms_canonicalize(raw, expected):
    assert canonical_key(raw) == expected


def test_ga_target_and_completion_target_are_distinct_keys():
    keys = {k for k, _, _ in METRIC_VOCAB}
    assert "ga_target" in keys and "completion_target" in keys


def test_unknown_predicate_passthrough_never_raises():
    # review M-1: unknown predicates must pass through unchanged, not raise.
    assert (
        canonical_key("completely_unknown_metric_xyz")
        == "completely_unknown_metric_xyz"
    )
    assert canonical_key("") == ""


def test_revenue_and_arr_are_distinct_keys():
    keys = {k for k, _, _ in METRIC_VOCAB}
    assert "revenue" in keys and "arr" in keys and "churn" in keys
