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
    Entity,
    Link,
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
        self.semantic: list[tuple[Chunk, float]] = []
        self.lexical: list[tuple[Chunk, float]] = []
        self.org_tree: OrgNode = OrgNode(entity_id=0, name="", children=[], dotted_reports=[])
        self.vocab: dict[str, str] = {}  # lowercased alias -> canonical key

    # -- helpers used by tests ------------------------------------------- #
    def add_entity(self, e: Entity) -> int:
        eid = e.id or (max(self.entities) + 1 if self.entities else 1)
        e.id = eid
        self.entities[eid] = e
        self.aliases.setdefault(e.canonical_name.strip().lower(), eid)
        return eid

    def add_alias_for(self, entity_id: int, alias: str) -> None:
        self.aliases[alias.strip().lower()] = entity_id

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

    def get_claims(self, subject_id: int, predicate: Optional[str] = None) -> list[Claim]:
        out = [c for c in self.claims.values() if c.subject_entity_id == subject_id]
        if predicate:
            out = [c for c in out if c.predicate == predicate]
        return out

    def get_links(self, link_type: Optional[str] = None) -> list[Link]:
        if link_type:
            return [link for link in self.links if link.link_type == link_type]
        return list(self.links)

    def get_org_subtree(self, root_id: Optional[int] = None, as_of: Optional[date] = None) -> OrgNode:
        return self.org_tree

    def get_contradictions(self, subject_id: Optional[int] = None) -> list[Contradiction]:
        if subject_id is None:
            return list(self.contradictions)
        return [c for c in self.contradictions if c.subject_entity_id == subject_id]

    def get_sources(self, claim_ids: list[int]) -> list[Citation]:
        return [self.citations[cid] for cid in claim_ids if cid in self.citations]

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
