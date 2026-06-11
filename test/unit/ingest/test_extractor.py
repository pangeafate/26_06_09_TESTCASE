"""ChunkExtractor: render named prompt -> LLM -> coerce -> validated candidates, per-item drop."""

from __future__ import annotations

import json
import logging

from helixpay.contracts import Chunk
from helixpay.ingest.extract.extractor import ChunkContext, ChunkExtractor
from helixpay.ingest.extract.llm import GenerationResult


class StubLLM:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def generate(self, *, system: str, user: str, max_tokens: int) -> str:
        self.calls.append((system, user))
        return self._responses.pop(0)


class StubLLMWithMeta:
    """Stub that surfaces stop_reason via generate_with_meta."""

    def __init__(self, responses: list[GenerationResult]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def generate_with_meta(self, *, system: str, user: str, max_tokens: int) -> GenerationResult:
        self.calls.append((system, user))
        return self._responses.pop(0)


# _MIXED fixture:
# - "HelixPay" ARR claim with valid subject_type "metric" → kept
# - "Cosmos" arr hypothetical → dropped (hypothetical)
# - "X" with subject_type "wizard" → coerced to "other" (SP_025 fallback) → kept
# - Sara Wijaya → Daniel Tan reports_to → kept as-is
# - "a" manages "b" → coerced to reports_to with INVERSION: from=b, to=a → kept
# Net: 2 claims (ARR, p), 2 relations (both reports_to)
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
    """SP_014: 'manages' is COERCED to reports_to (inverted), so both relations survive.
    SP_025: the 'wizard' subject_type now coerces to 'other' (fallback) and is KEPT; only the
    hypothetical is dropped."""
    llm = StubLLM([_MIXED])
    ex = ChunkExtractor(llm)
    with caplog.at_level(logging.WARNING, logger="helixpay.ingest.extract.extractor"):
        out = ex.extract(Chunk(document_id=1, ordinal=0, text="body"), _CTX)

    # valid metric claim kept; wizard subject_type → other (kept, SP_025); hypothetical dropped
    assert [c.predicate for c in out.claims] == ["ARR", "p"]
    wizard = next(c for c in out.claims if c.predicate == "p")
    assert wizard.subject_type == "other"

    # Two relations: the original Sara→Daniel and the coerced 'manages' (now reports_to).
    # That two reports_to survive proves the extractor wires coerce in; the inversion
    # *direction* (b→a) is coerce math, owned by test_coerce.py — not re-asserted here.
    assert len(out.relations) == 2
    link_types = {r.link_type for r in out.relations}
    assert link_types == {"reports_to"}

    # The original relation must still be there
    original = next(r for r in out.relations if r.from_entity == "Sara Wijaya")
    assert original.to_entity == "Daniel Tan"
    assert original.link_type == "reports_to"

    # The hypothetical claim is the only real drop now (wizard recovered to 'other', SP_025).
    assert ex.ledger.per_source[_CTX.source_uri].dropped_by_reason["hypothetical"] == 1


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


# --------------------------------------------------------------------------- #
# SP_014 new tests: coerce, ledger, truncation
# --------------------------------------------------------------------------- #

def test_unmappable_subject_type_falls_back_to_other_and_is_counted():
    """SP_025: subject_type='wizard' coerces to 'other' (kept, not dropped) and the fallback
    is counted as a coercion in the ledger.

    This is the extractor↔coerce *wiring* test: it asserts only the ledger-counting
    that test_coerce.py does NOT cover. The coerce math itself is owned by test_coerce.py.
    """
    wizard = json.dumps({
        "claims": [
            {"subject": "X", "subject_type": "wizard", "predicate": "p", "object_value": "v"}
        ],
        "relations": []
    })
    llm = StubLLM([wizard])
    ex = ChunkExtractor(llm)
    out = ex.extract(Chunk(document_id=1, ordinal=0, text="body"), _CTX)
    assert len(out.claims) == 1 and out.claims[0].subject_type == "other"
    uri = _CTX.source_uri
    assert ex.ledger.per_source[uri].items_dropped == 0
    assert ex.ledger.per_source[uri].coerced_by_kind["subject_type_fallback"] >= 1


def test_ledger_records_chunk_on_extract():
    """Every call to extract() increments the chunk counter."""
    llm = StubLLM(['{"claims": [], "relations": []}', '{"claims": [], "relations": []}'])
    ex = ChunkExtractor(llm)
    ctx = ChunkContext(source_type="md", source_uri="data/doc.md")
    ex.extract(Chunk(document_id=1, ordinal=0, text="body"), ctx)
    ex.extract(Chunk(document_id=1, ordinal=1, text="body2"), ctx)
    assert ex.ledger.per_source["data/doc.md"].chunks == 2


def test_ledger_records_empty_extraction():
    """When the LLM is unrecoverable, empty_extractions is incremented."""
    llm = StubLLM(["not json", "still not json"])
    ex = ChunkExtractor(llm)
    ctx = ChunkContext(source_type="md", source_uri="data/empty.md")
    out = ex.extract(Chunk(document_id=1, ordinal=0, text="body"), ctx)
    assert out.claims == []
    assert ex.ledger.per_source["data/empty.md"].empty_extractions == 1


def test_ledger_records_truncated():
    """A max_tokens stop increments truncated_calls in the ledger."""
    truncated_json = '{"claims": [], "relations": []}'
    llm = StubLLMWithMeta([GenerationResult(text=truncated_json, stop_reason="max_tokens")])
    ctx = ChunkContext(source_type="md", source_uri="data/dense.md")
    ex = ChunkExtractor(llm)
    ex.extract(Chunk(document_id=1, ordinal=0, text="body"), ctx)
    assert ex.ledger.per_source["data/dense.md"].truncated_calls == 1


def test_ledger_probe_has_frozen_shape():
    """probe() emits the SP_015 keys plus SP_024's lossy_drops (the gating subset)."""
    llm = StubLLM(["not json", "still not json"])
    ex = ChunkExtractor(llm)
    ctx = ChunkContext(source_type="md", source_uri="data/x.md")
    ex.extract(Chunk(document_id=1, ordinal=0, text="body"), ctx)

    probe = ex.ledger.probe()
    assert "data/x.md" in probe
    keys = set(probe["data/x.md"].keys())
    assert keys == {"empty_extractions", "truncated_calls", "items_dropped", "lossy_drops"}


def test_ledger_hypothetical_drops_are_counted():
    """Hypothetical claims dropped post-extraction must be recorded in the ledger."""
    hypo = json.dumps({
        "claims": [
            {"subject": "Cosmos", "predicate": "arr", "object_value": "165K", "hypothetical": True},
            {"subject": "HelixPay", "predicate": "ARR", "object_value": "14.2M"},
        ],
        "relations": []
    })
    ex = ChunkExtractor(StubLLM([hypo]))
    ctx = ChunkContext(source_type="md", source_uri="data/h.md")
    out = ex.extract(Chunk(document_id=1, ordinal=0, text="body"), ctx)
    assert len(out.claims) == 1  # hypothetical dropped
    assert ex.ledger.per_source["data/h.md"].dropped_by_reason["hypothetical"] == 1


def test_injected_ledger_is_used():
    """A ledger injected at construction time is accumulated into."""
    from helixpay.ingest.extract.ledger import LossLedger
    shared = LossLedger()
    llm = StubLLM(['{"claims": [], "relations": []}'])
    ex = ChunkExtractor(llm, ledger=shared)
    ctx = ChunkContext(source_type="md", source_uri="data/shared.md")
    ex.extract(Chunk(document_id=1, ordinal=0, text="body"), ctx)
    assert shared.per_source["data/shared.md"].chunks == 1
    assert ex.ledger is shared
