"""Org-chart enrichment and entity-detail reads."""

from __future__ import annotations

from datetime import date

from helixpay.contracts import Claim, Entity, Link, OrgNode
from helixpay.query.graph import entity_detail, org_chart


def test_org_chart_enriches_roles_and_keeps_structure(repo):
    repo.add_entity(Entity(canonical_name="Wei Chen", entity_type="person", attributes={"role": "CEO"}))
    repo.add_entity(Entity(canonical_name="Priya Raman", entity_type="person", attributes={"role": "COO"}))
    repo.org_tree = OrgNode(
        entity_id=1, name="Wei Chen", children=[
            OrgNode(entity_id=2, name="Priya Raman", children=[], dotted_reports=[]),
        ], dotted_reports=[],
    )
    tree = org_chart(repo)
    assert tree["name"] == "Wei Chen"
    assert tree["role"] == "CEO"
    assert tree["children"][0]["name"] == "Priya Raman"
    assert tree["children"][0]["role"] == "COO"


def test_entity_detail_returns_claims_and_links(repo):
    eid = repo.add_entity(Entity(canonical_name="Wei Chen", entity_type="person"))
    repo.add_claim_row(Claim(subject_entity_id=eid, predicate="title", object_value="CEO", as_of=date(2026, 4, 15)))
    repo.links = [Link(from_entity_id=eid, to_entity_id=99, link_type="reports_to")]
    detail = entity_detail(repo, "Wei Chen")
    assert detail["entity"]["canonical_name"] == "Wei Chen"
    assert detail["aliases"] == []                       # Protocol friction (no get_aliases)
    assert any(c["predicate"] == "title" for c in detail["claims"])
    assert detail["links"][0]["link_type"] == "reports_to"


def test_entity_detail_unknown_name_is_empty(repo):
    detail = entity_detail(repo, "Nobody")
    assert detail == {"entity": {}, "aliases": [], "claims": [], "links": []}
