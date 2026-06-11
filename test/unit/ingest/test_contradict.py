"""Contradiction detection: first-class rows, conflicting claims coexist (never collapsed)."""

from __future__ import annotations

import logging
from datetime import date

from helixpay.contracts import Claim, Contradiction, Link
from helixpay.ingest.contradict import (
    classify,
    detect,
    detect_link_conflicts,
    normalize_value,
    values_conflict,
)

_Q1 = date(2026, 3, 31)


class FakeRepo:
    def __init__(self, claims: list[Claim]) -> None:
        self._claims = claims
        self.contradictions: list[Contradiction] = []

    def get_claims(self, subject_id, predicate=None):
        return [
            c
            for c in self._claims
            if c.subject_entity_id == subject_id
            and (predicate is None or c.predicate == predicate)
        ]

    def get_contradictions(self, subject_id=None):
        return [
            c
            for c in self.contradictions
            if subject_id is None or c.subject_entity_id == subject_id
        ]

    def add_contradiction(self, c: Contradiction) -> None:
        pair = tuple(
            sorted((c.claim_a_id, c.claim_b_id))
        )  # mirror the repo's pair-dedup
        if any(
            tuple(sorted((x.claim_a_id, x.claim_b_id))) == pair
            for x in self.contradictions
        ):
            return
        self.contradictions.append(c)


def _claim(cid, value, *, as_of=_Q1, doc=1, valid_to=None, superseded_by=None):
    return Claim(
        id=cid,
        subject_entity_id=10,
        predicate="revenue",
        object_value=value,
        as_of=as_of,
        valid_to=valid_to,
        superseded_by=superseded_by,
        document_id=doc,
    )


def test_same_period_two_sources_disagree_is_source_disagreement():
    repo = FakeRepo([_claim(1, "SGD 14.2M", doc=1), _claim(2, "SGD 13.9M", doc=2)])
    n = detect(repo, 10, "revenue")
    assert n == 1
    c = repo.contradictions[0]
    assert {c.claim_a_id, c.claim_b_id} == {1, 2}
    assert c.kind == "source_disagreement"
    assert c.subject_entity_id == 10 and c.predicate == "revenue"


def test_equal_values_across_currency_formatting_is_not_a_conflict():
    repo = FakeRepo([_claim(1, "SGD 14.2M", doc=1), _claim(2, "14.2M", doc=2)])
    assert detect(repo, 10, "revenue") == 0


def test_different_as_of_points_do_not_overlap():
    # Q4 vs Q1 revenue: a legitimate period change, not a contradiction.
    repo = FakeRepo(
        [
            _claim(1, "SGD 11.0M", as_of=date(2025, 12, 31)),
            _claim(2, "SGD 14.2M", as_of=_Q1),
        ]
    )
    assert detect(repo, 10, "revenue") == 0


def test_overlapping_window_with_different_as_of_is_temporal():
    a = _claim(1, "end of June", as_of=date(2026, 4, 15), valid_to=date(2026, 7, 1))
    b = _claim(2, "end of Q3", as_of=date(2026, 4, 21))
    repo = FakeRepo([a, b])
    n = detect(repo, 10, "revenue")
    assert n == 1 and repo.contradictions[0].kind == "temporal"


def test_non_numeric_same_period_disagreement():
    repo = FakeRepo([_claim(1, "end of June", doc=1), _claim(2, "end of Q3", doc=2)])
    assert detect(repo, 10, "revenue") == 1


def test_superseded_claims_are_ignored():
    repo = FakeRepo(
        [_claim(1, "SGD 13.9M", doc=1, superseded_by=2), _claim(2, "SGD 14.2M", doc=2)]
    )
    assert detect(repo, 10, "revenue") == 0  # only one live claim


