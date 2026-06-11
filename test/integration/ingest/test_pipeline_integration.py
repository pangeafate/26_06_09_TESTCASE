"""DB-gated integration: the pipeline against a real PostgresRepository (pgvector).

No API keys needed — the extractor is a deterministic stub and the embedder returns
fixed 1024-d vectors, so this exercises the *real* SQL paths (upsert_document, add_chunks
into pgvector, resolve_entity, canonical_predicate against a seeded metric_vocab, add_claim,
add_contradiction, supersede_claim, get_claims, get_sources) without an LLM.

Auto-skips when ``DATABASE_URL`` is unset (``db`` mark + conftest). The ``pg_repo`` fixture
TRUNCATEs ``metric_vocab``, so each test seeds the vocab + entities it needs — otherwise
``canonical_predicate`` would silently no-op and the contradiction would group for the wrong
reason (Stage-3 H5).
"""

from __future__ import annotations

from datetime import date

import pytest

from helixpay.contracts import Chunk, Document, Entity, Link
from helixpay.ingest.extract.schemas import ClaimOut, ExtractionOut, RelationOut
from helixpay.ingest.pipeline import run
from helixpay.seed.metric_vocab import METRIC_VOCAB

pytestmark = pytest.mark.db


class _Connector:
    source_type = "md"

    def __init__(self, doc, chunks):
        self._doc, self._chunks = doc, chunks

    def load(self, path):
        return self._doc, list(self._chunks)


class _Scripted:
    def __init__(self, by_text):
        self.by_text = by_text

    def extract(self, chunk, ctx):
        return self.by_text.get(chunk.text, ExtractionOut())


class _Embedder:
    def embed(self, texts):
        return [[0.01] * 1024 for _ in texts]


def _discover(*pairs):
    return lambda root: list(pairs)


def _seed(repo):
    for key, display, aliases in METRIC_VOCAB:
        repo.upsert_metric(key, display, aliases)
    return repo.upsert_entity(Entity(canonical_name="HelixPay", entity_type="other", seeded=True))


def test_cross_source_disagreement_persists_a_contradiction(pg_repo):
    helix = _seed(pg_repo)
    d1 = Document(source_uri="data/dashboards/april.html", source_type="html", content_hash="h1", as_of=date(2026, 3, 31))
    d2 = Document(source_uri="data/board-deck-q1-2026.pdf", source_type="pdf", content_hash="h2", as_of=date(2026, 3, 31))
    extr = _Scripted({
        "a": ExtractionOut(claims=[ClaimOut(subject="HelixPay", subject_type="other", predicate="revenue", object_value="SGD 14.2M", as_of="2026-03-31")]),
        "b": ExtractionOut(claims=[ClaimOut(subject="HelixPay", subject_type="other", predicate="Q1 revenue", object_value="SGD 13.9M", as_of="2026-03-31")]),
    })
    disc = _discover((_Connector(d1, [Chunk(ordinal=0, text="a")]), "p1"),
                     (_Connector(d2, [Chunk(ordinal=0, text="b")]), "p2"))

    report = run("data", pg_repo, discover=disc, embedder=_Embedder(), extractor=extr)

    assert report.contradictions == 1
    contradictions = pg_repo.get_contradictions(helix)
    assert len(contradictions) == 1
    assert contradictions[0].kind == "source_disagreement"
    claims = pg_repo.get_claims(helix, "revenue")
    assert len(claims) == 2  # both coexist — never collapsed

    # idempotent: a second identical run adds no rows
    report2 = run("data", pg_repo, discover=disc, embedder=_Embedder(), extractor=extr)
    assert report2.contradictions == 0
    assert len(pg_repo.get_contradictions(helix)) == 1
    assert len(pg_repo.get_claims(helix, "revenue")) == 2


def test_same_source_newer_value_supersedes_without_deleting(pg_repo):
    helix = _seed(pg_repo)
    d1 = Document(source_uri="data/x.md", source_type="md", content_hash="h1", as_of=date(2026, 3, 31))
    d2 = Document(source_uri="data/x.md", source_type="md", content_hash="h2", as_of=date(2026, 4, 30))
    e1 = _Scripted({"a": ExtractionOut(claims=[ClaimOut(subject="HelixPay", subject_type="other", predicate="revenue", object_value="SGD 13.9M", as_of="2026-03-31")])})
    e2 = _Scripted({"b": ExtractionOut(claims=[ClaimOut(subject="HelixPay", subject_type="other", predicate="revenue", object_value="SGD 14.2M", as_of="2026-04-30")])})

    run("data", pg_repo, discover=_discover((_Connector(d1, [Chunk(ordinal=0, text="a")]), "p")), embedder=_Embedder(), extractor=e1)
    run("data", pg_repo, discover=_discover((_Connector(d2, [Chunk(ordinal=0, text="b")]), "p")), embedder=_Embedder(), extractor=e2)

    claims = pg_repo.get_claims(helix, "revenue")
    assert len(claims) == 2  # nothing deleted
    old = next(c for c in claims if c.object_value == "SGD 13.9M")
    new = next(c for c in claims if c.object_value == "SGD 14.2M")
    assert old.superseded_by == new.id and old.valid_to == date(2026, 4, 30)
    assert pg_repo.get_contradictions(helix) == []  # same source → supersede, not contradiction


