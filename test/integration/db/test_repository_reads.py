"""DB-gated integration for the SP_022 retrieval reads (``get_chunk``, ``list_documents``,
``list_entities``) and the SP_023 graph/temporal reads (``get_links`` incoming, ``list_metrics``,
``get_claims_by_predicate``) against a real PostgresRepository.

These are pure SELECT paths (no LLM, no embeddings beyond a fixed vector). They back the
MCP retrieval + graph/temporal tools. Auto-skips unless ``DATABASE_URL`` is set (see
``test/conftest.py``)."""

from __future__ import annotations

from datetime import date

import pytest

from helixpay.contracts import Chunk, Claim, Document, Entity, Link, Repository

pytestmark = pytest.mark.db


def _doc(h: str, uri: str, as_of: date | None, raw: str = "body") -> Document:
    return Document(
        source_uri=uri, source_type="md", content_hash=h, as_of=as_of, raw_text=raw
    )


def test_repository_satisfies_extended_protocol(pg_repo):
    # The three new reads are part of the Repository contract now (SP_022).
    repo: Repository = pg_repo  # typed assignment — mypy + runtime conformance
    assert isinstance(repo, Repository)
    assert hasattr(repo, "get_chunk")
    assert hasattr(repo, "list_documents")
    assert hasattr(repo, "list_entities")


def test_get_chunk_roundtrips_full_text_and_misses_return_none(pg_repo):
    did = pg_repo.upsert_document(_doc("h-chunk", "data/c.md", date(2026, 1, 1)))
    body = "HelixPay closed Series B in March 2026. " * 20  # > snippet length
    [cid] = pg_repo.add_chunks(
        [Chunk(document_id=did, ordinal=0, text=body)], [[0.01] * 1024]
    )
    got = pg_repo.get_chunk(cid)
    assert got is not None
    assert got.id == cid and got.document_id == did
    assert got.text == body  # FULL untruncated text (this is what `fetch` returns)
    assert pg_repo.get_chunk(9_999_999) is None  # miss → None, no raise


def test_list_documents_orders_as_of_desc_nulls_last_and_keeps_raw_text(pg_repo):
    pg_repo.upsert_document(_doc("h-old", "data/old.md", date(2025, 1, 1)))
    pg_repo.upsert_document(_doc("h-new", "data/new.md", date(2026, 6, 1)))
    pg_repo.upsert_document(_doc("h-nul", "data/undated.md", None))
    docs = pg_repo.list_documents()
    uris = [d.source_uri for d in docs]
    assert uris == ["data/new.md", "data/old.md", "data/undated.md"]  # desc, nulls last
    # the repo read returns the HONEST full model (raw_text present); trimming is the
    # engine/wire layer's job, not the contract's (SP_022 review HIGH-3)
    assert all(d.raw_text is not None for d in docs)


def test_list_entities_filters_by_type_and_lists_all(pg_repo):
    pg_repo.upsert_entity(Entity(canonical_name="HelixPay Brasil", entity_type="other"))
    pg_repo.upsert_entity(Entity(canonical_name="HelixPay SEA", entity_type="other"))
    pg_repo.upsert_entity(Entity(canonical_name="Wei Chen", entity_type="person"))
    others = pg_repo.list_entities("other")
    assert [e.canonical_name for e in others] == ["HelixPay Brasil", "HelixPay SEA"]
    assert all(e.entity_type == "other" for e in others)
    assert len(pg_repo.list_entities()) == 3  # list-all
    assert pg_repo.list_entities("nonexistent") == []  # unknown type → [], no raise


