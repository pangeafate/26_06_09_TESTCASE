"""The contradiction precision sweep (SP_028a) — cardinality skip + value-pair dedup.

Sweep-level tests (NOT detect() tests): they exercise scripts.recompute_contradictions.recompute
against a FakeRepo, so detect()/detect_link_conflicts() stay unmodified. No DB.
"""

from __future__ import annotations

from datetime import date

from helixpay.contracts import Claim, Contradiction, Link
from scripts.recompute_contradictions import recompute


class FakeRepo:
    def __init__(self, claims: list[Claim], links: list[Link] | None = None) -> None:
        self._claims = claims
        self._links = links or []
        self.contradictions: list[Contradiction] = []

    def get_contradictions(self, subject_id=None):
        return [c for c in self.contradictions if subject_id is None or c.subject_entity_id == subject_id]

    def clear_contradictions(self) -> int:
        n = len(self.contradictions)
        self.contradictions = []
        return n

    def distinct_claim_groups(self):
        out: list[tuple[int, str]] = []
        for c in self._claims:
            k = (c.subject_entity_id, c.predicate)
            if k not in out:
                out.append(k)
        return out

    def get_claims(self, subject_id, predicate=None):
        return [
            c for c in self._claims
            if c.subject_entity_id == subject_id and (predicate is None or c.predicate == predicate)
        ]

    def distinct_link_groups(self):
        out: list[tuple[int, str]] = []
        for ln in self._links:
            k = (ln.from_entity_id, ln.link_type)
            if k not in out:
                out.append(k)
        return out

    def get_links(self, link_type=None, from_entity_id=None, to_entity_id=None):
        return [
            ln for ln in self._links
            if (link_type is None or ln.link_type == link_type)
            and (from_entity_id is None or ln.from_entity_id == from_entity_id)
        ]

    def add_contradiction(self, c: Contradiction) -> None:
        # Mirror the real UNIQUE(claim_a_id,claim_b_id) / link-pair dedup.
        if c.claim_a_id is not None:
            pair = tuple(sorted((c.claim_a_id, c.claim_b_id)))
            if any(x.claim_a_id is not None and tuple(sorted((x.claim_a_id, x.claim_b_id))) == pair
                   for x in self.contradictions):
                return
        elif c.link_a_id is not None:
            pair = tuple(sorted((c.link_a_id, c.link_b_id)))
            if any(x.link_a_id is not None and tuple(sorted((x.link_a_id, x.link_b_id))) == pair
                   for x in self.contradictions):
                return
        self.contradictions.append(c)


def _c(cid: int, subj: int, pred: str, value: str, as_of: date) -> Claim:
    return Claim(id=cid, subject_entity_id=subj, predicate=pred, object_value=value,
                 as_of=as_of, document_id=cid)


def test_set_valued_group_is_skipped():
    # pain_point is set_valued — multiplicity is legitimate, so two values are NOT a conflict.
    claims = [
        _c(1, 10, "pain_point", "slow onboarding", date(2026, 3, 31)),
        _c(2, 10, "pain_point", "opaque reporting", date(2026, 3, 31)),
    ]
    repo = FakeRepo(claims)
    stats = recompute(repo)
    assert stats["skipped_set_valued"] == 1
    assert len(repo.contradictions) == 0


def test_value_pair_dedup_collapses_pairwise_inflation():
    # 3 "June" + 2 "Q3" ga_target claims → 6 conflicting June×Q3 pairs (ga_target bypasses the
    # window gate) → ONE deduped row, not six.
    claims = [_c(i, 20, "ga_target", "end of June 2026", date(2026, 4, 15)) for i in (1, 2, 3)]
    claims += [_c(i, 20, "ga_target", "end of Q3 2026", date(2026, 5, 12)) for i in (4, 5)]
    repo = FakeRepo(claims)
    recompute(repo)
    assert len(repo.contradictions) == 1
    # The surviving representative's note carries BOTH values (the unresolved-subject oracle path).
    note = (repo.contradictions[0].note or "").lower()
    assert "june" in note and "q3" in note


def test_distinct_value_pairs_both_survive():
    # June-vs-Q3 and June-vs-Q4 are DIFFERENT conflicts — dedup must keep each distinct pair.
    claims = [
        _c(1, 30, "ga_target", "end of June 2026", date(2026, 4, 15)),
        _c(2, 30, "ga_target", "end of Q3 2026", date(2026, 5, 12)),
        _c(3, 30, "ga_target", "end of Q4 2026", date(2026, 5, 20)),
    ]
    repo = FakeRepo(claims)
    recompute(repo)
    # three distinct value-pairs: June-Q3, June-Q4, Q3-Q4
    assert len(repo.contradictions) == 3


def _link(lid: int, frm: int, to: int, *, doc: int) -> Link:
    return Link(id=lid, from_entity_id=frm, to_entity_id=to, link_type="reports_to",
                as_of=None, valid_to=None, document_id=doc)


def test_link_dedup_collapses_same_target_pair():
    # entity 5 reports_to →1 (doc1), →1 (doc2), →2 (doc3): two conflicting pairs both carry the
    # same {to=1, to=2} target pair → collapse to ONE link contradiction.
    repo = FakeRepo([], [_link(1, 5, 1, doc=1), _link(2, 5, 1, doc=2), _link(3, 5, 2, doc=3)])
    recompute(repo)
    assert len(repo.contradictions) == 1
