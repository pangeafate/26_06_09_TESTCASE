"""Unit tests for the pure gleaning utilities (SP_018 RDD/SRP split).

These cover the dedup-key + merge logic lifted out of ``ChunkExtractor`` into
``helixpay.ingest.extract.glean`` — no LLM, no ledger.
"""

from __future__ import annotations

import json

from helixpay.ingest.extract.glean import (
    claim_key,
    dump_already,
    estimate_tokens,
    merge_new,
    rel_key,
)
from helixpay.ingest.extract.schemas import ClaimOut, ExtractionOut, RelationOut


def _claim(subject="Acme", predicate="ARR", object_value="5", as_of=None):
    return ClaimOut(
        subject=subject, predicate=predicate, object_value=object_value, as_of=as_of
    )


def _rel(frm="Maria", to="HelixPay", link_type="member_of"):
    return RelationOut(from_entity=frm, to_entity=to, link_type=link_type)


def test_claim_key_is_case_and_space_insensitive_but_keeps_as_of():
    a = _claim(subject="  ACME  ", predicate="Arr", object_value=" 5 ", as_of="2025-01-01")
    b = _claim(subject="acme", predicate="arr", object_value="5", as_of="2025-01-01")
    assert claim_key(a) == claim_key(b)
    # same value at a different as_of must NOT collapse (temporal distinctness)
    c = _claim(subject="acme", predicate="arr", object_value="5", as_of="2025-04-01")
    assert claim_key(b) != claim_key(c)


def test_rel_key_normalizes_endpoints():
    assert rel_key(_rel(frm="  Maria ", to="HelixPay")) == (
        "maria",
        "helixpay",
        "member_of",
    )


def test_dump_already_is_json_with_claims_and_relations():
    payload = dump_already([_claim()], [_rel()])
    parsed = json.loads(payload)
    assert parsed["claims"][0]["subject"] == "Acme"
    assert parsed["relations"][0]["link_type"] == "member_of"


def test_estimate_tokens_is_quarter_length():
    assert estimate_tokens("a" * 40) == 10


def test_merge_new_appends_claims_then_relations_and_dedups_in_place():
    claims = [_claim(object_value="5")]
    relations = [_rel(link_type="member_of")]
    seen = {claim_key(c) for c in claims}
    seen_rel = {rel_key(r) for r in relations}

    extra = ExtractionOut(
        claims=[_claim(object_value="5"), _claim(object_value="9")],  # first is a dup
        relations=[_rel(link_type="reports_to")],  # new
    )
    added = merge_new(claims, relations, extra, seen, seen_rel)
    assert added is True
    assert [c.object_value for c in claims] == ["5", "9"]  # only the new claim appended
    assert [r.link_type for r in relations] == ["member_of", "reports_to"]
    # seen sets mutated in place so they carry to the next pass
    assert claim_key(_claim(object_value="9")) in seen
    assert rel_key(_rel(link_type="reports_to")) in seen_rel


def test_merge_new_preserves_order_with_dups_interleaved():
    claims = [_claim(object_value="5")]
    relations: list[RelationOut] = []
    seen = {claim_key(c) for c in claims}
    seen_rel: set = set()
    # [new, dup, new] within one pass -> appended in encounter order, dup skipped
    extra = ExtractionOut(
        claims=[_claim(object_value="7"), _claim(object_value="5"), _claim(object_value="9")],
        relations=[],
    )
    assert merge_new(claims, relations, extra, seen, seen_rel) is True
    assert [c.object_value for c in claims] == ["5", "7", "9"]


def test_merge_new_returns_false_when_nothing_new():
    claims = [_claim(object_value="5")]
    relations: list[RelationOut] = []
    seen = {claim_key(c) for c in claims}
    seen_rel: set = set()
    extra = ExtractionOut(claims=[_claim(object_value="5")], relations=[])
    assert merge_new(claims, relations, extra, seen, seen_rel) is False
    assert len(claims) == 1  # unchanged
