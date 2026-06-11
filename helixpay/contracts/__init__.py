"""Public contract surface for the HelixPay ontology.

Import everything cross-module from here:

    from helixpay.contracts import Claim, Repository, AnswerBundle

These types are frozen at the gate (HELIXPAY_BUILD_SPEC.md §4). Downstream agents
import them and never redefine them locally.
"""

from __future__ import annotations

from .connector import SourceConnector
from .models import (
    Alias,
    AnswerBundle,
    Chunk,
    Citation,
    Claim,
    Contradiction,
    ContradictionKind,
    Document,
    Entity,
    EntityDetail,
    EntityType,
    Link,
    LinkType,
    MetricVocab,
    OrgNode,
    SourceType,
)
from .query import QueryEngine
from .repository import Repository

__all__ = [
    # models
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
    # enums
    "SourceType",
    "EntityType",
    "LinkType",
    "ContradictionKind",
    # protocols
    "SourceConnector",
    "Repository",
    "QueryEngine",
]
