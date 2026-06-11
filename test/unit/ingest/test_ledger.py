"""Loss ledger: per-source counters for extraction visibility (SP_014)."""

from __future__ import annotations

import json

import pytest

from helixpay.ingest.extract.ledger import DocLoss, LossLedger


# --------------------------------------------------------------------------- #
# DocLoss unit
# --------------------------------------------------------------------------- #

def test_docloss_defaults_to_zero():
    d = DocLoss()
    assert d.chunks == 0
    assert d.empty_extractions == 0
    assert d.truncated_calls == 0
    assert d.items_emitted == 0
    assert d.items_dropped == 0
    assert len(d.dropped_by_reason) == 0
    assert len(d.coerced_by_kind) == 0


# --------------------------------------------------------------------------- #
# LossLedger counters
# --------------------------------------------------------------------------- #

def _ledger_with_uri(uri: str = "s3://test/doc.md") -> LossLedger:
    return LossLedger()


def test_record_chunk_increments():
    ledger = LossLedger()
    ledger.record_chunk("u1")
    ledger.record_chunk("u1")
    ledger.record_chunk("u2")
    assert ledger.per_source["u1"].chunks == 2
    assert ledger.per_source["u2"].chunks == 1


def test_record_empty_increments():
    ledger = LossLedger()
    ledger.record_empty("u1")
    ledger.record_empty("u1")
    assert ledger.per_source["u1"].empty_extractions == 2


def test_record_truncated_increments():
    ledger = LossLedger()
    ledger.record_truncated("uri")
    assert ledger.per_source["uri"].truncated_calls == 1


def test_record_emitted_increments():
    ledger = LossLedger()
    ledger.record_emitted("uri", 3)
    ledger.record_emitted("uri", 2)
    assert ledger.per_source["uri"].items_emitted == 5


def test_record_emitted_default_n_is_1():
    ledger = LossLedger()
    ledger.record_emitted("uri")
    assert ledger.per_source["uri"].items_emitted == 1


def test_record_coerced_increments_by_kind():
    ledger = LossLedger()
    ledger.record_coerced("uri", "as_of")
    ledger.record_coerced("uri", "as_of")
    ledger.record_coerced("uri", "link_verb")
    assert ledger.per_source["uri"].coerced_by_kind["as_of"] == 2
    assert ledger.per_source["uri"].coerced_by_kind["link_verb"] == 1


def test_record_drop_increments_both():
    ledger = LossLedger()
    ledger.record_drop("uri", "unmappable_enum")
    ledger.record_drop("uri", "unmappable_enum")
    ledger.record_drop("uri", "validation_error")
    src = ledger.per_source["uri"]
    assert src.items_dropped == 3
    assert src.dropped_by_reason["unmappable_enum"] == 2
    assert src.dropped_by_reason["validation_error"] == 1


def test_multiple_uris_are_independent():
    ledger = LossLedger()
    ledger.record_chunk("a")
    ledger.record_chunk("b")
    ledger.record_drop("a", "hypothetical")
    assert "b" not in ledger.per_source or ledger.per_source["b"].items_dropped == 0


# --------------------------------------------------------------------------- #
# probe() — frozen shape contract
# --------------------------------------------------------------------------- #

def test_probe_emits_exactly_four_keys_per_source():
    ledger = LossLedger()
    ledger.record_chunk("doc1.md")
    ledger.record_empty("doc1.md")
    ledger.record_truncated("doc1.md")
    ledger.record_drop("doc1.md", "hypothetical")

    result = ledger.probe()
    assert "doc1.md" in result
    node = result["doc1.md"]
    # Contract (SP_024): the original three keys PLUS lossy_drops. items_dropped stays the
    # TOTAL (all reasons); lossy_drops is the gating subset (schema/grounding losses only).
    assert set(node.keys()) == {
        "empty_extractions", "truncated_calls", "items_dropped", "lossy_drops"
    }
    assert node["empty_extractions"] == 1
    assert node["truncated_calls"] == 1
    assert node["items_dropped"] == 1
    # a "hypothetical" drop is intentional non-assertion, NOT a lossy schema failure.
    assert node["lossy_drops"] == 0


