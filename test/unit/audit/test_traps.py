"""Planted-trap checks over synthetic TrapContexts — pure, no DB."""

from __future__ import annotations

from helixpay.audit.traps import (
    build_trap_context,
    canonicalize,
    run_traps,
    trap_confluence_ga,
    trap_no_false_revenue_contradiction,
    trap_two_marias_distinct,
)

_VOCAB = [
    {"canonical_key": "ga_target", "aliases": ["ga date", "launch date", "go live"]},
    {"canonical_key": "revenue", "aliases": ["q1 revenue", "total revenue"]},
]


def _ctx(claim_rows, contradiction_rows=(), entity_rows=()):
    return build_trap_context(
        claim_rows=list(claim_rows),
        contradiction_rows=list(contradiction_rows),
        entity_rows=list(entity_rows),
        vocab_rows=_VOCAB,
    )


def test_canonicalize_maps_aliases_and_passes_unknown_through():
    vocab = {"ga date": "ga_target", "ga_target": "ga_target"}
    assert canonicalize("GA date", vocab) == "ga_target"
    assert canonicalize("ga_target", vocab) == "ga_target"
    assert canonicalize("unknown_metric", vocab) == "unknown_metric"


def test_confluence_ga_passes_when_differing_claims_are_paired():
    claims = [
        {
            "id": 1,
            "subject_name": "Project Confluence",
            "predicate": "launch date",
            "object_value": "end of June 2026",
            "superseded_by": None,
        },
        {
            "id": 2,
            "subject_name": "Project Confluence",
            "predicate": "ga date",
            "object_value": "end of Q3 2026",
            "superseded_by": None,
        },
    ]
    contras = [
        {
            "claim_a_id": 1,
            "claim_b_id": 2,
            "predicate": "ga_target",
            "link_a_id": None,
            "link_b_id": None,
        }
    ]
    res = trap_confluence_ga(_ctx(claims, contras))
    assert res.passed


def test_confluence_ga_fails_on_vocab_gap():
    # both claims use a predicate NOT in the vocab → they never share the ga_target key
    claims = [
        {
            "id": 1,
            "subject_name": "Project Confluence",
            "predicate": "ga_target_raw",
            "object_value": "end of June 2026",
            "superseded_by": None,
        },
        {
            "id": 2,
            "subject_name": "Project Confluence",
            "predicate": "ship_when",
            "object_value": "end of Q3 2026",
            "superseded_by": None,
        },
    ]
    res = trap_confluence_ga(_ctx(claims))
    assert not res.passed and "VOCAB" in res.detail


def test_confluence_ga_fails_when_claims_differ_but_unpaired():
    claims = [
        {
            "id": 1,
            "subject_name": "Project Confluence",
            "predicate": "ga date",
            "object_value": "end of June 2026",
            "superseded_by": None,
        },
        {
            "id": 2,
            "subject_name": "Project Confluence",
            "predicate": "go live",
            "object_value": "end of Q3 2026",
            "superseded_by": None,
        },
    ]
    res = trap_confluence_ga(_ctx(claims))  # no contradiction rows
    assert not res.passed and "DETECTION" in res.detail


def test_no_false_revenue_contradiction_passes_when_absent():
    claims = [
        {
            "id": 1,
            "subject_name": "HelixPay",
            "predicate": "q1 revenue",
            "object_value": "SGD 14.2M",
            "superseded_by": None,
        },
        {
            "id": 2,
            "subject_name": "HelixPay",
            "predicate": "total revenue",
            "object_value": "14.2 million",
            "superseded_by": None,
        },
    ]
    res = trap_no_false_revenue_contradiction(_ctx(claims))
    assert res.passed


def test_no_false_revenue_contradiction_fails_when_present():
    claims = [
        {
            "id": 1,
            "subject_name": "HelixPay",
            "predicate": "revenue",
            "object_value": "SGD 14.2M",
            "superseded_by": None,
        }
    ]
    contras = [{"predicate": "revenue", "claim_a_id": 1, "claim_b_id": 9}]
    res = trap_no_false_revenue_contradiction(_ctx(claims, contras))
    assert not res.passed


def test_two_marias_distinct_passes_when_both_present():
    entities = [
        {"id": 1, "canonical_name": "Maria Santos", "entity_type": "person"},
        {"id": 2, "canonical_name": "Maria Silva", "entity_type": "person"},
    ]
    assert trap_two_marias_distinct(_ctx([], entity_rows=entities)).passed


def test_two_marias_distinct_fails_when_collapsed_to_one():
    one = [{"id": 1, "canonical_name": "Maria Santos", "entity_type": "person"}]
    assert not trap_two_marias_distinct(_ctx([], entity_rows=one)).passed


def test_run_traps_returns_all_three():
    res = run_traps(_ctx([]))
    assert {r.name for r in res} == {
        "confluence_ga_surfaces",
        "no_false_revenue_contradiction",
        "two_marias_distinct",
    }
