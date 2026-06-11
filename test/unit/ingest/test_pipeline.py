"""End-to-end ingestion pipeline, fully injected (no Agent 1, no DB, no API keys).

A reasonably complete in-memory ``FakeRepo`` mirrors the idempotent-upsert semantics of
``PostgresRepository`` so the pipeline's wiring, idempotency, supersession, and
contradiction sweep are all exercised without a database.
"""

from __future__ import annotations

from datetime import date

from helixpay.contracts import Chunk, Citation, Claim, Contradiction, Document, Entity, Link
from helixpay.ingest.extract.schemas import ClaimOut, ExtractionOut, RelationOut
from helixpay.ingest.pipeline import run
from helixpay.seed.metric_vocab import canonical_key


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #
class FakeRepo:
    def __init__(self) -> None:
        self.documents: dict[str, int] = {}
        self.doc_uri: dict[int, str] = {}
        self.chunks: list[Chunk] = []
        self.chunk_doc: dict[int, int] = {}
        self.entities: list[Entity] = []
        self.claims: list[Claim] = []
        self.links: list[Link] = []
        self.contradictions: list[Contradiction] = []
        self.add_chunks_seen: list[Chunk] = []
        self._next = {"doc": 1, "chunk": 1, "entity": 1, "claim": 1, "link": 1}

    def seed(self, name, etype):
        e = Entity(id=self._next["entity"], canonical_name=name, entity_type=etype, seeded=True)
        self.entities.append(e)
        self._next["entity"] += 1
        return e.id

    def upsert_document(self, doc: Document) -> int:
        if doc.content_hash in self.documents:
            return self.documents[doc.content_hash]
        did = self._next["doc"]; self._next["doc"] += 1
        self.documents[doc.content_hash] = did
        self.doc_uri[did] = doc.source_uri
        return did

    def add_chunks(self, chunks, embeddings):
        assert len(chunks) == len(embeddings)
        ids = []
        for ch in chunks:
            assert ch.document_id is not None, "chunk.document_id must be set before add_chunks"
            self.add_chunks_seen.append(ch)
            existing = next((c for c in self.chunks if c.document_id == ch.document_id and c.ordinal == ch.ordinal), None)
            if existing is not None:
                ids.append(existing.id); continue
            cid = self._next["chunk"]; self._next["chunk"] += 1
            stored = ch.model_copy(update={"id": cid})
            self.chunks.append(stored); self.chunk_doc[cid] = ch.document_id
            ids.append(cid)
        return ids

    def upsert_entity(self, e: Entity) -> int:
        for ex in self.entities:
            if ex.canonical_name == e.canonical_name and ex.entity_type == e.entity_type:
                return ex.id
        new = Entity(id=self._next["entity"], canonical_name=e.canonical_name,
                     entity_type=e.entity_type, attributes=e.attributes, seeded=e.seeded)
        self.entities.append(new); self._next["entity"] += 1
        return new.id

    def resolve_entity(self, name, entity_type=None, context=None):
        nl = name.strip().lower()
        cands = [e for e in self.entities if e.canonical_name.lower() == nl
                 and (entity_type is None or e.entity_type == entity_type)]
        return cands[0] if len(cands) == 1 else None

    def canonical_predicate(self, raw: str) -> str:
        return canonical_key(raw)

    def add_claim(self, c: Claim) -> int:
        key = (c.subject_entity_id, c.predicate, c.object_value or "", c.source_chunk_id or -1)
        for ex in self.claims:
            if (ex.subject_entity_id, ex.predicate, ex.object_value or "", ex.source_chunk_id or -1) == key:
                return ex.id
        cid = self._next["claim"]; self._next["claim"] += 1
        self.claims.append(c.model_copy(update={"id": cid}))
        return cid

    def supersede_claim(self, old_id, new_id, valid_to):
        for i, c in enumerate(self.claims):
            if c.id == old_id:
                self.claims[i] = c.model_copy(update={"superseded_by": new_id, "valid_to": valid_to})

    def add_link(self, link: Link) -> None:
        key = (link.from_entity_id, link.to_entity_id, link.link_type, link.as_of)
        if any((l.from_entity_id, l.to_entity_id, l.link_type, l.as_of) == key for l in self.links):
            return
        lid = self._next["link"]; self._next["link"] += 1
        self.links.append(link.model_copy(update={"id": lid}))

    def get_links(self, link_type=None, from_entity_id=None):
        return [l for l in self.links
                if (link_type is None or l.link_type == link_type)
                and (from_entity_id is None or l.from_entity_id == from_entity_id)]

    def add_contradiction(self, c: Contradiction) -> None:
        # dedup on whichever pair is populated: claim-pair OR (SP_011) link-pair. A naive
        # sorted((a, b)) on a link contradiction would crash (both claim ids are None and
        # None is unorderable), so branch on which anchor is set — mirrors the DB's two
        # unique constraints (UNIQUE(claim_a_id, claim_b_id) + contradictions_link_pair).
        if c.claim_a_id is not None and c.claim_b_id is not None:
            key = ("claim", min(c.claim_a_id, c.claim_b_id), max(c.claim_a_id, c.claim_b_id))
        elif c.link_a_id is not None and c.link_b_id is not None:
            key = ("link", min(c.link_a_id, c.link_b_id), max(c.link_a_id, c.link_b_id))
        else:
            self.contradictions.append(c); return
        if any(self._contra_key(x) == key for x in self.contradictions):
            return
        self.contradictions.append(c)

    @staticmethod
    def _contra_key(x: Contradiction):
        if x.claim_a_id is not None and x.claim_b_id is not None:
            return ("claim", min(x.claim_a_id, x.claim_b_id), max(x.claim_a_id, x.claim_b_id))
        if x.link_a_id is not None and x.link_b_id is not None:
            return ("link", min(x.link_a_id, x.link_b_id), max(x.link_a_id, x.link_b_id))
        return None

    def get_claims(self, subject_id, predicate=None):
        return [c for c in self.claims if c.subject_entity_id == subject_id
                and (predicate is None or c.predicate == predicate)]

    def get_contradictions(self, subject_id=None):
        return [c for c in self.contradictions
                if subject_id is None or c.subject_entity_id == subject_id]

    def get_sources(self, claim_ids):
        out = []
        for cid in claim_ids:
            c = next((x for x in self.claims if x.id == cid), None)
            if c is None:
                continue
            doc_id = c.document_id or self.chunk_doc.get(c.source_chunk_id)
            uri = self.doc_uri.get(doc_id) if doc_id else None
            if uri:
                out.append(Citation(source_uri=uri, claim_id=cid))
        return out