def test_claim_without_id_is_skipped(caplog):
    repo = FakeRepo([_claim(None, "SGD 14.2M", doc=1), _claim(2, "SGD 13.9M", doc=2)])
    with caplog.at_level(logging.WARNING, logger="helixpay.ingest.contradict"):
        assert detect(repo, 10, "revenue") == 0
    assert any("skip" in r.message.lower() for r in caplog.records)


def test_detection_does_not_mutate_claims():
    claims = [_claim(1, "SGD 14.2M", doc=1), _claim(2, "SGD 13.9M", doc=2)]
    repo = FakeRepo(claims)
    detect(repo, 10, "revenue")
    assert all(
        c.superseded_by is None and c.valid_to is None for c in claims
    )  # never collapsed


# NOTE: pure ``normalize_value`` parsing (magnitude/currency suffixes, comma
# separators, label-digit refusal) is owned by ``test/unit/ingest/test_normalize.py``
# (``test_magnitude_suffix_variants`` covers the K/b/bn suffixes,
# ``test_currency_and_magnitude_word`` + ``test_real_currency_symbol`` the SGD/R$ forms,
# ``test_comma_thousands_separator`` the comma parse, ``test_quarter_labels_compare_as_text``
# + ``test_version_string_not_numeric`` the label-digit refusal). This file keeps only
# ``contradict``'s OWN ``values_conflict`` semantics (SP_030 Item 4 — owner-cited removal).
def test_unicode_minus_equals_ascii_minus():
    assert normalize_value("−11%")[1] == normalize_value("-11%")[1] == -11.0
    assert values_conflict("−11%", "-11%") is False


def test_eighteen_months_is_not_eighteen_million():
    assert values_conflict("18 months", "18M") is True  # not the same value


def test_unicode_minus_normalized_in_text_fallback():
    # non-numeric labels carrying a unicode minus must not spuriously conflict
    assert values_conflict("−Q4 update", "-Q4 update") is False


def test_values_conflict_numeric_vs_string():
    assert values_conflict("SGD 14.2M", "SGD 13.9M") is True
    assert values_conflict("47", "47.0") is False
    assert values_conflict("end of June", "end of june") is False  # casefold equal


def test_values_conflict_with_a_missing_value_is_not_a_conflict():
    assert values_conflict(None, "SGD 14.2M") is False
    assert values_conflict(None, None) is False


def test_classify_undated_cross_source_is_source_disagreement():
    a = _claim(1, "end of June", as_of=None, doc=1)
    b = _claim(2, "end of Q3", as_of=date(2026, 4, 21), doc=2)
    assert (
        classify(a, b) == "source_disagreement"
    )  # not "temporal" just because one is undated
    c = _claim(3, "x", as_of=None, doc=1)
    d = _claim(4, "y", as_of=None, doc=2)
    assert classify(c, d) == "source_disagreement"


def test_word_form_numbers_are_not_false_conflicts():
    # SP_010: contradict now delegates to the shared normalize util, which folds word
    # cardinals and word magnitudes. These pairs must NOT fire (no_false_contradiction).
    assert values_conflict("18 months", "eighteen months") is False
    assert values_conflict("SGD 14.2M", "14.2 million") is False
    # a genuine disagreement still fires
    assert values_conflict("SGD 14.2M", "SGD 13.9M") is True


def _tclaim(cid, value, as_of, *, subject=20, predicate="ga_target", doc=1):
    return Claim(
        id=cid,
        subject_entity_id=subject,
        predicate=predicate,
        object_value=value,
        as_of=as_of,
        document_id=doc,
    )


def test_target_predicate_slip_surfaces_despite_disjoint_as_of():
    # ga_target: as_of is the assertion date, not a validity window. A changed target
    # across two assertion dates (both valid_to=None) is a real temporal slip and must
    # surface — even though the point-windows do not overlap.
    a = _tclaim(1, "end of June 2026", date(2026, 4, 15), doc=1)
    b = _tclaim(2, "end of Q3 2026", date(2026, 5, 12), doc=2)
    repo = FakeRepo([a, b])
    assert detect(repo, 20, "ga_target") == 1
    assert repo.contradictions[0].kind == "temporal"


