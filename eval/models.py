"""Typed records for the eval harness (validated over the YAML).

``GoldenFact`` / ``Question`` are pydantic models so a malformed golden set or a
question with an unknown check fails loudly at load time rather than silently
mis-grading. Report types are plain dataclasses (pure data the harness prints).

Only ``helixpay.contracts`` is imported here — never a build slice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

# Closed vocabulary of answer checks. Kept here so both the loader (validation) and
# the harness (evaluation) share one source of truth; test_golden.py asserts that
# every check used in questions.yaml is in this set.
KNOWN_CHECKS: frozenset[str] = frozenset(
    {
        "cites_source",
        "states_as_of",
        "resolves_hierarchy",
        "uses_freshest_as_of",
        "surfaces_contradiction",
        "attributes_each_side",
        "cross_document_synthesis",
        "cites_multiple_sources",
        "entity_resolution",
        "alias_handling",
        "no_false_contradiction",
    }
)

# Checks that decide the /goal verdict. ``alias_handling`` is reported but not gated
# (the hard alias test lives in extraction recall, not in the answer bundle shape).
SOFT_CHECKS: frozenset[str] = frozenset({"alias_handling"})
GATING_CHECKS: frozenset[str] = KNOWN_CHECKS - SOFT_CHECKS

KNOWN_FORMATS: frozenset[str] = frozenset(
    {"md", "pdf", "html", "slack", "email", "code", "interview", "image"}
)


class FactKind(str, Enum):
    claim = "claim"
    link = "link"


class GoldenFact(BaseModel):
    """One by-eye fact. ``recall_bar`` facts count toward the recall denominator."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str
    format: str
    kind: FactKind
    subject: str
    predicate: str
    value: str
    as_of: Optional[date] = None
    source_uri: str
    recall_bar: bool = True
    note: Optional[str] = None
    # link-only:
    link_type: Optional[str] = None
    from_: Optional[str] = Field(default=None, alias="from")
    to: Optional[str] = None


class GoldenContradiction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    subject: str
    predicate: str
    claim_a: Optional[str] = None
    claim_b: Optional[str] = None
    corroborating_sources: list[str] = Field(default_factory=list)
    expected: Optional[str] = None
    note: Optional[str] = None


@dataclass
class GoldenSet:
    facts: list[GoldenFact]
    contradictions: list[GoldenContradiction]

    @property
    def bar_facts(self) -> list[GoldenFact]:
        return [f for f in self.facts if f.recall_bar]


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    q: str
    checks: list[str]
    golden_refs: list[str] = Field(default_factory=list)
    contradiction_ref: Optional[str] = None
    expected: Optional[str] = None
    note: Optional[str] = None


# --------------------------------------------------------------------------- #
# Report records                                                              #
# --------------------------------------------------------------------------- #
class Verdict(str, Enum):
    found = "FOUND"
    mismatch = "MISMATCH"
    missing = "MISSING"


@dataclass
class FactVerdict:
    fact_id: str
    verdict: Verdict
    detail: str = ""


@dataclass
class ExtractionReport:
    verdicts: list[FactVerdict] = field(default_factory=list)

    @property
    def found(self) -> int:
        return sum(1 for v in self.verdicts if v.verdict is Verdict.found)

    @property
    def mismatch(self) -> int:
        return sum(1 for v in self.verdicts if v.verdict is Verdict.mismatch)

    @property
    def missing(self) -> int:
        return sum(1 for v in self.verdicts if v.verdict is Verdict.missing)

    @property
    def total(self) -> int:
        return len(self.verdicts)

    @property
    def recall(self) -> float:
        return self.found / self.total if self.total else 0.0

    @property
    def precision(self) -> float:
        """Golden-set precision: of the golden subjects the extractor attempted
        (FOUND + MISMATCH), the fraction it got right. Not corpus precision."""
        attempted = self.found + self.mismatch
        return self.found / attempted if attempted else 0.0


@dataclass
class CheckResult:
    name: str
    passed: bool
    gating: bool


@dataclass
class AnswerResult:
    question_id: str
    checks: list[CheckResult] = field(default_factory=list)
    latency_s: float = 0.0
    error: Optional[str] = None
    surfaced_contradiction: bool = False

    @property
    def gating_passed(self) -> bool:
        if self.error is not None:
            return False
        return all(c.passed for c in self.checks if c.gating)


@dataclass
class GoalVerdict:
    recall: float
    recall_bar: float
    recall_ok: bool
    answers_ok: bool
    contradiction_ok: bool

    @property
    def passed(self) -> bool:
        return self.recall_ok and self.answers_ok and self.contradiction_ok


__all__ = [
    "KNOWN_CHECKS",
    "GATING_CHECKS",
    "SOFT_CHECKS",
    "KNOWN_FORMATS",
    "FactKind",
    "GoldenFact",
    "GoldenContradiction",
    "GoldenSet",
    "Question",
    "Verdict",
    "FactVerdict",
    "ExtractionReport",
    "CheckResult",
    "AnswerResult",
    "GoalVerdict",
]
