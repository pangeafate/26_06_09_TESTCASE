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
