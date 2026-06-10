"""Consensus / dissent rollup (SP_012 gap 5) — pure, no-LLM grouping.

The rollup collapses N coexisting claims for one predicate into a single ranked
consensus value (with corroborating count + freshest as_of) plus explicit dissent.
It must never collapse genuine disagreement (CLAUDE.md "never collapse conflicting
facts") and must not merge two distinct predicates that share a value.
"""

from __future__ import annotations

from datetime import date

from helixpay.contracts import Claim
from helixpay.query.consensus import ConsensusGroup, rollup


def _c(cid, pred, val, as_of=None):
    return Claim(
        id=cid, subject_entity_id=1, predicate=pred, object_value=val, as_of=as_of
    )


def _identity(p):
    return p


def test_rollup_collapses_seven_runway_claims_to_consensus_plus_dissent():
    # 6 sources agree on 18 months (in spelling variants normalize_value folds), 1 dissents.
    claims = [
        _c(1, "runway", "18 months", date(2026, 1, 1)),
        _c(2, "runway", "eighteen months", date(2026, 2, 1)),
        _c(3, "runway", "~18 months", date(2026, 3, 1)),
        _c(4, "runway", "18 months", date(2026, 3, 31)),
        _c(5, "runway", "18 months", date(2026, 2, 15)),
        _c(6, "runway", "18 months", date(2026, 1, 20)),
        _c(7, "runway", "24 months", date(2026, 3, 15)),
    ]
    groups = rollup(claims, _identity)
    assert len(groups) == 1
    g = groups[0]
    assert isinstance(g, ConsensusGroup)
    assert g.predicate == "runway"
    assert g.corroborating_count == 6  # the six "18 months" variants
    assert g.freshest_as_of == date(2026, 3, 31)  # freshest among the consensus
    assert set(g.member_ids) == {1, 2, 3, 4, 5, 6}
    # the dissenting value is preserved, not collapsed
    assert len(g.dissent) == 1
    assert g.dissent[0].claim_ids == [7]
    assert g.dissent[0].count == 1


def test_rollup_does_not_merge_distinct_predicates_sharing_a_value():
    # Same numeric value (100) on two different canonical predicates must NOT co-group.
    claims = [
        _c(1, "arr", "100", date(2026, 1, 1)),
        _c(2, "arr", "100", date(2026, 2, 1)),
        _c(3, "revenue", "100", date(2026, 1, 1)),
        _c(4, "revenue", "100", date(2026, 2, 1)),
    ]
    groups = rollup(claims, _identity)
    assert {g.predicate for g in groups} == {"arr", "revenue"}
    for g in groups:
        assert g.corroborating_count == 2
        assert g.dissent == []


def test_rollup_groups_on_canonical_predicate():
    # "ARR" and "annual recurring revenue" canonicalize to the same key → one group.
    canon = {"arr": "arr", "annual recurring revenue": "arr"}.get
    claims = [
        _c(1, "arr", "SGD 10M", date(2026, 1, 1)),
        _c(2, "annual recurring revenue", "SGD 10M", date(2026, 2, 1)),
    ]
    groups = rollup(claims, lambda p: canon(p, p))
    assert len(groups) == 1
    assert groups[0].predicate == "arr"
    assert groups[0].corroborating_count == 2


def test_rollup_skips_singletons():
    # A predicate with a single claim has nothing to consolidate.
    groups = rollup([_c(1, "headcount", "42", date(2026, 1, 1))], _identity)
    assert groups == []


def test_rollup_freshest_is_none_when_all_undated():
    claims = [_c(1, "runway", "18 months"), _c(2, "runway", "18 months")]
    groups = rollup(claims, _identity)
    assert len(groups) == 1
    assert groups[0].freshest_as_of is None
    assert groups[0].corroborating_count == 2


def test_rollup_consensus_is_the_larger_bucket():
    # 1 vs 3 — the majority value is consensus, the minority is dissent (numeric tie-break
    # never makes the minority win).
    claims = [
        _c(1, "burn", "SGD 1M", date(2026, 3, 31)),  # newest but minority
        _c(2, "burn", "SGD 2M", date(2026, 1, 1)),
        _c(3, "burn", "SGD 2M", date(2026, 1, 2)),
        _c(4, "burn", "SGD 2M", date(2026, 1, 3)),
    ]
    groups = rollup(claims, _identity)
    g = groups[0]
    assert g.corroborating_count == 3
    assert set(g.member_ids) == {2, 3, 4}
    assert g.dissent[0].claim_ids == [1]
