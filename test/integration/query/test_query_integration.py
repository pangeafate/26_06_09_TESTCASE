"""QueryEngine against the REAL seeded fixture DB (hybrid retrieval, graph, and
contradiction surfacing run for real; only the LLM/embedding seams are stubbed —
we never make paid API calls in the suite).

Auto-skips unless DATABASE_URL is set (see test/conftest.py). The fake embedder
returns [0.01]*1024 to match the fixture chunk embeddings (avoids an undefined
zero-vector cosine — review code-M4); contradiction surfacing is asserted via the
structured path, not semantic rank.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from helixpay.config import EMBEDDING_DIM
from helixpay.query import HelixQueryEngine
from helixpay.seed.run_seed import seed_all

pytestmark = pytest.mark.db

DATA = Path(__file__).resolve().parents[3] / "data"


class _FakeEmbedder:
    def embed_query(self, text: str) -> list[float]:
        return [0.01] * EMBEDDING_DIM


class _FakeSynthesizer:
    def __init__(self, response: dict) -> None:
        self.response = response

    def synthesize(self, prompt: str, *, schema: dict) -> dict:
        return self.response


@pytest.fixture
def seeded_repo(pg_repo):
    seed_all(pg_repo, DATA, with_fixture=True)  # roster + metric_vocab + planted conflict
    return pg_repo


def test_ask_surfaces_planted_revenue_contradiction(seeded_repo):
    synth = _FakeSynthesizer({
        "sentences": [
            {"text": "The dashboard reports SGD 14.2M.", "cites": ["C1"]},
            {"text": "The board deck reports SGD 13.9M.", "cites": ["C2"]},
            {"text": "The two sources disagree.", "cites": ["C1", "C2"]},
        ],
        "confidence": 0.7,
    })
    engine = HelixQueryEngine(seeded_repo, _FakeEmbedder(), synth, k=8)
    bundle = engine.ask("What was HelixPay's Q1 2026 revenue?")

    assert len(bundle.contradictions) >= 1
    c = bundle.contradictions[0]
    assert c.claim_a_id is not None and c.claim_b_id is not None   # both sides
    # both conflicting claims cited, each with a source + as_of
    assert len(bundle.citations) == 2
    assert all(cit.source_uri and cit.as_of for cit in bundle.citations)
    assert bundle.as_of_coverage["latest"] == "2026-03-31"


def test_find_contradictions_revenue(seeded_repo):
    engine = HelixQueryEngine(seeded_repo, _FakeEmbedder(), _FakeSynthesizer({"sentences": []}), k=8)
    found = engine.find_contradictions("revenue")
    assert any(c.predicate == "revenue" and c.kind == "value_conflict" for c in found)


def test_get_org_chart_root_is_ceo(seeded_repo):
    engine = HelixQueryEngine(seeded_repo, _FakeEmbedder(), _FakeSynthesizer({"sentences": []}), k=8)
    tree = engine.get_org_chart()
    assert tree["name"] == "Wei Chen"
    assert any(child["name"] == "Priya Raman" for child in tree["children"])


def test_get_org_chart_as_of_before_roster_is_empty(seeded_repo):
    engine = HelixQueryEngine(seeded_repo, _FakeEmbedder(), _FakeSynthesizer({"sentences": []}), k=8)
    early = engine.get_org_chart(as_of=date(2026, 1, 1))
    assert early["children"] == []


def test_get_entity_returns_claims(seeded_repo):
    engine = HelixQueryEngine(seeded_repo, _FakeEmbedder(), _FakeSynthesizer({"sentences": []}), k=8)
    detail = engine.get_entity("Revenue")
    assert detail["entity"].get("canonical_name") == "Revenue"
    assert any(c["predicate"] == "revenue" for c in detail["claims"])


class _RaisingSynthesizer:
    """Models the external-model boundary failing mid-answer."""

    def synthesize(self, prompt: str, *, schema: dict) -> dict:
        raise RuntimeError("synthesis backend unavailable")


def test_ask_degrades_when_synthesis_raises(seeded_repo):
    # SP_030: the real-path synthesis-failure branch (engine.ask except handler) must
    # degrade — return a bundle, never leak the prompt or crash — and the structured
    # contradiction path (independent of the synth) still surfaces the planted conflict.
    engine = HelixQueryEngine(seeded_repo, _FakeEmbedder(), _RaisingSynthesizer(), k=8)
    bundle = engine.ask("What was HelixPay's Q1 2026 revenue?")
    assert bundle is not None
    assert bundle.contradictions  # structured path is synth-independent
    assert "synthesis backend unavailable" not in (bundle.answer or "")


def test_search_then_fetch_real_path(seeded_repo):
    # Exercises the real hybrid-retrieval search + chunk fetch path end-to-end (the
    # serving methods previously covered only via FakeRepository slices).
    engine = HelixQueryEngine(seeded_repo, _FakeEmbedder(), _FakeSynthesizer({"sentences": []}), k=8)
    hits = engine.search("revenue", k=3)
    assert hits and all("id" in h for h in hits)
    fetched = engine.fetch(str(hits[0]["id"]))
    assert fetched["metadata"]["found"] is True and fetched["text"]