class FakeConnector:
    source_type = "md"

    def __init__(self, doc: Document, chunks: list[Chunk]) -> None:
        self._doc, self._chunks = doc, chunks

    def load(self, path):
        return self._doc, list(self._chunks)


class ScriptedExtractor:
    def __init__(self, by_text: dict[str, ExtractionOut]) -> None:
        self.by_text = by_text
        self.calls = 0

    def extract(self, chunk, ctx):
        self.calls += 1
        return self.by_text.get(chunk.text, ExtractionOut())


class FakeEmbedder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return [[0.01] * 1024 for _ in texts]


def _discover_of(*pairs):
    def discover(root):
        return list(pairs)
    return discover


def _doc(uri, h, as_of=date(2026, 3, 31)):
    return Document(source_uri=uri, source_type="md", content_hash=h, as_of=as_of)


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
def _repo_with_roster():
    repo = FakeRepo()
    repo.seed("HelixPay", "other")
    repo.seed("Sara Wijaya", "person")
    repo.seed("Daniel Tan", "person")
    return repo


def test_pipeline_persists_claims_and_links():
    repo = _repo_with_roster()
    doc = _doc("data/board-update-2026-04-22.md", "h1")
    chunk = Chunk(ordinal=0, text="c1")
    extr = ScriptedExtractor({
        "c1": ExtractionOut(
            claims=[ClaimOut(subject="HelixPay", subject_type="other", predicate="ARR",
                             object_value="SGD 51M", as_of="2026-03-31", confidence=0.9)],
            relations=[RelationOut(from_entity="Sara Wijaya", to_entity="Daniel Tan", link_type="reports_to")],
        )
    })
    emb = FakeEmbedder()
    report = run("data", repo, discover=_discover_of((FakeConnector(doc, [chunk]), "p")), embedder=emb, extractor=extr)

    assert report.documents == 1 and report.chunks == 1
    assert report.claims == 1 and report.links == 1 and report.contradictions == 0
    assert repo.claims[0].predicate == canonical_key("ARR") == "arr"
    assert all(c.document_id is not None for c in repo.add_chunks_seen)  # H-2


