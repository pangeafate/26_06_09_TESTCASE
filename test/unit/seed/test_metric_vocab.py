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


def test_unknown_predicate_passthrough_never_raises():
    # review M-1: unknown predicates must pass through unchanged, not raise.
    assert canonical_key("completely_unknown_metric_xyz") == "completely_unknown_metric_xyz"
    assert canonical_key("") == ""


def test_revenue_and_arr_are_distinct_keys():
    keys = {k for k, _, _ in METRIC_VOCAB}
    assert "revenue" in keys and "arr" in keys and "churn" in keys
