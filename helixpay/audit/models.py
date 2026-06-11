"""Audit value types (pure data — no I/O, no SQL).

These are tool-output records, deliberately NOT in ``helixpay/contracts`` (they are not
cross-module domain types; the audit is a dev-tooling capability). ``ClaimRecord`` is a
claim flattened with its chunk text, document ``source_uri`` and subject entity — the
unit every invariant check reads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Optional


class Severity(str, Enum):
    error = "error"  # a real integrity break (gates ``--strict``)
    warn = "warn"  # a soft signal worth a human look (e.g. unresolved subject)
    info = "info"


@dataclass(frozen=True)
class ClaimRecord:
    """A claim joined to its chunk, document and subject entity."""

    id: int
    subject_entity_id: Optional[int]
    subject_name: Optional[str]
    subject_type: Optional[str]
    predicate: str
    object_value: Optional[str]
    as_of: Optional[date]
    confidence: Optional[float]
    superseded_by: Optional[int]
    source_chunk_id: Optional[int]
    document_id: Optional[int]
    chunk_text: Optional[str]
    document_source_uri: Optional[str]
    evidence: Optional[str] = None
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    # False when run against a pre-SP_009 schema (no evidence/offset columns): the
    # evidence invariants then no-op instead of false-flagging every claim.
    evidence_columns_present: bool = True

    @classmethod
    def from_row(cls, row: dict[str, Any], *, evidence_present: bool) -> "ClaimRecord":
        """Build from a ``dict_row`` mapping (see ``audit_queries.fetch_claim_rows``)."""
        return cls(
            id=row["id"],
            subject_entity_id=row.get("subject_entity_id"),
            subject_name=row.get("subject_name"),
            subject_type=row.get("subject_type"),
            predicate=row["predicate"],
            object_value=row.get("object_value"),
            as_of=row.get("as_of"),
            confidence=row.get("confidence"),
            superseded_by=row.get("superseded_by"),
            source_chunk_id=row.get("source_chunk_id"),
            document_id=row.get("document_id"),
            chunk_text=row.get("chunk_text"),
            document_source_uri=row.get("document_source_uri"),
            evidence=row.get("evidence"),
            char_start=row.get("char_start"),
            char_end=row.get("char_end"),
            evidence_columns_present=evidence_present,
        )


@dataclass(frozen=True)
class Violation:
    """One invariant breach against one claim."""

    claim_id: int
    category: str
    severity: Severity
    detail: str


@dataclass(frozen=True)
class TrapResult:
    """The outcome of one planted known-answer check."""

    name: str
    passed: bool
    detail: str


@dataclass
class AuditReport:
    total_claims: int
    counts: dict[str, int]
    violations: list[Violation]
    sample: list[ClaimRecord]
    traps: list[TrapResult]
    evidence_columns_present: bool

    def violations_by_category(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for v in self.violations:
            out[v.category] = out.get(v.category, 0) + 1
        return out

    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.severity is Severity.error)

    def failed_traps(self) -> list[TrapResult]:
        return [t for t in self.traps if not t.passed]

    def clean(self) -> bool:
        """True when nothing hard is wrong: no ERROR invariants and every trap passed."""
        return self.error_count() == 0 and not self.failed_traps()


__all__ = ["Severity", "ClaimRecord", "Violation", "TrapResult", "AuditReport"]
