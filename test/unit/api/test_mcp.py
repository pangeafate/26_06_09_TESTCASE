"""MCP server — six typed tools, thin pass-throughs, reachable over streamable-HTTP.

Two layers of assertion:
  * tool-logic level — ``list_tools`` / ``call_tool`` against the mock engine (verifies the
    pass-through and the guarded retrieval dispatch);
  * transport level — a real HTTP round-trip to the mounted ``/mcp`` endpoint proving the
    streamable-HTTP transport is live (stdio would not satisfy the live-URL requirement).
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from helixpay.api.app import create_app
from helixpay.api.engine import MockQueryEngine, get_engine, set_engine
from helixpay.mcp.server import build_mcp

EXPECTED_TOOLS = {"ask", "get_entity", "get_org_chart", "find_contradictions",
                  "get_sources", "search"}


@pytest.fixture(autouse=True)
def _mock_engine():
    original = get_engine()
    set_engine(MockQueryEngine())
    yield
    set_engine(original)


def _text(result) -> str:
    """call_tool returns list[TextContent] (or a (content, structured) tuple in some
    SDK builds); pull the first text payload either way."""
    content = result[0] if isinstance(result, tuple) else result
    return content[0].text


def test_all_six_tools_registered():
    mcp = build_mcp()
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert EXPECTED_TOOLS <= names


def test_ask_tool_passes_through_to_engine():
    mcp = build_mcp()
    payload = json.loads(_text(asyncio.run(mcp.call_tool("ask", {"question": "Q1 revenue?"}))))
    assert payload["answer"]
    assert payload["citations"]
    assert payload["contradictions"], "contradictions surfaced through the MCP tool"


def test_get_sources_and_search_retrieval_tools():
    mcp = build_mcp()
    sources = json.loads(_text(asyncio.run(mcp.call_tool("get_sources", {}))))
    assert sources["available"] is True and sources["results"]
    found = json.loads(_text(asyncio.run(mcp.call_tool("search", {"query": "revenue", "k": 1}))))
    assert found["available"] is True and len(found["results"]) == 1


def test_retrieval_degrades_when_engine_lacks_surface():
    """A Protocol-only engine (no get_sources/search) must not break the tools."""

    class CoreOnly:  # implements only the frozen QueryEngine surface
        def ask(self, question):
            return MockQueryEngine().ask(question)

        def get_entity(self, name):
            return MockQueryEngine().get_entity(name)

        def get_org_chart(self, as_of=None):
            return MockQueryEngine().get_org_chart(as_of)

        def find_contradictions(self, topic=None):
            return MockQueryEngine().find_contradictions(topic)

    set_engine(CoreOnly())
    mcp = build_mcp()
    sources = json.loads(_text(asyncio.run(mcp.call_tool("get_sources", {}))))
    assert sources["available"] is False and sources["results"] == []


def _post_mcp(client: TestClient, body: dict):
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    return client.post("/mcp/", json=body, headers=headers)


def _sse_json(resp) -> dict:
    """Parse the single JSON-RPC result frame from a streamable-HTTP SSE response. Asserts
    exactly one ``data:`` frame so the test fails loudly if the SDK ever batches frames
    (rather than silently picking the wrong one)."""
    frames = [
        json.loads(line[len("data:"):].strip())
        for line in resp.text.splitlines()
        if line.startswith("data:")
    ]
    assert len(frames) == 1, f"expected one SSE data frame, got {len(frames)}: {resp.text!r}"
    return frames[0]


def test_mcp_reachable_over_streamable_http():
    """Initialize + tools/call over HTTP — proves the streamable-HTTP transport is live."""
    with TestClient(create_app()) as client:
        init = _post_mcp(client, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "test", "version": "1"}},
        })
        assert init.status_code == 200
        assert "text/event-stream" in init.headers.get("content-type", "")

        called = _post_mcp(client, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "ask", "arguments": {"question": "Q1 revenue?"}},
        })
        assert called.status_code == 200
        result = _sse_json(called)["result"]
        inner = json.loads(result["content"][0]["text"])
        assert inner["answer"]
        assert inner["contradictions"]
