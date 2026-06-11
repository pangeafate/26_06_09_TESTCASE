"""Frozen domain models for the HelixPay ontology (spec §4).

These are the cross-module types. Every other module imports them from here and
NEVER redefines them locally. They are pydantic models so the extraction layer can
validate LLM structured output against them and repair-or-drop (spec §7).

The ontology is a *claim/assertion* model: a property value is a ``Claim`` carrying
its source, ``as_of`` and confidence; conflicting claims coexist (they are never
collapsed into a golden record), and ``Contradiction`` rows are first-class objects.
Superseded facts are never deleted — ``valid_to`` / ``superseded_by`` are set instead.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional, TypedDict

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Controlled vocabularies (string enums — stored as TEXT, validated in Python) #
# --------------------------------------------------------------------------- #
class SourceType(str, Enum):
    md = "md"
    pdf = "pdf"
    html = "html"
    image = "image"
    slack = "slack"
    email = "email"
    code = "code"


class EntityType(str, Enum):
    person = "person"
    team = "team"
    customer = "customer"
    product = "product"
    metric = "metric"
    other = "other"  # org units / subsidiaries (e.g. HelixPay Brasil) land here


class LinkType(str, Enum):
    reports_to = "reports_to"        # solid-line management
    dotted_line_to = "dotted_line_to"  # functional dotted-line (org-chart.md:123)
    owns = "owns"
    member_of = "member_of"
    mentions = "mentions"


class ContradictionKind(str, Enum):
    value_conflict = "value_conflict"
    temporal = "temporal"
    source_disagreement = "source_disagreement"


# --------------------------------------------------------------------------- #
# Core records                                                                #
# --------------------------------------------------------------------------- #
class Document(BaseModel):
    """Raw provenance, content-addressed for idempotency."""

    id: Optional[int] = None
    source_uri: str
    source_type: str  # one of SourceType
    title: Optional[str] = None
    author: Optional[str] = None
    lang: Optional[str] = None
    as_of: Optional[date] = None
    ingested_at: Optional[datetime] = None
    content_hash: str
    raw_text: Optional[str] = None


class Chunk(BaseModel):
    """A retrievable span of a document.

    ``embedding`` and ``tsv`` are storage concerns (the embedding is produced
    upstream by the ingest pipeline and passed to ``Repository.add_chunks``; the
    ``tsv`` is a DB-generated column) and so are deliberately NOT carried here.
    """

    id: Optional[int] = None
    document_id: Optional[int] = None
    ordinal: int = 0
    text: str


class Entity(BaseModel):
    id: Optional[int] = None
    canonical_name: str
    entity_type: str  # one of EntityType
    attributes: dict = Field(default_factory=dict)
    seeded: bool = False  # True for roster rows loaded at the gate


class Alias(BaseModel):
    id: Optional[int] = None
    entity_id: int
    alias: str
    source_chunk_id: Optional[int] = None


class Claim(BaseModel):
    """One asserted property value. Conflicting claims coexist."""

    id: Optional[int] = None
    subject_entity_id: Optional[int] = None
    predicate: str  # canonicalized against metric_vocab where applicable
    object_value: Optional[str] = None
    object_entity_id: Optional[int] = None
    as_of: Optional[date] = None
    confidence: Optional[float] = None
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    superseded_by: Optional[int] = None
    source_chunk_id: Optional[int] = None
    document_id: Optional[int] = None
    # Provenance v2 (SP_009): the verbatim grounding span the model cited and its
    # offsets into the source chunk text (``chunks.text``), span ``[char_start, char_end)``.
    # Additive + nullable: an old payload without them validates and degrades to today's
    # behavior. They are NOT part of the natural key, so a re-extraction of the same fact
    # with a different span dedupes to the first write (first-write-wins).
    evidence: Optional[str] = None
    char_start: Optional[int] = None
    char_end: Optional[int] = None


class Link(BaseModel):
    """A typed relation, including org hierarchy (queried via recursive CTE)."""

    id: Optional[int] = None
    from_entity_id: int
    to_entity_id: int
    link_type: str  # one of LinkType
    # SP_025: the original out-of-vocab verb when link_type was coerced to the generic
    # `mentions` fallback (e.g. "contributor", "employed_by"). None for canonical links.
    # Additive + nullable; rides outside the natural key (mirrors document_id below).
    raw_verb: Optional[str] = None
    as_of: Optional[date] = None
    valid_to: Optional[date] = None
    confidence: Optional[float] = None
    source_chunk_id: Optional[int] = None
    # Provenance v2 (SP_009): mirror Claim so relationship provenance is a direct join
    # (not claims-only). Additive + nullable; first-write-wins on re-ingest.
    document_id: Optional[int] = None


class Contradiction(BaseModel):
    """A first-class object: two disagreeing facts, surfaced never hidden.

    A contradiction pairs two *claims* (value conflicts) or, since SP_009, two *links*
    (graph/relationship conflicts, e.g. two sources asserting different managers). Exactly
    one pair kind is populated per row; the unused pair stays ``None``.
    """

    id: Optional[int] = None
    subject_entity_id: Optional[int] = None
    predicate: Optional[str] = None
    claim_a_id: Optional[int] = None
    claim_b_id: Optional[int] = None
    kind: Optional[str] = None  # one of ContradictionKind
    note: Optional[str] = None
    detected_at: Optional[datetime] = None
    # Provenance v2 (SP_009): link-pair conflicts make graph contradictions first-class.
    link_a_id: Optional[int] = None
    link_b_id: Optional[int] = None


class MetricVocab(BaseModel):
    """One controlled-vocabulary metric (the ``metric_vocab`` table).

    A new additive model (SP_023) for a previously-unmodeled table — it backs the
    ``list_metrics`` read so an agent can discover the queryable predicate vocabulary
    (``canonical_key`` + its human ``display_name`` + the ``aliases`` that canonicalize onto
    it). It is a *new* type, not a fork of a frozen one.
    """

    canonical_key: str
    display_name: Optional[str] = None
    aliases: list[str] = Field(default_factory=list)


class Citation(BaseModel):
    """Provenance attached to an answer. ``as_of`` is what makes staleness visible.

    A citation anchors back to whatever it grounds: a ``claim_id`` (value provenance),
    a ``chunk_id`` (retrieval provenance), or — since SP_009 — a ``link_id`` (relationship
    provenance, returned by ``get_link_sources``). All anchors are nullable and additive.
    """

    source_uri: str
    as_of: Optional[date] = None
    snippet: Optional[str] = None
    claim_id: Optional[int] = None
    chunk_id: Optional[int] = None
    link_id: Optional[int] = None


class AnswerBundle(BaseModel):
    """The grounded answer. Contradictions are surfaced, never hidden (spec §4)."""

    answer: str
    citations: list[Citation] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    as_of_coverage: dict = Field(default_factory=dict)
    confidence: float = 0.0


# --------------------------------------------------------------------------- #
# Typed return shapes for graph/entity reads (replaces bare ``dict`` — review M2) #
# --------------------------------------------------------------------------- #
class OrgNode(TypedDict, total=False):
    """One node of an org-subtree returned by ``get_org_subtree``/``get_org_chart``."""

    entity_id: int
    name: str
    role: Optional[str]
    as_of: Optional[str]           # ISO date of the reporting line
    reports_to: Optional[int]
    children: list["OrgNode"]      # solid-line reports
    dotted_reports: list[int]      # dotted-line functional reports (entity ids)


class EntityDetail(TypedDict, total=False):
    """Shape returned by ``QueryEngine.get_entity`` / aggregated entity read."""

    entity: dict
    aliases: list[str]
    claims: list[dict]
    links: list[dict]


__all__ = [
    "SourceType",
    "EntityType",
    "LinkType",
    "ContradictionKind",
    "Document",
    "Chunk",
    "Entity",
    "Alias",
    "Claim",
    "Link",
    "Contradiction",
    "MetricVocab",
    "Citation",
    "AnswerBundle",
    "OrgNode",
    "EntityDetail",
]