def test_completion_target_slip_also_surfaces_and_is_idempotent():
    a = _tclaim(
        1, "end of June 2026", date(2026, 4, 15), predicate="completion_target", doc=1
    )
    b = _tclaim(
        2, "end of August 2026", date(2026, 5, 12), predicate="completion_target", doc=2
    )
    repo = FakeRepo([a, b])
    assert detect(repo, 20, "completion_target") == 1
    assert detect(repo, 20, "completion_target") == 0  # re-run writes nothing new


def test_non_target_metric_time_series_still_not_a_conflict():
    # The window bypass is scoped: revenue at two disjoint as_of points is a legitimate
    # series, not a contradiction — the bypass must NOT regress this.
    a = _tclaim(1, "SGD 11.0M", date(2025, 12, 31), predicate="revenue", doc=1)
    b = _tclaim(2, "SGD 14.2M", date(2026, 3, 31), predicate="revenue", doc=2)
    repo = FakeRepo([a, b])
    assert detect(repo, 20, "revenue") == 0


def test_detect_is_idempotent_on_rerun():
    repo = FakeRepo([_claim(1, "SGD 14.2M", doc=1), _claim(2, "SGD 13.9M", doc=2)])
    assert detect(repo, 10, "revenue") == 1
    assert detect(repo, 10, "revenue") == 0  # second pass writes nothing new
    assert len(repo.contradictions) == 1  # pair-deduped, not double-counted


# --------------------------------------------------------------------------- #
# Link / graph contradictions (SP_011): two reports_to edges, same from, different
# manager, overlapping validity → a first-class Contradiction pairing the two LINKS.
# --------------------------------------------------------------------------- #
class FakeLinkRepo:
    """Minimal repo for the link sweep: links + link-pair-deduped contradictions."""

    def __init__(self, links: list[Link]) -> None:
        self._links = links
        self.contradictions: list[Contradiction] = []

    def get_links(self, link_type=None, from_entity_id=None):
        return [
            l
            for l in self._links
            if (link_type is None or l.link_type == link_type)
            and (from_entity_id is None or l.from_entity_id == from_entity_id)
        ]

    def get_contradictions(self, subject_id=None):
        return [
            c
            for c in self.contradictions
            if subject_id is None or c.subject_entity_id == subject_id
        ]

    def add_contradiction(self, c: Contradiction) -> None:
        # dedup on the LINK pair (claim ids are None for graph contradictions) — mirrors
        # the DB partial unique index contradictions_link_pair.
        if c.link_a_id is None or c.link_b_id is None:
            self.contradictions.append(c)
            return
        key = (min(c.link_a_id, c.link_b_id), max(c.link_a_id, c.link_b_id))
        if any(
            x.link_a_id is not None
            and (min(x.link_a_id, x.link_b_id), max(x.link_a_id, x.link_b_id)) == key
            for x in self.contradictions
        ):
            return
        self.contradictions.append(c)


def _link(lid, from_id, to_id, *, link_type="reports_to", as_of=_Q1, valid_to=None, document_id=1):
    return Link(
        id=lid,
        from_entity_id=from_id,
        to_entity_id=to_id,
        link_type=link_type,
        as_of=as_of,
        valid_to=valid_to,
        document_id=document_id,
    )


def test_link_conflict_two_managers_cross_source_fires():
    repo = FakeLinkRepo([_link(1, 5, 10, document_id=1), _link(2, 5, 11, document_id=2)])
    assert detect_link_conflicts(repo, 5, "reports_to") == 1
    c = repo.contradictions[0]
    assert {c.link_a_id, c.link_b_id} == {1, 2}
    assert c.subject_entity_id == 5 and c.predicate == "reports_to"
    assert c.claim_a_id is None and c.claim_b_id is None  # a link-pair, not a claim-pair
    assert c.kind == "source_disagreement"  # different documents


