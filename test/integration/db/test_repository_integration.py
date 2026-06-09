"""DB-gated integration: schema applies, writes are idempotent, resolution is
roster-first, supersession keeps history, and the org subtree resolves.

Auto-skipped unless DATABASE_URL is set (see test/conftest.py)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from helixpay.contracts import Chunk, Claim, Contradiction, Document, Entity, Link
from helixpay.seed.run_seed import seed_all

pytestmark = pytest.mark.db

DATA = Path(__file__).resolve().parents[3] / "data"


def _doc(h: str) -> Document:
    return Document(source_uri="data/x.md", source_type="md", content_hash=h, raw_text="x")


def test_upsert_document_idempotent_on_content_hash(pg_repo):
    id1 = pg_repo.upsert_document(_doc("hash-A"))
    id2 = pg_repo.upsert_document(_doc("hash-A"))
    assert id1 == id2
    with pg_repo.conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM documents WHERE content_hash = 'hash-A'")
        assert cur.fetchone()["n"] == 1


def test_add_claim_idempotent_on_natural_key(pg_repo):
    e = pg_repo.upsert_entity(Entity(canonical_name="Revenue", entity_type="metric"))
    c = Claim(subject_entity_id=e, predicate="revenue", object_value="SGD 14.2M")
    first = pg_repo.add_claim(c)
    again = pg_repo.add_claim(c)
    assert first == again


def test_supersede_keeps_old_claim(pg_repo):
    e = pg_repo.upsert_entity(Entity(canonical_name="Revenue", entity_type="metric"))
    old = pg_repo.add_claim(Claim(subject_entity_id=e, predicate="revenue", object_value="13.9M", source_chunk_id=None))
    new = pg_repo.add_claim(Claim(subject_entity_id=e, predicate="revenue", object_value="14.2M", source_chunk_id=None))
    pg_repo.supersede_claim(old, new, valid_to=date(2026, 3, 31))
    with pg_repo.conn.cursor() as cur:
        cur.execute("SELECT superseded_by, valid_to FROM claims WHERE id = %s", (old,))
        row = cur.fetchone()
    assert row["superseded_by"] == new and row["valid_to"] == date(2026, 3, 31)


def test_canonical_predicate_via_db(pg_repo):
    pg_repo.upsert_metric("arr", "Annual Recurring Revenue", ["arr", "annual recurring revenue"])
    assert pg_repo.canonical_predicate("Annual Recurring Revenue") == "arr"
    assert pg_repo.canonical_predicate("unknown_metric") == "unknown_metric"  # never raises


def test_seed_is_idempotent_and_resolves_name_traps(pg_repo):
    s1 = seed_all(pg_repo, DATA, with_fixture=True)
    s2 = seed_all(pg_repo, DATA, with_fixture=True)
    assert s1["entities"] == s2["entities"]  # second run adds no new entities

    santos = pg_repo.resolve_entity("Maria Santos", entity_type="person")
    silva = pg_repo.resolve_entity("Maria Silva", entity_type="person")
    assert santos is not None and silva is not None and santos.id != silva.id
    assert santos.seeded is True
    # a bare ambiguous first name resolves to None, never a silent pick
    assert pg_repo.resolve_entity("Maria", entity_type="person") is None
    # alias resolution
    hpb = pg_repo.resolve_entity("HPB")
    assert hpb is not None and hpb.canonical_name == "HelixPay Brasil"


def test_org_subtree_root_is_ceo(pg_repo):
    seed_all(pg_repo, DATA, with_fixture=False)
    tree = pg_repo.get_org_subtree()
    assert tree["name"] == "Wei Chen"
    # CEO has direct reports incl. the COO
    child_names = {c["name"] for c in tree["children"]}
    assert "Priya Raman" in child_names


def test_add_chunks_idempotent_on_document_ordinal(pg_repo):
    doc = pg_repo.upsert_document(_doc("hash-chunks"))
    ids1 = pg_repo.add_chunks([Chunk(document_id=doc, ordinal=0, text="hello")], [[0.1] * 1024])
    ids2 = pg_repo.add_chunks([Chunk(document_id=doc, ordinal=0, text="hello")], [[0.1] * 1024])
    assert ids1 == ids2
    with pg_repo.conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM chunks WHERE document_id = %s", (doc,))
        assert cur.fetchone()["n"] == 1


def test_resolve_entity_context_disambiguates_shared_alias(pg_repo):
    # Two distinct people sharing the alias "Maria" — the Agent-2 disambiguation case.
    santos = pg_repo.upsert_entity(Entity(canonical_name="Maria Santos", entity_type="person",
                                          attributes={"department": "Customer Success"}, seeded=True))
    silva = pg_repo.upsert_entity(Entity(canonical_name="Maria Silva", entity_type="person",
                                         attributes={"department": "Sales"}, seeded=True))
    pg_repo.add_alias(santos, "Maria")
    pg_repo.add_alias(silva, "Maria")
    # bare ambiguous alias → None (never a silent pick)
    assert pg_repo.resolve_entity("Maria", entity_type="person") is None
    # resolving context picks exactly one
    got = pg_repo.resolve_entity("Maria", entity_type="person", context={"department": "Sales"})
    assert got is not None and got.id == silva
    got2 = pg_repo.resolve_entity("Maria", entity_type="person", context={"department": "Customer Success"})
    assert got2 is not None and got2.id == santos


def test_contradiction_pair_dedups_regardless_of_order(pg_repo):
    e = pg_repo.upsert_entity(Entity(canonical_name="Revenue", entity_type="metric"))
    a = pg_repo.add_claim(Claim(subject_entity_id=e, predicate="revenue", object_value="14.2M"))
    b = pg_repo.add_claim(Claim(subject_entity_id=e, predicate="revenue", object_value="13.9M"))
    pg_repo.add_contradiction(Contradiction(subject_entity_id=e, predicate="revenue", claim_a_id=a, claim_b_id=b, kind="value_conflict"))
    pg_repo.add_contradiction(Contradiction(subject_entity_id=e, predicate="revenue", claim_a_id=b, claim_b_id=a, kind="value_conflict"))
    assert len(pg_repo.get_contradictions(subject_id=e)) == 1


def test_org_subtree_as_of_filters_reporting_lines(pg_repo):
    seed_all(pg_repo, DATA, with_fixture=False)
    # a date before the org-chart export has no valid reporting lines → empty root
    early = pg_repo.get_org_subtree(as_of=date(2026, 1, 1))
    assert early["children"] == []
    # at/after the export date the tree is populated
    current = pg_repo.get_org_subtree(as_of=date(2026, 4, 15))
    assert current["name"] == "Wei Chen" and current["children"]


def test_fixture_contradiction_is_queryable(pg_repo):
    seed_all(pg_repo, DATA, with_fixture=True)
    contradictions = pg_repo.get_contradictions()
    assert any(c.kind == "value_conflict" and c.predicate == "revenue" for c in contradictions)
    # both sides cite a source with an as_of
    cc = next(c for c in contradictions if c.predicate == "revenue")
    cites = pg_repo.get_sources([cc.claim_a_id, cc.claim_b_id])
    assert len(cites) == 2
    assert all(cite.source_uri and cite.as_of for cite in cites)
