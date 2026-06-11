"""LLM contradiction adjudication (SP_028b) — cluster gen, content cache, two-block I/O,
single-writer arbitration, deterministic fallback floor.

All $0: a scripted stub ``LLMClient`` (no network, no API key) + an in-memory dict cache.
The two-block design (CLAIM ``C1..Cn`` / LINK ``L1..Lm``) makes a claim↔link pair structurally
impossible — a pair always names ONE block (Stage-3 C-1/C-2 fix).
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Callable, Optional

import pytest

from eval.contradiction_recall import _present
from helixpay.contracts import Claim, Contradiction, Link
from helixpay.ingest import adjudicate
from helixpay.ingest.adjudicate import (
    DictCache,
    adjudicate_store,
    build_cluster,
    cluster_cache_key,
)

# --------------------------------------------------------------------------- #
# Test doubles                                                                #
# --------------------------------------------------------------------------- #


class StubClient:
    """An ``LLMClient`` whose ``generate`` returns ``responder(user)``; counts calls."""

    def __init__(self, responder: Callable[[str], str]) -> None:
        self._responder = responder
        self.calls = 0

    def generate(self, *, system: str, user: str, max_tokens: int) -> str:
        self.calls += 1
        return self._responder(user)


def verdict_json(*pairs: dict) -> str:
    return json.dumps({"contradictions": list(pairs)})


def pair(block: str, a: int, b: int, kind: str = "value_conflict", rationale: str = "r") -> dict:
    return {"block": block, "a": a, "b": b, "kind": kind, "rationale": rationale}


class FakeRepo:
    """Minimal Repository surface the sweep touches (mirrors test_sweep_dedup's FakeRepo)."""

    def __init__(self, claims: list[Claim], links: Optional[list[Link]] = None) -> None:
        self._claims = claims
        self._links = links or []
        self.contradictions: list[Contradiction] = []
        self.cleared = 0

    # canonicalization is identity here (the test predicates are already canonical)
    def canonical_predicate(self, raw: str) -> str:
        return raw

    def resolve_entity(self, name, entity_type=None, context=None):
        return None

    def clear_contradictions(self) -> int:
        n = len(self.contradictions)
        self.contradictions = []
        self.cleared += 1
        return n

    def distinct_claim_groups(self) -> list[tuple[int, str]]:
        out: list[tuple[int, str]] = []
        for c in self._claims:
            k = (c.subject_entity_id, c.predicate)
            if k not in out:
                out.append(k)
        return out

    def distinct_link_groups(self) -> list[tuple[int, str]]:
        out: list[tuple[int, str]] = []
        for ln in self._links:
            k = (ln.from_entity_id, ln.link_type)
            if k not in out:
                out.append(k)
        return out

    def get_claims(self, subject_id, predicate=None):
        return [
            c
            for c in self._claims
            if c.subject_entity_id == subject_id and (predicate is None or c.predicate == predicate)
        ]

    def get_links(self, link_type=None, from_entity_id=None, to_entity_id=None):
        return [
            ln
            for ln in self._links
            if (link_type is None or ln.link_type == link_type)
            and (from_entity_id is None or ln.from_entity_id == from_entity_id)
        ]

    def get_contradictions(self, subject_id=None):
        return [
            c
            for c in self.contradictions
            if subject_id is None or c.subject_entity_id == subject_id
        ]

    def add_contradiction(self, c: Contradiction) -> None:
        # mirror the real UNIQUE(claim pair) / (link pair) dedup
        if c.claim_a_id is not None:
            key = tuple(sorted((c.claim_a_id, c.claim_b_id)))
            if any(
                x.claim_a_id is not None and tuple(sorted((x.claim_a_id, x.claim_b_id))) == key
                for x in self.contradictions
            ):
                return
        elif c.link_a_id is not None:
            key = tuple(sorted((c.link_a_id, c.link_b_id)))
            if any(
                x.link_a_id is not None and tuple(sorted((x.link_a_id, x.link_b_id))) == key
                for x in self.contradictions
            ):
                return
        self.contradictions.append(c)


def _c(cid, subj, pred, value, as_of=date(2026, 3, 31), doc=None):
    return Claim(
        id=cid, subject_entity_id=subj, predicate=pred, object_value=value, as_of=as_of,
        document_id=doc if doc is not None else cid,
    )


def _link(lid, frm, to, ltype="reports_to", as_of=None, doc=None):
    return Link(id=lid, from_entity_id=frm, to_entity_id=to, link_type=ltype, as_of=as_of,
                valid_to=None, document_id=doc)


# --------------------------------------------------------------------------- #
# Cluster generation                                                          #
# --------------------------------------------------------------------------- #


def test_cluster_is_two_blocks_cross_predicate_claims_plus_links():
    claims = [
        _c(1, 10, "revenue", "SGD 14.2M"),
        _c(2, 10, "nps", "47"),
        _c(3, 10, "pain_point", "slow onboarding"),  # set_valued → excluded from claim block
    ]
    links = [
        _link(4, 10, 99, "reports_to"),
        _link(5, 10, 88, "dotted_line_to"),
    ]
    cluster = build_cluster(FakeRepo(claims, links), 10)
    assert {m.predicate for m in cluster.claims} == {"revenue", "nps"}  # pain_point dropped
    assert {m.predicate for m in cluster.links} == {"reports_to", "dotted_line_to"}


def test_member_order_is_signature_sorted_not_fetch_order():
    # Same members, reversed fetch order → identical block numbering AND the same cache key.
    fwd = FakeRepo([_c(1, 10, "revenue", "SGD 14.2M"), _c(2, 10, "nps", "47")])
    rev = FakeRepo([_c(2, 10, "nps", "47"), _c(1, 10, "revenue", "SGD 14.2M")])
    cl_f, cl_r = build_cluster(fwd, 10), build_cluster(rev, 10)
    assert [m.row_id for m in cl_f.claims] == [m.row_id for m in cl_r.claims]
    assert cluster_cache_key(cl_f) == cluster_cache_key(cl_r)


def test_cache_key_is_content_not_surrogate_id_and_excludes_source_uri():
    a = build_cluster(FakeRepo([_c(1, 10, "revenue", "SGD 14.2M", doc=1),
                                _c(2, 10, "nps", "47", doc=2)]), 10)
    # different row ids AND different document_ids/source, same semantic content → same key
    b = build_cluster(FakeRepo([_c(7, 10, "revenue", "SGD 14.2M", doc=555),
                                _c(9, 10, "nps", "47", doc=777)]), 10)
    assert cluster_cache_key(a) == cluster_cache_key(b)


def test_model_is_part_of_cache_key():
    # The model rides in the key, so a Sonnet run and an Opus run never share a cached verdict.
    cl = build_cluster(FakeRepo([_c(1, 10, "revenue", "SGD 14.2M"), _c(2, 10, "nps", "47")]), 10)
    assert cluster_cache_key(cl, model="claude-sonnet-4-6") != cluster_cache_key(cl, model="claude-opus-4-8")


def test_build_adjudicator_client_model_override():
    from helixpay.ingest.adjudicate import ADJUDICATE_MODEL, build_adjudicator_client

    assert build_adjudicator_client().model == ADJUDICATE_MODEL  # default = Opus synthesis tier
    assert build_adjudicator_client().temperature == 0
    c = build_adjudicator_client(model="claude-sonnet-4-6")
    assert c.model == "claude-sonnet-4-6" and c.temperature == 0


def test_version_bump_invalidates_cache_key(monkeypatch):
    cl = build_cluster(FakeRepo([_c(1, 10, "revenue", "SGD 14.2M"), _c(2, 10, "nps", "47")]), 10)
    base = cluster_cache_key(cl)
    monkeypatch.setattr(adjudicate, "NORM_VERSION", "bumped-norm")
    assert cluster_cache_key(cl) != base
    monkeypatch.setattr(adjudicate, "NORM_VERSION", adjudicate.NORM_VERSION)
    monkeypatch.setattr(adjudicate, "PROMPT_VERSION", "bumped-prompt")
    assert cluster_cache_key(cl) != base


# --------------------------------------------------------------------------- #
# Write paths                                                                 #
# --------------------------------------------------------------------------- #


def test_cross_predicate_claim_pair_is_written_with_claim_ids():
    repo = FakeRepo([_c(1, 10, "revenue", "SGD 14.2M"), _c(2, 10, "revenue_vs_plan", "below plan")])
    client = StubClient(lambda u: verdict_json(pair("claim", 1, 2)))
    adjudicate_store(repo, client, DictCache())
    assert len(repo.contradictions) == 1
    row = repo.contradictions[0]
    assert {row.claim_a_id, row.claim_b_id} == {1, 2}
    assert row.link_a_id is None and row.link_b_id is None


def test_link_pair_is_written_with_link_ids():
    # Maria #6: solid reports_to vs dotted_line_to → a LINK-block pair.
    repo = FakeRepo([], [_link(1, 10, 99, "reports_to"), _link(2, 10, 88, "dotted_line_to")])
    client = StubClient(lambda u: verdict_json(pair("link", 1, 2, kind="source_disagreement")))
    adjudicate_store(repo, client, DictCache())
    assert len(repo.contradictions) == 1
    row = repo.contradictions[0]
    assert {row.link_a_id, row.link_b_id} == {1, 2}
    assert row.claim_a_id is None and row.claim_b_id is None


def test_out_of_range_index_pair_is_dropped_zero_uncited():
    repo = FakeRepo([_c(1, 10, "revenue", "SGD 14.2M"), _c(2, 10, "revenue", "SGD 13.9M")])
    client = StubClient(lambda u: verdict_json(pair("claim", 1, 99)))  # 99 out of range
    adjudicate_store(repo, client, DictCache())
    assert repo.contradictions == []


def test_link_block_index_on_claims_only_cluster_is_dropped():
    # No link block → a verdict citing the LINK block must drop (out of range), never write.
    repo = FakeRepo([_c(1, 10, "revenue", "SGD 14.2M"), _c(2, 10, "revenue", "SGD 13.9M")])
    client = StubClient(lambda u: verdict_json(pair("link", 1, 2)))
    adjudicate_store(repo, client, DictCache())
    assert repo.contradictions == []


def test_self_pair_is_dropped():
    repo = FakeRepo([_c(1, 10, "revenue", "SGD 14.2M"), _c(2, 10, "revenue", "SGD 13.9M")])
    client = StubClient(lambda u: verdict_json(pair("claim", 1, 1)))  # a == b
    adjudicate_store(repo, client, DictCache())
    assert repo.contradictions == []


def test_llm_note_carries_both_values_verbatim_for_oracle_match():
    repo = FakeRepo([_c(1, 10, "revenue", "SGD 14.2M"), _c(2, 10, "revenue", "SGD 13.9M")])
    client = StubClient(lambda u: verdict_json(pair("claim", 1, 2)))
    adjudicate_store(repo, client, DictCache())
    note = repo.contradictions[0].note or ""
    assert note.startswith("[llm]")
    assert _present("SGD 14.2M", note) and _present("SGD 13.9M", note)


# --------------------------------------------------------------------------- #
# Arbitration: precision drop vs fallback floor                               #
# --------------------------------------------------------------------------- #


def test_empty_verdict_is_authoritative_no_fallback():
    # Two conflicting claims; the LLM returns NO pairs → precision win: zero rows, no floor.
    repo = FakeRepo([_c(1, 10, "revenue", "SGD 14.2M"), _c(2, 10, "revenue", "SGD 13.9M")])
    client = StubClient(lambda u: verdict_json())  # empty contradictions
    adjudicate_store(repo, client, DictCache())
    assert repo.contradictions == []


def test_undecodable_verdict_falls_back_to_deterministic_floor():
    # call_structured drops (garbage in, garbage on repair) → verdict ABSENT → floor writes the row.
    repo = FakeRepo([_c(1, 10, "revenue", "SGD 14.2M"), _c(2, 10, "revenue", "SGD 13.9M")])
    client = StubClient(lambda u: "not json at all")
    adjudicate_store(repo, client, DictCache())
    assert len(repo.contradictions) == 1
    note = repo.contradictions[0].note or ""
    assert not note.startswith("[llm]")  # deterministic floor note, not an LLM verdict
    assert client.calls == 2  # initial + one repair, then drop


def test_oversized_cluster_falls_back_and_logs_cap(caplog):
    repo = FakeRepo([_c(1, 10, "revenue", "SGD 14.2M"), _c(2, 10, "revenue", "SGD 13.9M")])
    client = StubClient(lambda u: verdict_json(pair("claim", 1, 2)))
    with caplog.at_level(logging.INFO):
        adjudicate_store(repo, client, DictCache(), max_cluster_members=1)
    assert client.calls == 0  # never reached the LLM
    assert len(repo.contradictions) == 1  # deterministic floor caught it
    assert any("cap" in r.message.lower() for r in caplog.records)


# --------------------------------------------------------------------------- #
# Cache + dry-run                                                             #
# --------------------------------------------------------------------------- #


def test_second_sweep_on_unchanged_store_makes_zero_llm_calls():
    repo = FakeRepo([_c(1, 10, "revenue", "SGD 14.2M"), _c(2, 10, "revenue", "SGD 13.9M")])
    cache = DictCache()
    client = StubClient(lambda u: verdict_json(pair("claim", 1, 2)))
    adjudicate_store(repo, client, cache)
    first = client.calls
    assert first >= 1
    adjudicate_store(repo, client, cache)  # unchanged store → all cache hits
    assert client.calls == first  # no new calls


def test_dry_run_writes_nothing_and_makes_no_calls():
    repo = FakeRepo([_c(1, 10, "revenue", "SGD 14.2M"), _c(2, 10, "revenue", "SGD 13.9M")])
    client = StubClient(lambda u: verdict_json(pair("claim", 1, 2)))
    stats = adjudicate_store(repo, client, DictCache(), dry_run=True)
    assert client.calls == 0
    assert repo.contradictions == []
    assert repo.cleared == 0  # the table is not even cleared in a dry run
    assert stats["clusters"] == 1 and stats["estimated_llm_calls"] == 1