def test_probe_lossy_drops_counts_only_genuine_losses():
    ledger = LossLedger()
    # intentional drops — correct non-assertion, must NOT count as lossy
    ledger.record_drop("d.md", "hypothetical")
    ledger.record_drop("d.md", "ungrounded")
    # genuine schema/representation losses — must count as lossy
    ledger.record_drop("d.md", "validation_error")
    ledger.record_drop("d.md", "unmappable_enum")
    ledger.record_drop("d.md", "unparseable_as_of")

    node = ledger.probe()["d.md"]
    assert node["items_dropped"] == 5  # total, all reasons
    assert node["lossy_drops"] == 3  # validation_error + unmappable_enum + unparseable_as_of


def test_probe_unknown_drop_reason_counts_as_lossy_failsafe():
    # SP_024 review: the gate is defined by EXCLUSION from INTENTIONAL_DROP_REASONS, not by
    # membership in a lossy allow-list — so a brand-new, unclassified reason can only RAISE
    # severity (counts as lossy → blocks PASS), never silently slip through as benign. This
    # pins the fail-safe direction against a future maintainer flipping it to an allow-list.
    ledger = LossLedger()
    ledger.record_drop("d.md", "some_future_unclassified_reason")
    node = ledger.probe()["d.md"]
    assert node["items_dropped"] == 1
    assert node["lossy_drops"] == 1  # unknown ⇒ lossy


def test_probe_includes_all_recorded_sources():
    ledger = LossLedger()
    ledger.record_chunk("a.md")
    ledger.record_chunk("b.md")
    result = ledger.probe()
    assert set(result.keys()) == {"a.md", "b.md"}


def test_probe_returns_empty_dict_when_nothing_recorded():
    ledger = LossLedger()
    assert ledger.probe() == {}


# --------------------------------------------------------------------------- #
# summary() — JSON-serialisable
# --------------------------------------------------------------------------- #

def test_summary_is_json_serialisable():
    ledger = LossLedger()
    ledger.record_chunk("u")
    ledger.record_emitted("u", 5)
    ledger.record_drop("u", "unmappable_enum")
    ledger.record_coerced("u", "as_of")
    summary = ledger.summary()
    # Must not raise
    serialised = json.dumps(summary)
    assert isinstance(serialised, str)


def test_summary_contains_totals_and_by_source():
    ledger = LossLedger()
    ledger.record_chunk("doc1.md")
    ledger.record_chunk("doc2.md")
    ledger.record_emitted("doc1.md", 4)
    ledger.record_drop("doc1.md", "validation_error")
    ledger.record_coerced("doc2.md", "link_verb")

    summary = ledger.summary()
    assert "totals" in summary
    assert "by_source" in summary
    assert "doc1.md" in summary["by_source"]
    assert "doc2.md" in summary["by_source"]


def test_summary_totals_aggregate_across_sources():
    ledger = LossLedger()
    ledger.record_emitted("a.md", 3)
    ledger.record_emitted("b.md", 7)
    ledger.record_drop("a.md", "hypothetical")
    ledger.record_drop("b.md", "hypothetical")

    summary = ledger.summary()
    totals = summary["totals"]
    assert totals["items_emitted"] == 10
    assert totals["items_dropped"] == 2


def test_summary_counters_are_plain_dicts_not_counter_objects():
    """Counter objects are not JSON-serialisable; summary must convert them."""
    ledger = LossLedger()
    ledger.record_drop("u.md", "unmappable_enum")
    ledger.record_coerced("u.md", "as_of")

    summary = ledger.summary()
    source_dict = summary["by_source"]["u.md"]
    # Must be plain dict, not a Counter
    assert isinstance(source_dict["dropped_by_reason"], dict)
    assert isinstance(source_dict["coerced_by_kind"], dict)
    assert not hasattr(source_dict["dropped_by_reason"], "most_common")
