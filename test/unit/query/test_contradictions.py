"""Contradiction surfacing — topic/subject filtering; both sides carried."""

from __future__ import annotations

from datetime import date

from helixpay.contracts import Claim, Contradiction, Entity, Link
from helixpay.query.contradictions import find, label_for, relevant


def _seed_revenue_conflict(repo):
    rid = repo.add_entity(Entity(canonical_name="Revenue", entity_type="metric"))
    repo.vocab = {"revenue": "revenue", "annual recurring revenue": "arr", "arr": "arr"}
    repo.contradictions = [
        Contradiction(
            id=1,
            subject_entity_id=rid,
            predicate="revenue",
            claim_a_id=10,
            claim_b_id=11,
            kind="value_conflict",
        ),
    ]
    return rid


def test_find_none_returns_all(repo):
    _seed_revenue_conflict(repo)
    got = find(repo, None)
    assert len(got) == 1


def test_find_by_topic_resolves_subject_and_predicate(repo):
    _seed_revenue_conflict(repo)
    got = find(repo, "revenue")
    assert len(got) == 1
    c = got[0]
    assert c.claim_a_id == 10 and c.claim_b_id == 11  # both sides carried


def test_find_filters_on_canonicalized_predicate(repo):
    # contradiction is on "arr"; topic "annual recurring revenue" canonicalizes to "arr".
    repo.add_entity(Entity(canonical_name="Revenue", entity_type="metric"))
    repo.vocab = {"annual recurring revenue": "arr"}
    repo.contradictions = [
        Contradiction(
            id=2,
            subject_entity_id=999,
            predicate="arr",
            claim_a_id=1,
            claim_b_id=2,
            kind="value_conflict",
        ),
    ]
    got = find(repo, "annual recurring revenue")
    assert [c.id for c in got] == [2]  # matched via canonical key, not raw string


def test_find_does_not_match_when_canonical_differs(repo):
    # topic canonicalizes to "arr" but the only conflict is on "revenue" → no match.
    repo.vocab = {"arr": "arr"}
    repo.contradictions = [
        Contradiction(
            id=3, subject_entity_id=999, predicate="revenue", claim_a_id=1, claim_b_id=2
        ),
    ]
    assert find(repo, "arr") == []


def test_relevant_by_subject_ids(repo):
    rid = _seed_revenue_conflict(repo)
    got = relevant(repo, subject_ids=[rid])
    assert [c.id for c in got] == [1]


def test_relevant_by_topic_when_entity_unresolved(repo):
    # No subject resolved (subject_ids empty) — the topic predicate path must
    # still surface the conflict (review code-C2).
    _seed_revenue_conflict(repo)
    got = relevant(repo, subject_ids=[], topics=["revenue", "q1", "2026"])
    assert [c.id for c in got] == [1]


# -- SP_012: typed contradictions ---------------------------------------- #
def _claim(cid, as_of):
    return Claim(
        id=cid, subject_entity_id=1, predicate="revenue", object_value="x", as_of=as_of
    )


def test_label_for_trusts_stored_kind():
    # When kind is set it is trusted (mapped to a human label), never re-derived.
    assert label_for(Contradiction(kind="value_conflict"), {}) == "value"
    assert label_for(Contradiction(kind="temporal"), {}) == "temporal"
    assert (
        label_for(Contradiction(kind="source_disagreement"), {})
        == "source disagreement"
    )


def test_label_for_infers_temporal_only_when_kind_missing():
    # kind None + both sides dated and different → temporal.
    by_id = {10: _claim(10, date(2026, 1, 1)), 11: _claim(11, date(2026, 3, 1))}
    c = Contradiction(claim_a_id=10, claim_b_id=11)  # kind None
    assert label_for(c, by_id) == "temporal"


def test_label_for_defaults_to_value_when_dates_equal_or_missing():
    by_id = {10: _claim(10, date(2026, 1, 1)), 11: _claim(11, date(2026, 1, 1))}
    c = Contradiction(claim_a_id=10, claim_b_id=11)
    assert label_for(c, by_id) == "value"


def test_label_for_link_conflict_is_relationship():
    c = Contradiction(link_a_id=5, link_b_id=6)  # link-pair conflict, no claim ids
    assert label_for(c, {}) == "relationship"


def test_label_for_passes_through_unknown_stored_kind():
    # A stored kind without a friendly label is trusted and surfaced verbatim, never
    # silently re-derived to a different type.
    assert (
        label_for(
            Contradiction(kind="data_model_conflict", claim_a_id=1, claim_b_id=2), {}
        )
        == "data_model_conflict"
    )


def test_relevant_surfaces_link_contradiction(repo):
    # A relationship conflict (link-pair) on a subject must surface alongside value ones.
    sid = repo.add_entity(Entity(canonical_name="Bob", entity_type="person"))
    repo.contradictions = [
        Contradiction(
            id=7,
            subject_entity_id=sid,
            link_a_id=5,
            link_b_id=6,
            kind="source_disagreement",
            note="two managers asserted",
        ),
    ]
    got = relevant(repo, subject_ids=[sid])
    assert [c.id for c in got] == [7]
    assert got[0].link_a_id == 5 and got[0].link_b_id == 6