def test_link_conflict_same_document_is_value_conflict():
    repo = FakeLinkRepo([_link(1, 5, 10, document_id=7), _link(2, 5, 11, document_id=7)])
    assert detect_link_conflicts(repo, 5, "reports_to") == 1
    assert repo.contradictions[0].kind == "value_conflict"  # one source, not a disagreement


def test_link_same_manager_is_not_a_conflict():
    # two sources agreeing on the manager → no conflict
    repo = FakeLinkRepo([_link(1, 5, 10, document_id=1), _link(2, 5, 10, document_id=2)])
    assert detect_link_conflicts(repo, 5, "reports_to") == 0


def test_link_dotted_line_is_never_swept():
    repo = FakeLinkRepo(
        [_link(1, 5, 10, link_type="reports_to"), _link(2, 5, 11, link_type="dotted_line_to")]
    )
    # the solid group has a single edge → 0; dotted is not allowlisted → 0 (a person with
    # one solid manager + one functional dotted-line is NOT a contradiction)
    assert detect_link_conflicts(repo, 5, "reports_to") == 0
    assert detect_link_conflicts(repo, 5, "dotted_line_to") == 0


def test_link_member_of_is_never_swept():
    # a person legitimately belongs to multiple teams — member_of is not single-valued
    repo = FakeLinkRepo(
        [_link(1, 5, 10, link_type="member_of"), _link(2, 5, 11, link_type="member_of")]
    )
    assert detect_link_conflicts(repo, 5, "member_of") == 0


def test_link_disjoint_windows_is_succession_not_conflict():
    # an old CLOSED reporting line + a later OPEN one do not overlap → legitimate manager
    # change, not a contradiction
    repo = FakeLinkRepo(
        [
            _link(1, 5, 10, as_of=date(2026, 1, 1), valid_to=date(2026, 2, 1)),
            _link(2, 5, 11, as_of=date(2026, 3, 1), valid_to=None),
        ]
    )
    assert detect_link_conflicts(repo, 5, "reports_to") == 0


def test_link_two_open_lines_overlap_and_fire():
    # both valid_to=None (still in effect) → open windows overlap → conflict surfaces
    repo = FakeLinkRepo(
        [
            _link(1, 5, 10, as_of=date(2026, 1, 1), valid_to=None, document_id=1),
            _link(2, 5, 11, as_of=date(2026, 6, 1), valid_to=None, document_id=2),
        ]
    )
    assert detect_link_conflicts(repo, 5, "reports_to") == 1


def test_link_conflict_idempotent_on_rerun():
    repo = FakeLinkRepo([_link(1, 5, 10, document_id=1), _link(2, 5, 11, document_id=2)])
    assert detect_link_conflicts(repo, 5, "reports_to") == 1
    assert detect_link_conflicts(repo, 5, "reports_to") == 0  # re-run writes nothing new
    assert len(repo.contradictions) == 1


def test_link_conflict_skips_unpersisted_edge(caplog):
    repo = FakeLinkRepo([_link(None, 5, 10), _link(2, 5, 11)])
    with caplog.at_level(logging.WARNING, logger="helixpay.ingest.contradict"):
        assert detect_link_conflicts(repo, 5, "reports_to") == 0
    assert any("skip" in r.message.lower() for r in caplog.records)


def test_link_conflict_zero_edges_is_noop():
    # no edges for the group → nothing to compare, no contradiction, no crash
    repo = FakeLinkRepo([])
    assert detect_link_conflicts(repo, 5, "reports_to") == 0
    assert repo.contradictions == []


def test_link_conflict_single_edge_is_noop():
    # one manager is the normal case — a single reports_to edge never self-conflicts
    repo = FakeLinkRepo([_link(1, 5, 10)])
    assert detect_link_conflicts(repo, 5, "reports_to") == 0
    assert repo.contradictions == []
