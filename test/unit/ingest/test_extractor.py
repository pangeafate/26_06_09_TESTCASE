"""ChunkExtractor: render named prompt -> LLM -> validated candidates, per-item drop."""

from __future__ import annotations

import json
import logging

from helixpay.contracts import Chunk
from helixpay.ingest.extract.extractor import ChunkContext, ChunkExtractor


class StubLLM:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def generate(self, *, system: str, user: str, max_tokens: int) -> str:
        self.calls.append((system, user))
        return self._responses.pop(0)


_MIXED = json.dumps(
    {
        "claims": [
            {"subject": "HelixPay", "subject_type": "metric", "predicate": "ARR", "object_value": "SGD 14.2M", "as_of": "2026-03-31"},
            {"subject": "Cosmos", "predicate": "arr", "object_value": "SGD 165K", "hypothetical": True},
            {"subject": "X", "subject_type": "wizard", "predicate": "p", "object_value": "v"},
        ],
        "relations": [
            {"from_entity": "Sara Wijaya", "to_entity": "Daniel Tan", "link_type": "reports_to"},
            {"from_entity": "a", "to_entity": "b", "link_type": "manages"},
        ],
    }
)

_CTX = ChunkContext(source_type="md", source_uri="data/x.md", as_of="2026-03-31", roster_hint="Daniel Tan (person)")


def test_extract_keeps_valid_drops_bad_and_hypothetical(caplog):
    llm = StubLLM([_MIXED])
    ex = ChunkExtractor(llm)
    with caplog.at_level(logging.WARNING, logger="helixpay.ingest.extract.extractor"):
        out = ex.extract(Chunk(document_id=1, ordinal=0, text="body"), _CTX)

    # valid metric claim kept; bad subject_type dropped; hypothetical dropped
    assert [c.predicate for c in out.claims] == ["ARR"]
    # valid relation kept; bad link_type dropped
    assert [r.link_type for r in out.relations] == ["reports_to"]
    assert any("drop" in r.message.lower() for r in caplog.records)


def test_extract_renders_named_prompt_with_chunk_body():
    llm = StubLLM(['{"claims": [], "relations": []}'])
    ex = ChunkExtractor(llm)
    ex.extract(Chunk(document_id=1, ordinal=0, text="ZZ_BODY_ZZ"), _CTX)
    _system, user = llm.calls[0]
    assert "ZZ_BODY_ZZ" in user
    assert "data/x.md" in user


def test_extract_returns_empty_when_llm_unrecoverable():
    llm = StubLLM(["not json", "still not json"])  # original + repair both fail
    ex = ChunkExtractor(llm)
    out = ex.extract(Chunk(document_id=1, ordinal=0, text="body"), _CTX)
    assert out.claims == []
    assert out.relations == []


# --------------------------------------------------------------------------- #
# gleaning
# --------------------------------------------------------------------------- #
def _claims_json(*triples):
    claims = [{"subject": s, "predicate": p, "object_value": v, "evidence": v} for s, p, v in triples]
    return json.dumps({"claims": claims, "relations": []})


def test_gleaning_off_by_default_single_call():
    llm = StubLLM([_claims_json(("HelixPay", "revenue", "14.2M"))])
    ex = ChunkExtractor(llm)  # glean_passes defaults to 0
    out = ex.extract(Chunk(document_id=1, ordinal=0, text="14.2M revenue"), _CTX)
    assert len(llm.calls) == 1  # no gleaning pass
    assert [c.object_value for c in out.claims] == ["14.2M"]


def test_gleaning_merges_new_claims_and_feeds_prior_output_back():
    llm = StubLLM([_claims_json(("HelixPay", "revenue", "14.2M")),
                   _claims_json(("HelixPay", "arr", "51M"))])
    ex = ChunkExtractor(llm, glean_passes=1)
    out = ex.extract(Chunk(document_id=1, ordinal=0, text="14.2M revenue and 51M arr"), _CTX)
    assert len(llm.calls) == 2
    assert {c.object_value for c in out.claims} == {"14.2M", "51M"}
    assert "revenue" in llm.calls[1][1].lower()  # pass-1 prompt echoes the prior output


def test_gleaning_dedups_exact_repeat():
    llm = StubLLM([_claims_json(("HelixPay", "revenue", "14.2M")),
                   _claims_json(("helixpay", "Revenue", "14.2M"), ("HelixPay", "arr", "51M"))])
    ex = ChunkExtractor(llm, glean_passes=1)
    out = ex.extract(Chunk(document_id=1, ordinal=0, text="x"), _CTX)
    keys = sorted((c.subject.lower(), c.predicate.lower(), c.object_value) for c in out.claims)
    assert keys == [("helixpay", "arr", "51M"), ("helixpay", "revenue", "14.2M")]  # repeat folded