def test_pipeline_is_idempotent_on_rerun():
    repo = _repo_with_roster()
    doc = _doc("data/x.md", "h1")
    extr = ScriptedExtractor({"c1": ExtractionOut(
        claims=[ClaimOut(subject="HelixPay", subject_type="other", predicate="revenue", object_value="SGD 14.2M", as_of="2026-03-31")])})
    disc = _discover_of((FakeConnector(doc, [Chunk(ordinal=0, text="c1")]), "p"))

    run("data", repo, discover=disc, embedder=FakeEmbedder(), extractor=extr)
    run("data", repo, discover=disc, embedder=FakeEmbedder(), extractor=ScriptedExtractor(extr.by_text))

    assert len(repo.documents) == 1 and len(repo.chunks) == 1 and len(repo.claims) == 1


def test_already_ingested_skips_embed_and_extract():
    repo = _repo_with_roster()
    doc = _doc("data/x.md", "h1")
    extr = ScriptedExtractor({"c1": ExtractionOut(claims=[ClaimOut(subject="HelixPay", predicate="revenue", object_value="v")])})
    emb = FakeEmbedder()
    report = run("data", repo, discover=_discover_of((FakeConnector(doc, [Chunk(ordinal=0, text="c1")]), "p")),
                 embedder=emb, extractor=extr, already_ingested=lambda h: True)

    assert report.skipped_documents == 1
    assert emb.calls == [] and extr.calls == 0 and report.claims == 0


def test_pipeline_detects_contradiction_within_document():
    repo = _repo_with_roster()
    doc = _doc("data/q1.md", "h1")
    chunks = [Chunk(ordinal=0, text="c1"), Chunk(ordinal=1, text="c2")]
    # "revenue" and "Q1 revenue" both canonicalize to "revenue", so the two claims group
    extr = ScriptedExtractor({
        "c1": ExtractionOut(claims=[ClaimOut(subject="HelixPay", subject_type="other", predicate="revenue", object_value="SGD 14.2M", as_of="2026-03-31")]),
        "c2": ExtractionOut(claims=[ClaimOut(subject="HelixPay", subject_type="other", predicate="Q1 revenue", object_value="SGD 13.9M", as_of="2026-03-31")]),
    })
    report = run("data", repo, discover=_discover_of((FakeConnector(doc, chunks), "p")), embedder=FakeEmbedder(), extractor=extr)

    assert report.contradictions == 1
    assert repo.contradictions[0].kind == "value_conflict"  # same as_of, same document
    assert len(repo.claims) == 2  # both coexist, neither collapsed


def test_empty_document_is_a_clean_noop():
    repo = _repo_with_roster()
    doc = _doc("data/empty.md", "h1")
    emb = FakeEmbedder()
    report = run("data", repo, discover=_discover_of((FakeConnector(doc, []), "p")), embedder=emb,
                 extractor=ScriptedExtractor({}))
    assert report.documents == 1 and report.chunks == 0 and report.claims == 0
    assert emb.calls == []  # no embed call for a chunkless document


