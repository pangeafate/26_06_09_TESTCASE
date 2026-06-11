"""DB-gated integration for the SP_022 retrieval reads: ``get_chunk``,
``list_documents``, ``list_entities`` against a real PostgresRepository.

These are pure SELECT paths (no LLM, no embeddings beyond a fixed vector). They back the
MCP ``fetch`` / ``get_sources`` / ``list_entities`` tools. Auto-skips unless ``DATABASE_URL``
is set (see ``test/conftest.py``)."""

from __future__ import annotations

from datetime import date

import pytest

from helixpay.contracts import Chunk, Document, Entity, Repository

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
