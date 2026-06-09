"""REST surface — thin pass-throughs to the injected ``QueryEngine``.

Every route returns the contract shape; ``/ask`` always carries a ``contradictions`` key
(surfaced, never hidden); ``/contradictions`` returns first-class rows. The engine is the
deterministic ``MockQueryEngine``, swapped in via ``set_engine`` (the production swap seam).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from helixpay.api.app import create_app
from helixpay.api.engine import MockQueryEngine, get_engine, set_engine


@pytest.fixture(autouse=True)
def _mock_engine():
    original = get_engine()
    set_engine(MockQueryEngine())
    yield
    set_engine(original)


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


def test_ask_returns_cited_answer_with_contradictions_surfaced(client):
    resp = client.post("/ask", json={"question": "What was Q1 revenue?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"]
    # Every claim is cited, each citation carries an as_of.
    assert body["citations"], "answer must be cited"
    assert all("source_uri" in c for c in body["citations"])
    assert any(c.get("as_of") for c in body["citations"])
    # Contradictions are present (key always exists) — here, surfaced and non-empty.
    assert "contradictions" in body
    assert body["contradictions"], "the planted Q1 conflict must surface"


def test_entity_returns_aliases_claims_links(client):
    resp = client.get("/entity/Maria Santos")
    assert resp.status_code == 200
    body = resp.json()
    assert body["entity"]["canonical_name"] == "Maria Santos"
    assert "aliases" in body and "claims" in body and "links" in body


def test_org_chart_returns_hierarchy_node(client):
    resp = client.get("/org-chart")
    assert resp.status_code == 200
    body = resp.json()
    assert "entity_id" in body and "children" in body
    assert body["children"][0]["reports_to"] == body["entity_id"]


def test_org_chart_accepts_as_of(client):
    resp = client.get("/org-chart", params={"as_of": "2025-01-31"})
    assert resp.status_code == 200
    assert resp.json()["as_of"] == "2025-01-31"


def test_org_chart_rejects_malformed_as_of_with_422(client):
    resp = client.get("/org-chart", params={"as_of": "not-a-date"})
    assert resp.status_code == 422  # client error, not an opaque 500
    assert "as_of" in resp.json()["detail"]


def test_contradictions_endpoint_returns_first_class_rows(client):
    resp = client.get("/contradictions")
    assert resp.status_code == 200
    rows = resp.json()
    assert isinstance(rows, list) and rows
    assert rows[0]["kind"] == "value_conflict"
