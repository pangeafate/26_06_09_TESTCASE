"""Repository contract (spec §4) — the single storage seam.

Agents 2 (extraction) and 3 (query) code against this Protocol; the gate provides
the one Postgres implementation (``helixpay.db.repository.PostgresRepository``). All
raw SQL is confined to ``helixpay.db``; nothing else touches the database directly.

Frozen seam decisions from the Stage 3 plan review:
  * ``resolve_entity`` takes an optional ``context`` so the two Marias / two Tans
    can be disambiguated; a bare ambiguous name with no context resolves to None
    (never a silent arbitrary pick).
  * ``supersede_claim`` carries supersession through the seam (sets valid_to /
    superseded_by); facts are never deleted.
  * ``add_chunks`` takes embeddings only — ``tsv`` is a DB-generated column.
  * ``canonical_predicate`` returns its input unchanged when unknown; it never raises.
"""

from __future__ import annotations

from datetime import date
from typing import Optional, Protocol, runtime_checkable

from .models import (
    Chunk,
    Citation,
    Claim,
    Contradiction,
    Document,
    Entity,
    Link,
    OrgNode,
)


@runtime_checkable
class Repository(Protocol):
    # -- documents & chunks ------------------------------------------------- #
    def upsert_document(self, doc: Document) -> int:
        """Insert a document, or return the existing id when ``content_hash``
        already exists (idempotency — a no-op re-ingest)."""
        ...

    def add_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]) -> list[int]:
        """Persist chunks with their (upstream-computed) embeddings. ``tsv`` is
        generated in the database. Returns the new chunk ids in input order."""
        ...

    # -- entities & aliases ------------------------------------------------- #
    def upsert_entity(self, e: Entity) -> int:
        ...

    def add_alias(self, entity_id: int, alias: str, source_chunk_id: Optional[int] = None) -> None:
        ...

    def resolve_entity(
        self,
        name: str,
        entity_type: Optional[str] = None,
        context: Optional[dict] = None,
    ) -> Optional[Entity]:
        """Resolve a mention to a roster entity (seeded entities first). ``context``
        may carry disambiguation hints (e.g. ``{"team": "...", "location": "...",
        "source_uri": "..."}``). An ambiguous bare name with no resolving context
        returns None rather than guessing."""
        ...

    # -- claims, links, contradictions ------------------------------------- #
    def add_claim(self, c: Claim) -> int:
        """Insert a claim. Insert-only and idempotent on its natural key
        (subject, predicate, object_value, source_chunk_id); supersession is a
        separate operation (``supersede_claim``). Provenance-v2 fields
        (``evidence``/``char_start``/``char_end``) are persisted but are NOT part of
        the natural key, so a re-extraction of the same fact keeps the first span."""
        ...

    def supersede_claim(self, old_id: int, new_id: int, valid_to: date) -> None:
        """Mark ``old_id`` superseded by ``new_id`` and set its ``valid_to``.
        Never deletes the superseded claim."""
        ...

    def add_link(self, link: Link) -> None:
        ...

    def add_contradiction(self, c: Contradiction) -> None:
        ...

    def canonical_predicate(self, raw: str) -> str:
        """Map a raw predicate onto its ``metric_vocab`` canonical key. Returns
        ``raw`` unchanged when it is not in the vocabulary; never raises."""
        ...

    # -- retrieval ---------------------------------------------------------- #
    def search_semantic(self, qvec: list[float], k: int) -> list[tuple[Chunk, float]]:
        ...

    def search_lexical(self, q: str, k: int) -> list[tuple[Chunk, float]]:
        ...

    # -- graph / structured reads ------------------------------------------ #
    def get_claims(self, subject_id: int, predicate: Optional[str] = None) -> list[Claim]:
        ...

    def get_links(
        self,
        link_type: Optional[str] = None,
        from_entity_id: Optional[int] = None,
    ) -> list[Link]:
        """All links, optionally filtered by ``link_type`` and/or ``from_entity_id``.
        ``from_entity_id`` was appended (SP_009) so the new parameter is keyword- and
        positionally-backward-compatible: ``get_links("reports_to")`` is unchanged."""
        ...

    def get_org_subtree(self, root_id: Optional[int] = None, as_of: Optional[date] = None) -> OrgNode:
        """Recursive-CTE org subtree from ``root_id`` (or the org root). ``as_of``
        filters reporting lines to those valid at that date."""
        ...

    def get_contradictions(self, subject_id: Optional[int] = None) -> list[Contradiction]:
        ...

    def get_sources(self, claim_ids: list[int]) -> list[Citation]:
        ...

    # -- provenance v2 (SP_009) -------------------------------------------- #
    def get_link_sources(self, link_ids: list[int]) -> list[Citation]:
        """Provenance for relationship (link) rows. Each returned ``Citation`` is
        anchored by ``link_id``; ``snippet`` is the link's source-chunk text prefix
        (links carry no evidence span). Links with no resolvable source are omitted."""
        ...

    def get_chunk_sources(self, chunk_ids: list[int]) -> list[Citation]:
        """Provenance for retrieved chunks (closes the query chunk-citation hole). One
        ``Citation`` per chunk, anchored by ``chunk_id`` with the chunk-text prefix as
        ``snippet`` — no claim join, so ``claim_id`` is always ``None``."""
        ...

    def known_content_hashes(self) -> set[str]:
        """Every ``documents.content_hash`` already stored. Lets ingestion skip
        re-embedding unchanged sources (compute-idempotency: re-ingest → near-free)."""
        ...


__all__ = ["Repository"]
