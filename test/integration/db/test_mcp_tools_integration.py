"""MCP tool dispatch against the REAL engine + repo (SP_030 Item 3).

``test/unit/api/test_mcp.py`` already drives all 12 tools via ``build_mcp`` +
``call_tool`` and asserts the ``{available:false}`` degrade — but only against
``MockQueryEngine`` (canned data). Nothing exercises the real dispatch path
``mcp tool → _retrieval/get_engine() → HelixQueryEngine → PostgresRepository``.
This fills exactly that gap: it ``set_engine``s a real ``HelixQueryEngine`` over a
seeded Postgres fixture and drives the tools end-to-end, so a regression in the
real SQL, the engine↔repo wiring, or the tool dispatch is caught here.

``db``-marked → auto-skips without ``DATABASE_URL`` (runs in CI, where SP_030
provisions pgvector). Only the LLM/embedding seams are stubbed — no paid calls.
The ``{available:false}`` degrade branch is owned by
``test/unit/api/test_mcp.py::test_retrieval_degrades_when_engine_lacks_surface`` —
it is intentionally NOT re-tested here.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from helixpay.api.engine import get_engine, set_engine
from helixpay.config import EMBEDDING_DIM
from helixpay.mcp.server import build_mcp
from helixpay.query import HelixQueryEngine
from helixpay.seed.run_seed import seed_all

pytestmark = pytest.mark.db

# test/integration/db/<file> → parents[2] = test/, .parent = project root → data/.
# (Equivalent to test_query_integration.py's parents[3]/"data" from one level deeper.)
DATA = Path(__file__).resolve().parents[2].parent / "data"


class _FakeEmbedder:
    # [0.01]*dim matches the fixture chunk embeddings (avoids an undefined
    # zero-vector cosine) — mirrors test_query_integration.py.
    def embed_query(self, text: str) -> list[float]:
        return [0.01] * EMBEDDING_DIM


class _FakeSynthesizer:
    def __init__(self, response: dict) -> None:
        self.response = response

    def synthesize(self, prompt: str, *, schema: dict) -> dict:
        return self.response


def _text(result) -> str:
    content = result[0] if isinstance(result, tuple) else result
    return content[0].text


def _call(mcp, name: str, args: dict) -> dict:
    return json.loads(_text(asyncio.run(mcp.call_tool(name, args))))


@pytest.fixture
def seeded_repo(pg_repo):
    seed_all(pg_repo, DATA, with_fixture=True)  # roster + metric_vocab + planted conflict
    return pg_repo


@pytest.fixture
def mcp_real(seeded_repo):
    """Point the MCP global at a real engine over the seeded repo; restore after."""
    synth = _FakeSynthesizer(
        {
            "sentences": [
                {"text": "The dashboard reports SGD 14.2M.", "cites": ["C1"]},
                {"text": "The board deck reports SGD 13.9M.", "cites": ["C2"]},
                {"text": "The two sources disagree.", "cites": ["C1", "C2"]},
            ],
            "confidence": 0.7,
        }
    )
    original = get_engine()
    set_engine(HelixQueryEngine(seeded_repo, _FakeEmbedder(), synth, k=8))
    try:
        yield build_mcp()
    finally:
        set_engine(original)


# --- direct pass-through tools (real engine over real repo) ------------------- #


def test_ask_tool_surfaces_contradiction_through_real_engine(mcp_real):
    payload = _call(mcp_real, "ask", {"question": "What was HelixPay's Q1 2026 revenue?"})
    assert payload["answer"]
    assert len(payload["citations"]) == 2
    assert all(c["source_uri"] and c["as_of"] for c in payload["citations"])
    assert payload["contradictions"], "planted revenue conflict surfaced via the MCP tool"


def test_get_org_chart_tool_returns_seeded_root(mcp_real):
    tree = _call(mcp_real, "get_org_chart", {})
    assert tree["name"] == "Wei Chen"
    assert any(child["name"] == "Priya Raman" for child in tree["children"])


def test_get_entity_tool_returns_seeded_claims(mcp_real):
    detail = _call(mcp_real, "get_entity", {"name": "Revenue"})
    assert detail["entity"].get("canonical_name") == "Revenue"
    assert any(c["predicate"] == "revenue" for c in detail["claims"])


def test_find_contradictions_tool_finds_revenue_conflict(mcp_real):
    raw = _call(mcp_real, "find_contradictions", {"topic": "revenue"})
    # The tool returns a bare list; FastMCP must wrap a non-object return under a single
    # object key (structured content must be an object). Unwrap to the contained list
    # regardless of the key name; use .get() so a shape surprise is a clean assert, not a crash.
    if isinstance(raw, dict):
        lists = [v for v in raw.values() if isinstance(v, list)]
        raw = lists[0] if lists else [raw]
    items = [c for c in raw if isinstance(c, dict)]
    assert any(
        c.get("predicate") == "revenue" and c.get("kind") == "value_conflict" for c in items
    )


# --- the 8 optional retrieval tools: real engine → available:true ------------- #


def test_get_sources_tool_available_with_results(mcp_real):
    out = _call(mcp_real, "get_sources", {})
    assert out["available"] is True and out["results"]


def test_search_tool_available_and_fetch_roundtrips(mcp_real):
    found = _call(mcp_real, "search", {"query": "revenue", "k": 3})
    assert found["available"] is True and found["results"]
    chunk_id = found["results"][0]["id"]
    fetched = _call(mcp_real, "fetch", {"id": str(chunk_id)})
    assert fetched["available"] is True


def test_list_entities_tool_available(mcp_real):
    out = _call(mcp_real, "list_entities", {"entity_type": "other"})
    assert out["available"] is True and out["results"]


def test_list_metrics_tool_available(mcp_real):
    out = _call(mcp_real, "list_metrics", {})
    assert out["available"] is True and out["results"]


def test_get_claims_by_predicate_tool_available(mcp_real):
    out = _call(mcp_real, "get_claims_by_predicate", {"predicate": "revenue"})
    assert out["available"] is True and out["results"]


def test_get_timeline_tool_available(mcp_real):
    out = _call(mcp_real, "get_timeline", {"entity": "Revenue", "predicate": "revenue"})
    assert out["available"] is True


def test_get_relationships_tool_available(mcp_real):
    out = _call(mcp_real, "get_relationships", {"entity": "Wei Chen"})
    # Wei Chen is the seeded org root — has incoming reports_to edges, so the real
    # engine must return a populated relationships payload, not just available:true.
    assert out["available"] is True and out["results"]
