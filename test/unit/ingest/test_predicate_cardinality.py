"""Predicate-cardinality policy (SP_028a) — the contradiction pre-filter's data table."""

from __future__ import annotations

from helixpay.ingest.predicate_cardinality import cardinality, should_skip_predicate


def test_set_valued_predicate_is_skipped():
    assert cardinality("pain_point") == "set_valued"
    assert should_skip_predicate("pain_point") is True
    assert should_skip_predicate("weekly_activity") is True


def test_functional_predicate_is_kept():
    assert cardinality("ga_target") == "functional"
    assert should_skip_predicate("ga_target") is False
    assert should_skip_predicate("revenue") is False


def test_breakdown_is_classified_but_never_skipped():
    # gross_revenue is ALSO a real company metric — dropping by predicate would lose the
    # genuine conflict, so breakdown is classified but kept (entity-aware handling deferred).
    assert cardinality("gross_revenue") == "breakdown"
    assert should_skip_predicate("gross_revenue") is False
    assert should_skip_predicate("net_revenue") is False


def test_unknown_predicate_is_kept_safe_default():
    assert cardinality("totally_unknown_pred") == "unknown"
    assert should_skip_predicate("totally_unknown_pred") is False


def test_link_type_is_unknown_and_never_skipped():
    # A link type (handled by the link loop's own gate) must NEVER be classified set_valued,
    # or the sweep would wrongly skip link contradiction detection.
    assert cardinality("reports_to") == "unknown"
    assert should_skip_predicate("reports_to") is False
    assert should_skip_predicate("dotted_line_to") is False