def test_unresolved_person_mention_is_dropped_not_created():
    repo = _repo_with_roster()
    doc = _doc("data/x.md", "h1")
    extr = ScriptedExtractor({"c1": ExtractionOut(
        claims=[ClaimOut(subject="Ghost Person", subject_type="person", predicate="role", object_value="x")])})
    report = run("data", repo, discover=_discover_of((FakeConnector(doc, [Chunk(ordinal=0, text="c1")]), "p")),
                 embedder=FakeEmbedder(), extractor=extr)
    assert report.claims == 0 and report.dropped_mentions == 1
    assert all(e.canonical_name != "Ghost Person" for e in repo.entities)


def test_self_loop_relation_is_dropped():
    repo = _repo_with_roster()
    doc = _doc("data/x.md", "h1")
    # both endpoints resolve to the same seeded entity -> a self-loop, must not persist
    extr = ScriptedExtractor({"c1": ExtractionOut(
        relations=[RelationOut(from_entity="Daniel Tan", to_entity="Daniel Tan", link_type="reports_to")])})
    report = run("data", repo, discover=_discover_of((FakeConnector(doc, [Chunk(ordinal=0, text="c1")]), "p")),
                 embedder=FakeEmbedder(), extractor=extr)
    assert report.links == 0 and repo.links == []


def test_roster_hint_is_threaded_into_extraction():
    repo = _repo_with_roster()
    doc = _doc("data/x.md", "h1")

    class CtxCapture:
        def __init__(self): self.seen = []
        def extract(self, chunk, ctx):
            self.seen.append(ctx.roster_hint)
            return ExtractionOut()

    cap = CtxCapture()
    run("data", repo, discover=_discover_of((FakeConnector(doc, [Chunk(ordinal=0, text="c1")]), "p")),
        embedder=FakeEmbedder(), extractor=cap, roster_hint="Daniel Tan (person)")
    assert cap.seen == ["Daniel Tan (person)"]


def test_layer0_repairs_dashboard_metric_subject_to_company():
    # SP_019 Layer 0: the exact .replay-cache surface forms (metric-as-subject) must land on
    # the seeded company, not a minted metric row.
    repo = _repo_with_roster()  # seeds HelixPay (other)
    doc = _doc("data/dashboards/april-2026-kpi-dashboard.html", "h1")
    extr = ScriptedExtractor({"c1": ExtractionOut(claims=[
        ClaimOut(subject="Q1 2026 Revenue", subject_type="metric",
                 predicate="Q1 2026 Revenue (SGD)", object_value="SGD 14.2M", as_of="2026-04-21"),
        ClaimOut(subject="Aggregate NPS", subject_type="metric",
                 predicate="Aggregate NPS", object_value="47", as_of="2026-04-21"),
    ])})
    run("data", repo, discover=_discover_of((FakeConnector(doc, [Chunk(ordinal=0, text="c1")]), "p")),
        embedder=FakeEmbedder(), extractor=extr)

    hp = next(e for e in repo.entities if e.canonical_name == "HelixPay").id
    assert repo.claims and all(c.subject_entity_id == hp for c in repo.claims)  # company, not metric
    assert not any(e.entity_type == "metric" for e in repo.entities)  # no metric|... minted
    # NPS canonicalizes through the alias even in the simplified fake ("aggregate nps" -> nps)
    assert any(c.predicate == "nps" and c.object_value == "47" for c in repo.claims)