# --------------------------------------------------------------------------- #
# SP_011 — provenance produced on the write path, exercised through real SQL
# --------------------------------------------------------------------------- #
def test_evidence_and_offsets_persist_through_add_claim(pg_repo):
    helix = _seed(pg_repo)
    text = "Q1 closed at SGD 14.2M against a 16M plan."
    doc = Document(source_uri="data/board.md", source_type="md", content_hash="ev1", as_of=date(2026, 3, 31))
    extr = _Scripted({text: ExtractionOut(claims=[ClaimOut(
        subject="HelixPay", subject_type="other", predicate="revenue", object_value="SGD 14.2M",
        as_of="2026-03-31", evidence="SGD 14.2M against a 16M plan")])})
    run("data", pg_repo, discover=_discover((_Connector(doc, [Chunk(ordinal=0, text=text)]), "p")),
        embedder=_Embedder(), extractor=extr)
    claims = pg_repo.get_claims(helix, "revenue")
    assert len(claims) == 1
    c = claims[0]
    assert c.evidence == "SGD 14.2M against a 16M plan"
    assert c.char_start is not None and text[c.char_start:c.char_end] == "SGD 14.2M against a 16M plan"


def test_seeded_undated_edge_and_extracted_edge_coexist_with_provenance(pg_repo):
    # SP_011 corroborate fix: an UNDATED seeded reports_to (as run_seed now emits) and the
    # cited extracted twin from org-chart.md (export-dated) must NOT collide on the links
    # natural key — so the extracted edge survives and supplies the source_chunk_id.
    sara = pg_repo.upsert_entity(Entity(canonical_name="Sara Wijaya", entity_type="person", seeded=True))
    daniel = pg_repo.upsert_entity(Entity(canonical_name="Daniel Tan", entity_type="person", seeded=True))
    pg_repo.add_link(Link(from_entity_id=sara, to_entity_id=daniel, link_type="reports_to", as_of=None, confidence=1.0))
    doc = Document(source_uri="data/org-chart.md", source_type="md", content_hash="oc1", as_of=date(2026, 4, 15))
    extr = _Scripted({"oc": ExtractionOut(relations=[
        RelationOut(from_entity="Sara Wijaya", to_entity="Daniel Tan", link_type="reports_to")])})
    run("data", pg_repo, discover=_discover((_Connector(doc, [Chunk(ordinal=0, text="oc")]), "p")),
        embedder=_Embedder(), extractor=extr)
    links = pg_repo.get_links("reports_to", sara)
    assert len(links) == 2  # seeded (undated) + extracted (dated) coexist — no dedup-away
    cited = [l for l in links if l.source_chunk_id is not None]
    assert len(cited) == 1 and cited[0].document_id is not None  # the no-provenance hole is closed


def test_link_contradiction_surfaces_as_a_first_class_row(pg_repo):
    # two sources give the SAME subject two DIFFERENT solid-line managers → a graph
    # contradiction pairing the two links (not a synthetic corpus fact — exercised here on
    # stub edges; the real corpus is consistent and yields zero).
    sara = pg_repo.upsert_entity(Entity(canonical_name="Sara Wijaya", entity_type="person", seeded=True))
    pg_repo.upsert_entity(Entity(canonical_name="Daniel Tan", entity_type="person", seeded=True))
    pg_repo.upsert_entity(Entity(canonical_name="Arjun Kapoor", entity_type="person", seeded=True))
    d1 = Document(source_uri="data/a.md", source_type="md", content_hash="la1", as_of=date(2026, 4, 15))
    d2 = Document(source_uri="data/b.md", source_type="md", content_hash="lb1", as_of=date(2026, 4, 15))
    extr = _Scripted({
        "a": ExtractionOut(relations=[RelationOut(from_entity="Sara Wijaya", to_entity="Daniel Tan", link_type="reports_to")]),
        "b": ExtractionOut(relations=[RelationOut(from_entity="Sara Wijaya", to_entity="Arjun Kapoor", link_type="reports_to")]),
    })
    disc = _discover((_Connector(d1, [Chunk(ordinal=0, text="a")]), "p1"),
                     (_Connector(d2, [Chunk(ordinal=0, text="b")]), "p2"))
    report = run("data", pg_repo, discover=disc, embedder=_Embedder(), extractor=extr)
    assert report.contradictions == 1
    contras = [c for c in pg_repo.get_contradictions(sara) if c.link_a_id is not None]
    assert len(contras) == 1
    assert contras[0].link_a_id is not None and contras[0].link_b_id is not None
    assert contras[0].kind == "source_disagreement"  # different documents

    # idempotent: re-run writes no new contradiction (DB partial unique index on the link pair)
    report2 = run("data", pg_repo, discover=disc, embedder=_Embedder(), extractor=extr)
    assert report2.contradictions == 0
    assert len([c for c in pg_repo.get_contradictions(sara) if c.link_a_id is not None]) == 1