# --------------------------------------------------------------------------- #
# SP_023 graph/temporal reads                                                 #
# --------------------------------------------------------------------------- #
def test_get_links_to_entity_id_returns_incoming_edges(pg_repo):
    a = pg_repo.upsert_entity(Entity(canonical_name="Maria", entity_type="person"))
    b = pg_repo.upsert_entity(Entity(canonical_name="Tan", entity_type="person"))
    c = pg_repo.upsert_entity(Entity(canonical_name="Bob", entity_type="person"))
    pg_repo.add_link(Link(from_entity_id=a, to_entity_id=b, link_type="reports_to"))  # a→b
    pg_repo.add_link(Link(from_entity_id=c, to_entity_id=b, link_type="reports_to"))  # c→b
    pg_repo.add_link(Link(from_entity_id=b, to_entity_id=a, link_type="owns"))        # b→a
    incoming = pg_repo.get_links(to_entity_id=b)  # who points AT b
    assert {ln.from_entity_id for ln in incoming} == {a, c}
    outgoing = pg_repo.get_links(from_entity_id=b)
    assert {ln.to_entity_id for ln in outgoing} == {a}
    # link_type + to_entity_id AND together
    typed = pg_repo.get_links(link_type="reports_to", to_entity_id=b)
    assert {ln.from_entity_id for ln in typed} == {a, c}


def test_list_metrics_roundtrips_vocab(pg_repo):
    pg_repo.upsert_metric("revenue", "Revenue", ["arr", "annual recurring revenue"])
    pg_repo.upsert_metric("runway", "Runway (months)", [])
    metrics = pg_repo.list_metrics()
    by_key = {m.canonical_key: m for m in metrics}
    assert [m.canonical_key for m in metrics] == ["revenue", "runway"]  # ordered
    assert by_key["revenue"].display_name == "Revenue"
    assert by_key["revenue"].aliases == ["arr", "annual recurring revenue"]
    assert by_key["runway"].aliases == []


def test_get_claims_by_predicate_canonicalizes_and_excludes_distinct(pg_repo):
    """Proves the SQL alias + period-strip match (the one thing the fake can't reproduce)."""
    pg_repo.upsert_metric("revenue", "Revenue", ["arr"])
    sea = pg_repo.upsert_entity(Entity(canonical_name="HelixPay SEA", entity_type="other"))
    bra = pg_repo.upsert_entity(Entity(canonical_name="HelixPay Brasil", entity_type="other"))

    def claim(subj, pred, val):
        pg_repo.add_claim(Claim(subject_entity_id=subj, predicate=pred, object_value=val,
                                as_of=date(2026, 3, 31)))

    claim(sea, "Q1 2026 revenue", "$9.4M")   # period-qualified → strips to "revenue"
    claim(bra, "revenue", "$4.8M")           # canonical
    claim(sea, "arr", "$30M")                # alias → "revenue"
    claim(sea, "revenue vs plan", "+5%")     # distinct suffix → NOT revenue
    claim(bra, "fy2026 ebitda", "$1.1M")     # glued token → must NOT over-strip to "ebitda"

    rows = pg_repo.get_claims_by_predicate("revenue")
    vals = {r.object_value for r in rows}
    assert vals == {"$9.4M", "$4.8M", "$30M"}  # the 3 revenue-family claims, across 2 subjects
    assert "+5%" not in vals  # distinct suffix excluded
    # the glued "fy2026 ebitda" is its own predicate, never matched by "revenue"…
    assert "$1.1M" not in vals
    # …and NOT over-stripped to "ebitda" (the `+`-separator regression, Stage-3 H1):
    assert pg_repo.get_claims_by_predicate("ebitda") == []

    # subject_id narrows to one subject (the get_timeline path)
    sea_rows = pg_repo.get_claims_by_predicate("revenue", subject_id=sea)
    assert {r.object_value for r in sea_rows} == {"$9.4M", "$30M"}


def test_get_claims_by_predicate_unknown_predicate_is_empty(pg_repo):
    eid = pg_repo.upsert_entity(Entity(canonical_name="X", entity_type="other"))
    pg_repo.add_claim(Claim(subject_entity_id=eid, predicate="revenue", object_value="$1"))
    assert pg_repo.get_claims_by_predicate("headcount") == []  # unknown → [], no raise