def test_layer0_leaves_regional_metric_distinct_no_false_merge():
    # the planted Brasil value (unknown metric key) must NOT collapse onto the company.
    repo = _repo_with_roster()
    doc = _doc("data/images/revenue-trend-q1-2026.jpeg", "h1")
    extr = ScriptedExtractor({"c1": ExtractionOut(claims=[
        ClaimOut(subject="Brasil revenue", subject_type="metric", predicate="Brasil actual revenue",
                 object_value="SGD 4.8M", as_of="2026-03-31")])})
    run("data", repo, discover=_discover_of((FakeConnector(doc, [Chunk(ordinal=0, text="c1")]), "p")),
        embedder=FakeEmbedder(), extractor=extr)
    hp = next(e for e in repo.entities if e.canonical_name == "HelixPay").id
    # the Brasil claim is NOT on HelixPay (it minted/stayed its own subject) — no false merge.
    assert not any(c.subject_entity_id == hp for c in repo.claims)


def test_layer0_disabled_when_primary_entity_unseeded():
    # No seeded HelixPay -> repair disables (loud warning). The metric claim then falls back to
    # the pre-Layer-0 behavior (mints metric|Revenue); crucially it never RE-MINTS a HelixPay
    # row, so a roster rename can't silently fabricate the company entity.
    repo = FakeRepo()
    doc = _doc("data/x.html", "h1")
    extr = ScriptedExtractor({"c1": ExtractionOut(claims=[
        ClaimOut(subject="Revenue", subject_type="metric", predicate="revenue", object_value="SGD 14.2M")])})
    run("data", repo, discover=_discover_of((FakeConnector(doc, [Chunk(ordinal=0, text="c1")]), "p")),
        embedder=FakeEmbedder(), extractor=extr)
    assert not any(e.canonical_name == "HelixPay" for e in repo.entities)  # no fabricated company
    # the claim is not lost — it lands on the (minted) metric subject, exactly as before Layer 0
    assert any(e.canonical_name == "Revenue" and e.entity_type == "metric" for e in repo.entities)


def test_same_source_newer_value_supersedes_not_duplicates():
    repo = _repo_with_roster()
    d1 = _doc("data/x.md", "h1", as_of=date(2026, 3, 31))
    d2 = _doc("data/x.md", "h2", as_of=date(2026, 4, 30))  # changed file, same uri, newer
    e1 = ScriptedExtractor({"c1": ExtractionOut(claims=[ClaimOut(subject="HelixPay", subject_type="other", predicate="revenue", object_value="SGD 13.9M", as_of="2026-03-31")])})
    e2 = ScriptedExtractor({"c2": ExtractionOut(claims=[ClaimOut(subject="HelixPay", subject_type="other", predicate="revenue", object_value="SGD 14.2M", as_of="2026-04-30")])})

    run("data", repo, discover=_discover_of((FakeConnector(d1, [Chunk(ordinal=0, text="c1")]), "p")), embedder=FakeEmbedder(), extractor=e1)
    run("data", repo, discover=_discover_of((FakeConnector(d2, [Chunk(ordinal=0, text="c2")]), "p")), embedder=FakeEmbedder(), extractor=e2)

    old = next(c for c in repo.claims if c.object_value == "SGD 13.9M")
    new = next(c for c in repo.claims if c.object_value == "SGD 14.2M")
    assert old.superseded_by == new.id and old.valid_to == date(2026, 4, 30)  # set, not deleted
    assert len(repo.claims) == 2  # both rows kept
    assert repo.contradictions == []  # same source → supersede, NOT a contradiction


# --------------------------------------------------------------------------- #
# SP_011 — provenance is produced on the write path
# --------------------------------------------------------------------------- #
def test_pipeline_persists_evidence_and_located_offsets():
    repo = _repo_with_roster()
    doc = _doc("data/board.md", "h1")
    chunk = Chunk(ordinal=0, text="Q1 closed at SGD 14.2M against a 16M plan.")
    extr = ScriptedExtractor({chunk.text: ExtractionOut(claims=[
        ClaimOut(subject="HelixPay", subject_type="other", predicate="revenue",
                 object_value="SGD 14.2M", as_of="2026-03-31",
                 evidence="SGD 14.2M against a 16M plan")])})
    run("data", repo, discover=_discover_of((FakeConnector(doc, [chunk]), "p")),
        embedder=FakeEmbedder(), extractor=extr)
    c = repo.claims[0]
    assert c.evidence == "SGD 14.2M against a 16M plan"
    assert chunk.text[c.char_start:c.char_end] == "SGD 14.2M against a 16M plan"