def test_gleaning_early_stops_when_nothing_new():
    llm = StubLLM([_claims_json(("HelixPay", "revenue", "14.2M")),
                   json.dumps({"claims": [], "relations": []})])
    ex = ChunkExtractor(llm, glean_passes=2)  # would do 2, but stops after the empty pass
    out = ex.extract(Chunk(document_id=1, ordinal=0, text="x"), _CTX)
    assert len(llm.calls) == 2  # base + one gleaning pass; no 3rd
    assert [c.object_value for c in out.claims] == ["14.2M"]


def test_gleaning_keeps_same_value_at_a_different_as_of():
    base = json.dumps({"claims": [{"subject": "HelixPay", "predicate": "revenue", "object_value": "14.2M", "as_of": "2026-03-31", "evidence": "14.2M"}], "relations": []})
    glean = json.dumps({"claims": [{"subject": "HelixPay", "predicate": "revenue", "object_value": "14.2M", "as_of": "2025-03-31", "evidence": "14.2M"}], "relations": []})
    ex = ChunkExtractor(StubLLM([base, glean]), glean_passes=1)
    out = ex.extract(Chunk(document_id=1, ordinal=0, text="14.2M"), _CTX)
    assert sorted(c.as_of for c in out.claims) == ["2025-03-31", "2026-03-31"]  # not collapsed


def test_gleaning_dedups_relations():
    rel = lambda: {"relations": [{"from_entity": "Sara Wijaya", "to_entity": "Daniel Tan", "link_type": "reports_to"}], "claims": []}
    ex = ChunkExtractor(StubLLM([json.dumps(rel()), json.dumps(rel())]), glean_passes=1)
    out = ex.extract(Chunk(document_id=1, ordinal=0, text="x"), _CTX)
    assert len(out.relations) == 1  # duplicate relation folded


def test_gleaning_runs_all_passes_when_each_adds():
    llm = StubLLM([_claims_json(("HelixPay", "revenue", "14.2M")),
                   _claims_json(("HelixPay", "arr", "51M")),
                   _claims_json(("HelixPay", "nps", "47"))])
    ex = ChunkExtractor(llm, glean_passes=2)
    out = ex.extract(Chunk(document_id=1, ordinal=0, text="x"), _CTX)
    assert len(llm.calls) == 3  # base + 2 gleaning passes, each added
    assert {c.object_value for c in out.claims} == {"14.2M", "51M", "47"}


def test_gleaning_bad_pass_keeps_first_pass():
    llm = StubLLM([_claims_json(("HelixPay", "revenue", "14.2M")), "garbage", "still garbage"])
    ex = ChunkExtractor(llm, glean_passes=1)
    out = ex.extract(Chunk(document_id=1, ordinal=0, text="x"), _CTX)
    assert [c.object_value for c in out.claims] == ["14.2M"]  # base survives a failed glean


def test_gleaning_skipped_over_token_budget():
    llm = StubLLM([_claims_json(("HelixPay", "revenue", "14.2M"))])
    ex = ChunkExtractor(llm, glean_passes=1, glean_token_budget=1)  # tiny budget
    out = ex.extract(Chunk(document_id=1, ordinal=0, text="a long chunk body well over budget"), _CTX)
    assert len(llm.calls) == 1  # gleaning skipped
    assert [c.object_value for c in out.claims] == ["14.2M"]


# --------------------------------------------------------------------------- #
# grounding penalty
# --------------------------------------------------------------------------- #
def test_ungrounded_claim_confidence_is_penalized_not_dropped():
    # value 99M is not in the evidence -> ungrounded -> penalized, but kept
    bad = json.dumps({"claims": [{"subject": "HelixPay", "predicate": "revenue",
                                  "object_value": "99M", "evidence": "revenue was 14.2M", "confidence": 0.8}],
                      "relations": []})
    ex = ChunkExtractor(StubLLM([bad]))
    out = ex.extract(Chunk(document_id=1, ordinal=0, text="revenue was 14.2M"), _CTX)
    assert len(out.claims) == 1  # NOT dropped
    assert out.claims[0].confidence < 0.8  # penalized


def test_grounded_claim_confidence_unchanged():
    good = json.dumps({"claims": [{"subject": "HelixPay", "predicate": "revenue",
                                   "object_value": "14.2M", "evidence": "revenue was 14.2M", "confidence": 0.8}],
                       "relations": []})
    ex = ChunkExtractor(StubLLM([good]))
    out = ex.extract(Chunk(document_id=1, ordinal=0, text="revenue was 14.2M"), _CTX)
    assert out.claims[0].confidence == 0.8
