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


# --------------------------------------------------------------------------- #
# SP_009 provenance v2 — additive schema/repository surface.
# --------------------------------------------------------------------------- #
def _chunk(repo, h: str, text: str = "Q1 2026 Revenue: SGD 14.2M as of 2026-03-31") -> int:
    doc = repo.upsert_document(Document(source_uri="data/dash.html", source_type="html",
                                        content_hash=h, raw_text=text, as_of=date(2026, 3, 31)))
    return repo.add_chunks([Chunk(document_id=doc, ordinal=0, text=text)], [[0.1] * 1024])[0], doc


def test_apply_schema_is_idempotent(db_url):
    # The migration (incl. the new ALTER ... ADD COLUMN IF NOT EXISTS) re-runs clean.
    from helixpay.db.migrate import apply_schema

    n1 = apply_schema(db_url)
    n2 = apply_schema(db_url)
    assert n1 == n2 and n1 > 0


def test_add_claim_persists_evidence_and_offsets(pg_repo):
    chunk_id, _ = _chunk(pg_repo, "hash-ev")
    e = pg_repo.upsert_entity(Entity(canonical_name="Revenue", entity_type="metric"))
    cid = pg_repo.add_claim(Claim(
        subject_entity_id=e, predicate="revenue", object_value="SGD 14.2M",
        source_chunk_id=chunk_id, evidence="Revenue: SGD 14.2M", char_start=9, char_end=27,
    ))
    got = pg_repo.get_claims(e)
    assert len(got) == 1
    assert got[0].id == cid
    assert got[0].evidence == "Revenue: SGD 14.2M"
    assert (got[0].char_start, got[0].char_end) == (9, 27)


def test_add_claim_natural_key_unchanged_by_new_columns(pg_repo):
    # evidence/offsets are NOT part of the natural key: a re-extraction of the same
    # fact (different evidence) still dedupes to one row (first-write-wins).
    chunk_id, _ = _chunk(pg_repo, "hash-nk")
    e = pg_repo.upsert_entity(Entity(canonical_name="Revenue", entity_type="metric"))
    a = pg_repo.add_claim(Claim(subject_entity_id=e, predicate="revenue", object_value="14.2M",
                               source_chunk_id=chunk_id, evidence="first span"))
    b = pg_repo.add_claim(Claim(subject_entity_id=e, predicate="revenue", object_value="14.2M",
                               source_chunk_id=chunk_id, evidence="second span"))
    assert a == b
    rows = pg_repo.get_claims(e)
    assert len(rows) == 1 and rows[0].evidence == "first span"  # first write wins


def test_add_link_persists_document_id(pg_repo):
    chunk_id, doc = _chunk(pg_repo, "hash-link")
    a = pg_repo.upsert_entity(Entity(canonical_name="Alice", entity_type="person"))
    b = pg_repo.upsert_entity(Entity(canonical_name="Bob", entity_type="person"))
    pg_repo.add_link(Link(from_entity_id=a, to_entity_id=b, link_type="reports_to",
                          source_chunk_id=chunk_id, document_id=doc))
    links = pg_repo.get_links(from_entity_id=a)
    assert len(links) == 1 and links[0].document_id == doc


def test_get_links_filters_by_from_entity_and_type(pg_repo):
    a = pg_repo.upsert_entity(Entity(canonical_name="A", entity_type="person"))
    b = pg_repo.upsert_entity(Entity(canonical_name="B", entity_type="person"))
    c = pg_repo.upsert_entity(Entity(canonical_name="C", entity_type="person"))
    pg_repo.add_link(Link(from_entity_id=a, to_entity_id=b, link_type="reports_to"))
    pg_repo.add_link(Link(from_entity_id=a, to_entity_id=c, link_type="dotted_line_to"))
    pg_repo.add_link(Link(from_entity_id=b, to_entity_id=c, link_type="reports_to"))
    assert {l.to_entity_id for l in pg_repo.get_links(from_entity_id=a)} == {b, c}
    only_solid = pg_repo.get_links(link_type="reports_to", from_entity_id=a)
    assert len(only_solid) == 1 and only_solid[0].to_entity_id == b
    # old positional/keyword call still works (backward compat)
    assert len(pg_repo.get_links("reports_to")) == 2


def test_get_link_sources_returns_anchored_citation(pg_repo):
    chunk_id, doc = _chunk(pg_repo, "hash-ls")
    a = pg_repo.upsert_entity(Entity(canonical_name="Alice", entity_type="person"))
    b = pg_repo.upsert_entity(Entity(canonical_name="Bob", entity_type="person"))
    pg_repo.add_link(Link(from_entity_id=a, to_entity_id=b, link_type="reports_to",
                          source_chunk_id=chunk_id, document_id=doc, as_of=date(2026, 3, 31)))
    link_id = pg_repo.get_links(from_entity_id=a)[0].id
    cites = pg_repo.get_link_sources([link_id])
    assert len(cites) == 1
    assert cites[0].link_id == link_id          # anchored back to the link
    assert cites[0].source_uri == "data/dash.html"
    assert cites[0].as_of == date(2026, 3, 31)
    assert cites[0].snippet                      # chunk-text prefix


def test_get_link_sources_empty_input(pg_repo):
    assert pg_repo.get_link_sources([]) == []


def test_get_chunk_sources_one_citation_per_chunk(pg_repo):
    chunk_id, _ = _chunk(pg_repo, "hash-cs")
    cites = pg_repo.get_chunk_sources([chunk_id])
    assert len(cites) == 1
    assert cites[0].chunk_id == chunk_id
    assert cites[0].claim_id is None             # chunk-keyed, no claim join
    assert cites[0].source_uri == "data/dash.html"
    assert cites[0].snippet


def test_get_chunk_sources_empty_input(pg_repo):
    assert pg_repo.get_chunk_sources([]) == []


def test_known_content_hashes(pg_repo):
    assert pg_repo.known_content_hashes() == set()
    pg_repo.upsert_document(_doc("hash-1"))
    pg_repo.upsert_document(_doc("hash-2"))
    assert pg_repo.known_content_hashes() == {"hash-1", "hash-2"}


def test_link_pair_contradiction_dedups_regardless_of_order(pg_repo):
    a = pg_repo.upsert_entity(Entity(canonical_name="A", entity_type="person"))
    b = pg_repo.upsert_entity(Entity(canonical_name="B", entity_type="person"))
    c = pg_repo.upsert_entity(Entity(canonical_name="C", entity_type="person"))
    pg_repo.add_link(Link(from_entity_id=a, to_entity_id=b, link_type="reports_to"))
    pg_repo.add_link(Link(from_entity_id=a, to_entity_id=c, link_type="reports_to"))
    la = pg_repo.get_links(from_entity_id=a)[0].id
    lb = pg_repo.get_links(from_entity_id=a)[1].id
    pg_repo.add_contradiction(Contradiction(subject_entity_id=a, predicate="reports_to",
                                            link_a_id=la, link_b_id=lb, kind="source_disagreement"))
    pg_repo.add_contradiction(Contradiction(subject_entity_id=a, predicate="reports_to",
                                            link_a_id=lb, link_b_id=la, kind="source_disagreement"))
    rows = [c for c in pg_repo.get_contradictions(subject_id=a) if c.link_a_id is not None]
    assert len(rows) == 1