def test_pipeline_persists_evidence_with_none_offsets_when_unlocatable():
    # a paraphrased span that isn't a contiguous substring → evidence kept, offsets None
    repo = _repo_with_roster()
    doc = _doc("data/board.md", "h1")
    chunk = Chunk(ordinal=0, text="Topline came to 14.2M for the period.")
    extr = ScriptedExtractor({chunk.text: ExtractionOut(claims=[
        ClaimOut(subject="HelixPay", subject_type="other", predicate="revenue",
                 object_value="14.2M", as_of="2026-03-31",
                 evidence="ARR figure reported as 14.2M total annual")])})
    run("data", repo, discover=_discover_of((FakeConnector(doc, [chunk]), "p")),
        embedder=FakeEmbedder(), extractor=extr)
    c = repo.claims[0]
    assert c.evidence == "ARR figure reported as 14.2M total annual"
    assert c.char_start is None and c.char_end is None


def test_pipeline_link_carries_document_id():
    repo = _repo_with_roster()
    doc = _doc("data/board.md", "h1")
    extr = ScriptedExtractor({"c1": ExtractionOut(
        relations=[RelationOut(from_entity="Sara Wijaya", to_entity="Daniel Tan", link_type="reports_to")])})
    run("data", repo, discover=_discover_of((FakeConnector(doc, [Chunk(ordinal=0, text="c1")]), "p")),
        embedder=FakeEmbedder(), extractor=extr)
    assert len(repo.links) == 1
    assert repo.links[0].document_id is not None
    assert repo.links[0].source_chunk_id is not None


def test_pipeline_detects_link_contradiction_across_managers():
    repo = _repo_with_roster()
    arjun = repo.seed("Arjun Kapoor", "person")
    sara = next(e.id for e in repo.entities if e.canonical_name == "Sara Wijaya")
    doc = _doc("data/x.md", "h1")
    # one subject, two DIFFERENT solid-line managers in the same chunk → a graph conflict
    extr = ScriptedExtractor({"c1": ExtractionOut(relations=[
        RelationOut(from_entity="Sara Wijaya", to_entity="Daniel Tan", link_type="reports_to"),
        RelationOut(from_entity="Sara Wijaya", to_entity="Arjun Kapoor", link_type="reports_to"),
    ])})
    report = run("data", repo, discover=_discover_of((FakeConnector(doc, [Chunk(ordinal=0, text="c1")]), "p")),
                 embedder=FakeEmbedder(), extractor=extr)
    assert report.links == 2
    assert report.contradictions == 1
    link_contras = [c for c in repo.contradictions if c.link_a_id is not None]
    assert len(link_contras) == 1
    c = link_contras[0]
    assert c.subject_entity_id == sara and c.predicate == "reports_to"
    assert c.kind == "value_conflict"  # both edges from the same document
    assert {c.link_a_id, c.link_b_id} == {l.id for l in repo.links}  # pairs the two edges
    del arjun  # seeded only so the second manager resolves


def test_pipeline_consistent_reports_to_has_no_link_contradiction():
    repo = _repo_with_roster()
    doc = _doc("data/x.md", "h1")
    extr = ScriptedExtractor({"c1": ExtractionOut(relations=[
        RelationOut(from_entity="Sara Wijaya", to_entity="Daniel Tan", link_type="reports_to")])})
    report = run("data", repo, discover=_discover_of((FakeConnector(doc, [Chunk(ordinal=0, text="c1")]), "p")),
                 embedder=FakeEmbedder(), extractor=extr)
    assert report.links == 1 and report.contradictions == 0
