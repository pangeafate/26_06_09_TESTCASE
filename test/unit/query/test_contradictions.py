"""Contradiction surfacing — topic/subject filtering; both sides carried."""

from __future__ import annotations

from helixpay.contracts import Contradiction, Entity
from helixpay.query.contradictions import find, relevant


def _seed_revenue_conflict(repo):
    rid = repo.add_entity(Entity(canonical_name="Revenue", entity_type="metric"))
    repo.vocab = {"revenue": "revenue", "annual recurring revenue": "arr", "arr": "arr"}
    repo.contradictions = [
        Contradiction(id=1, subject_entity_id=rid, predicate="revenue",
                      claim_a_id=10, claim_b_id=11, kind="value_conflict"),
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
        Contradiction(id=2, subject_entity_id=999, predicate="arr",
                      claim_a_id=1, claim_b_id=2, kind="value_conflict"),
    ]
    got = find(repo, "annual recurring revenue")
    assert [c.id for c in got] == [2]   # matched via canonical key, not raw string


def test_find_does_not_match_when_canonical_differs(repo):
    # topic canonicalizes to "arr" but the only conflict is on "revenue" → no match.
    repo.vocab = {"arr": "arr"}
    repo.contradictions = [
        Contradiction(id=3, subject_entity_id=999, predicate="revenue",
                      claim_a_id=1, claim_b_id=2),
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
