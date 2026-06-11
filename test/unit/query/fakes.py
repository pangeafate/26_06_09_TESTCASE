"""In-memory fakes for the query unit suite (no DB, no API keys, no SDKs).

Importable as a bare top-level module under pytest's prepend import mode (the
``test/unit/query`` dir is on ``sys.path`` because it has no ``__init__``).
``conftest.py`` re-exports the fixtures.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from helixpay.config import EMBEDDING_DIM
from helixpay.contracts import (
    Chunk,
    Citation,
    Claim,
    Contradiction,
    Document,
    Entity,
    Link,
    MetricVocab,
    OrgNode,
)


class FakeRepository:
    """Hand-wired in-memory Repository — only the reads the query layer uses."""

    def __init__(self) -> None:
        self.entities: dict[int, Entity] = {}
        self.aliases: dict[str, int] = {}  # lowercased name/alias -> entity id
        self.claims: dict[int, Claim] = {}
        self.links: list[Link] = []
        self.contradictions: list[Contradiction] = []
        self.citations: dict[int, Citation] = {}  # claim_id -> Citation
        self.chunk_citations: dict[int, Citation] = {}  # chunk_id -> Citation (SP_009)
        self.link_citations: dict[int, Citation] = {}  # link_id -> Citation (SP_009)
        self.semantic: list[tuple[Chunk, float]] = []
        self.lexical: list[tuple[Chunk, float]] = []
        self.org_tree: OrgNode = OrgNode(
            entity_id=0, name="", children=[], dotted_reports=[]
        )
        self.vocab: dict[str, str] = {}  # lowercased alias -> canonical key
        self.documents: dict[int, Document] = {}  # SP_022: document inventory
        self.chunks: dict[int, Chunk] = {}  # SP_022: chunk-by-id (fetch)
        self.metrics: list[MetricVocab] = []  # SP_023: metric vocabulary

    # -- helpers used by tests ------------------------------------------- #
    def add_document(self, doc: Document) -> int:
        did = doc.id or (max(self.documents) + 1 if self.documents else 1)
        doc.id = did
        self.documents[did] = doc
        return did

    def add_chunk_row(self, chunk: Chunk) -> int:
        cid = chunk.id or (max(self.chunks) + 1 if self.chunks else 1)
        chunk.id = cid
        self.chunks[cid] = chunk
        return cid

    def add_metric(self, metric: MetricVocab) -> None:
        self.metrics.append(metric)
        for alias in [metric.canonical_key, *metric.aliases]:
            self.vocab[alias.strip().lower()] = metric.canonical_key

    def add_entity(self, e: Entity) -> int:
        eid = e.id or (max(self.entities) + 1 if self.entities else 1)
        e.id = eid
        self.entities[eid] = e
        self.aliases.setdefault(e.canonical_name.strip().lower(), eid)
        return eid

    def add_alias_for(self, entity_id: int, alias: str) -> None:
        self.aliases[alias.strip().lower()] = entity_id

    def add_link_row(self, link: Link, citation: Optional[Citation] = None) -> int:
        lid = link.id or (max((x.id or 0 for x in self.links), default=0) + 1)
        link.id = lid
        self.links.append(link)
        if citation is not None:
            citation.link_id = lid
            self.link_citations[lid] = citation
        return lid

    def add_chunk_source(self, chunk_id: int, citation: Citation) -> None:
        citation.chunk_id = chunk_id
        self.chunk_citations[chunk_id] = citation

    def add_claim_row(self, c: Claim, citation: Optional[Citation] = None) -> int:
        cid = c.id or (max(self.claims) + 1 if self.claims else 1)
        c.id = cid
        self.claims[cid] = c
        if citation is not None:
            citation.claim_id = cid
            self.citations[cid] = citation
        return cid

    # -- Repository reads ------------------------------------------------ #
    def search_semantic(self, qvec: list[float], k: int) -> list[tuple[Chunk, float]]:
        return self.semantic[:k]

    def search_lexical(self, q: str, k: int) -> list[tuple[Chunk, float]]:
        return self.lexical[:k]

    def get_claims(
        self, subject_id: int, predicate: Optional[str] = None
    ) -> list[Claim]:
        out = [c for c in self.claims.values() if c.subject_entity_id == subject_id]
        if predicate:
            out = [c for c in out if c.predicate == predicate]
        return out

    def get_links(
        self,
        link_type: Optional[str] = None,
        from_entity_id: Optional[int] = None,
        to_entity_id: Optional[int] = None,
    ) -> list[Link]:
        out = list(self.links)
        if link_type:
            out = [link for link in out if link.link_type == link_type]
        if from_entity_id is not None:
            out = [link for link in out if link.from_entity_id == from_entity_id]
        if to_entity_id is not None:  # SP_023 — incoming edges
            out = [link for link in out if link.to_entity_id == to_entity_id]
        return out

    def get_org_subtree(
        self, root_id: Optional[int] = None, as_of: Optional[date] = None
    ) -> OrgNode:
        return self.org_tree

    def get_contradictions(
        self, subject_id: Optional[int] = None
    ) -> list[Contradiction]:
        if subject_id is None:
            return list(self.contradictions)
        return [c for c in self.contradictions if c.subject_entity_id == subject_id]

    def get_sources(self, claim_ids: list[int]) -> list[Citation]:
        return [self.citations[cid] for cid in claim_ids if cid in self.citations]

    def get_chunk_sources(self, chunk_ids: list[int]) -> list[Citation]:
        return [
            self.chunk_citations[cid]
            for cid in chunk_ids
            if cid in self.chunk_citations
        ]

    def get_link_sources(self, link_ids: list[int]) -> list[Citation]:
        return [
            self.link_citations[lid] for lid in link_ids if lid in self.link_citations
        ]

    # -- SP_022 retrieval reads ------------------------------------------ #
    def get_chunk(self, chunk_id: int) -> Optional[Chunk]:
        return self.chunks.get(chunk_id)

    def list_documents(self) -> list[Document]:
        # as_of DESC NULLS LAST, id ASC (mirror PostgresRepository.list_documents)
        return sorted(
            self.documents.values(),
            key=lambda d: (
                d.as_of is None,
                -(d.as_of.toordinal() if d.as_of else 0),
                d.id or 0,
            ),
        )

    def list_entities(self, entity_type: Optional[str] = None) -> list[Entity]:
        out = [
            e
            for e in self.entities.values()
            if entity_type is None or e.entity_type == entity_type
        ]
        return sorted(out, key=lambda e: (e.entity_type, e.canonical_name))

    # -- SP_023 graph/temporal reads ------------------------------------- #
    def list_metrics(self) -> list[MetricVocab]:
        return sorted(self.metrics, key=lambda m: m.canonical_key)

    def get_claims_by_predicate(
        self, predicate: str, subject_id: Optional[int] = None
    ) -> list[Claim]:
        # Canonical-equality match (alias-aware via self.vocab). The SQL period-strip is NOT
        # reproduced here — unit tests use canonical/alias predicate spellings; period-qualified
        # matching is proven in the db-integration test (SP_023 Stage-3 M2).
        target = self.canonical_predicate(predicate)
        out = [
            c
            for c in self.claims.values()
            if self.canonical_predicate(c.predicate) == target
            and (subject_id is None or c.subject_entity_id == subject_id)
        ]
        return sorted(
            out,
            key=lambda c: (
                c.subject_entity_id is None,  # NULLS LAST (matches the SQL ordering)
                c.subject_entity_id or 0,
                -(c.as_of.toordinal() if c.as_of else 0),
                c.id or 0,
            ),
        )

    def resolve_entity(
        self,
        name: str,
        entity_type: Optional[str] = None,
        context: Optional[dict] = None,
    ) -> Optional[Entity]:
        eid = self.aliases.get(name.strip().lower())
        if eid is None:
            return None
        ent = self.entities.get(eid)
        if ent is None:
            return None
        if entity_type and ent.entity_type != entity_type:
            return None
        return ent

    def canonical_predicate(self, raw: str) -> str:
        return self.vocab.get(raw.strip().lower(), raw)


class FakeEmbedder:
    def __init__(self, value: float = 0.01) -> None:
        self._value = value
        self.calls: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        self.calls.append(text)
        return [self._value] * EMBEDDING_DIM


class FakeSynthesizer:
    """Returns a canned structured response; records the prompt it was given."""

    def __init__(self, response: Optional[dict] = None) -> None:
        self.response = response or {"sentences": [], "confidence": 0.0}
        self.last_prompt: Optional[str] = None
        self.last_schema: Optional[dict] = None

    def synthesize(self, prompt: str, *, schema: dict) -> dict:
        self.last_prompt = prompt
        self.last_schema = schema
        return self.response
