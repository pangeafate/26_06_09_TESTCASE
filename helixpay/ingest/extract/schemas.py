"""Structured-output schemas for extraction — validated against the frozen contracts.

The LLM is asked for JSON matching :class:`ExtractionOut`. These pydantic models are the
*schema* half of the "named prompt + structured-output schema + validate-and-repair"
convention (CLAUDE.md §7): enum-valued fields must land on a real ``EntityType`` /
``LinkType``; ``as_of`` must be a real ISO date; predicates must be non-empty; confidence
is clamped to ``[0,1]``. Anything the model emits outside these bounds fails validation
and triggers the repair-or-drop loop — no free-form trust.

These are the LLM's *candidate* shapes (entities are bare mention strings here);
``resolve``/``pipeline`` map them onto the contract ``Claim``/``Link`` after roster
resolution and predicate canonicalization.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from helixpay.contracts import EntityType, LinkType

_ENTITY_TYPES = {t.value for t in EntityType}
_LINK_TYPES = {t.value for t in LinkType}


def parse_as_of(raw: Optional[str]) -> Optional[date]:
    """Parse an ISO ``YYYY-MM-DD`` date, or ``None``. Raises ``ValueError`` otherwise."""
    if raw is None:
        return None
    return date.fromisoformat(raw)


class ClaimOut(BaseModel):
    """A candidate property value the model asserts about a subject mention."""

    subject: str
    subject_type: Optional[str] = None
    predicate: str
    object_value: Optional[str] = None
    as_of: Optional[str] = None
    confidence: float = 0.5
    evidence: Optional[str] = None
    # The model flags hypotheticals/counterfactuals ("would have been") so we never
    # persist them as competing facts (they create false contradictions — Stage-3 H1).
    hypothetical: bool = False

    @field_validator("subject", "predicate")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must be a non-empty string")
        return v.strip()

    @field_validator("subject_type")
    @classmethod
    def _known_entity_type(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in _ENTITY_TYPES:
            raise ValueError(f"subject_type must be one of {sorted(_ENTITY_TYPES)}")
        return v

    @field_validator("as_of")
    @classmethod
    def _iso_as_of(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            parse_as_of(v)  # raises ValueError on a non-ISO date
        return v

    @field_validator("confidence")
    @classmethod
    def _clamp_confidence(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))

    def as_of_date(self) -> Optional[date]:
        return parse_as_of(self.as_of)


class RelationOut(BaseModel):
    """A candidate typed relation between two entity mentions."""

    from_entity: str
    to_entity: str
    link_type: str
    as_of: Optional[str] = None
    confidence: float = 0.5

    @field_validator("from_entity", "to_entity")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must be a non-empty string")
        return v.strip()

    @field_validator("link_type")
    @classmethod
    def _known_link_type(cls, v: str) -> str:
        if v not in _LINK_TYPES:
            raise ValueError(f"link_type must be one of {sorted(_LINK_TYPES)}")
        return v

    @field_validator("as_of")
    @classmethod
    def _iso_as_of(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            parse_as_of(v)
        return v

    @field_validator("confidence")
    @classmethod
    def _clamp_confidence(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))

    def as_of_date(self) -> Optional[date]:
        return parse_as_of(self.as_of)


class ExtractionOut(BaseModel):
    """The full per-chunk extraction payload (strict, post-filtering)."""

    claims: list[ClaimOut] = Field(default_factory=list)
    relations: list[RelationOut] = Field(default_factory=list)


class RawExtraction(BaseModel):
    """Lenient envelope for the LLM round-trip: just two arrays of objects.

    The repair loop validates *this* shape (a JSON object with ``claims``/``relations``
    arrays); the extractor then validates each item against the strict ``ClaimOut`` /
    ``RelationOut`` and drops invalid items individually, so one malformed item does not
    discard its valid siblings.
    """

    claims: list[dict] = Field(default_factory=list)
    relations: list[dict] = Field(default_factory=list)


__all__ = ["ClaimOut", "RelationOut", "ExtractionOut", "RawExtraction", "parse_as_of"]
