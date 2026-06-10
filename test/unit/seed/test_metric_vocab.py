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


@pytest.mark.parametrize(
    "raw,expected",
    [
        # SP_010 final-mile: "who leads this repo/component" ranking predicates canonicalize
        # onto top_contributor (the golden code-core-top-contributor fact's predicate).
        ("top_contributor", "top_contributor"),
        ("top contributor", "top_contributor"),
        ("lead contributor", "top_contributor"),
        ("primary contributor", "top_contributor"),
        ("top committer", "top_contributor"),
        ("lead committer", "top_contributor"),
        ("leading contributor", "top_contributor"),
    ],
)
def test_final_mile_predicate_synonyms_canonicalize(raw, expected):
    assert canonical_key(raw) == expected


def test_top_contributor_is_a_distinct_key():
    keys = {k for k, _, _ in METRIC_VOCAB}
    assert "top_contributor" in keys


def test_migration_START_does_not_canonicalize_to_completion_target():
    # Guard: a START date is NOT a completion. "hubspot migration start date" (the cache's
    # May-1 start claim) must never land on completion_target, or it would false-pair with the
    # end-of-June completion. It is unknown → passes through unchanged.
    assert canonical_key("hubspot migration start date") != "completion_target"
    assert canonical_key("migration start") != "completion_target"


def test_no_alias_maps_to_two_distinct_keys():
    # A lowercased alias appearing under two canonical keys is a silent last-wins bug.
    seen: dict[str, str] = {}
    for key, _display, aliases in METRIC_VOCAB:
        for alias in (key, *aliases):
            a = alias.lower()
            assert a not in seen or seen[a] == key, (
                f"alias {a!r} maps to both {seen.get(a)!r} and {key!r}"
            )
            seen[a] = key


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
