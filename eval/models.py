"""Typed records for the eval harness (validated over the YAML).

``GoldenFact`` / ``Question`` are pydantic models so a malformed golden set or a
question with an unknown check fails loudly at load time rather than silently
mis-grading. Report types are plain dataclasses (pure data the harness prints).

Only ``helixpay.contracts`` is imported here — never a build slice.
"""

from __future__ import annotations

import math
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
    # SP_013: name-collision tag. Facts sharing a group (e.g. the two Marias) must
    # resolve to DISTINCT entity_ids — see eval/run.py check_entity_collisions.
    collision_group: Optional[str] = None
    # link-only:
    link_type: Optional[str] = None
    from_: Optional[str] = Field(default=None, alias="from")
    to: Optional[str] = None


class PredicateSynonym(BaseModel):
    """A predicate and its aliases that MUST canonicalize to one ``metric_vocab`` key
    (SP_013). ``ARR`` ≡ "annual recurring revenue" or contradiction detection no-ops."""

    model_config = ConfigDict(extra="forbid")

    id: str
    canonical: str
    aliases: list[str]
    note: Optional[str] = None


class EntityCollision(BaseModel):
    """A set of colliding names that must resolve to distinct entities (SP_013). Each
    name is paired by position with a resolving ``context`` (e.g. ``{source_uri: ...}``)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    names: list[str]
    contexts: list[dict] = Field(default_factory=list)
    note: Optional[str] = None


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
    predicate_synonyms: list[PredicateSynonym] = field(default_factory=list)
    entity_collisions: list[EntityCollision] = field(default_factory=list)

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


def wilson_interval(found: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion (research P0 #1 — report an
    interval, not a bare ratio; the naive normal interval misbehaves at the extremes
    and small n). ``z=1.96`` ≈ 95%. Returns ``(low, high)`` clamped to ``[0, 1]``;
    ``total==0`` returns ``(0.0, 0.0)`` (no observations, no interval).

    NOTE the golden facts are CLUSTERED by source document, so the true standard error
    is wider than this i.i.d.-Bernoulli interval — the rendered report states that
    caveat so the CI is not over-claimed."""
    if total <= 0:
        return (0.0, 0.0)
    n = float(total)
    p = found / n
    denom = 1.0 + z * z / n
    centre = p + z * z / (2.0 * n)
    margin = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n))
    low = (centre - margin) / denom
    high = (centre + margin) / denom
    return (max(0.0, low), min(1.0, high))


@dataclass
class FactVerdict:
    fact_id: str
    verdict: Verdict
    detail: str = ""
    # SP_013: the canonicalized predicate (claims) or link_type (links) this verdict is
    # for — grouping key for macro-per-predicate recall.
    predicate: str = ""


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
    def recall_ci(self) -> tuple[float, float]:
        """Wilson 95% interval on micro recall (research P0 #1)."""
        return wilson_interval(self.found, self.total)

    @property
    def per_predicate_recall(self) -> dict[str, tuple[int, int, float]]:
        """``{predicate: (found, total, recall)}`` — surfaces a rare-predicate miss
        (e.g. ``dotted_line_to`` recall 0) that micro recall would hide."""
        groups: dict[str, list[FactVerdict]] = {}
        for v in self.verdicts:
            groups.setdefault(v.predicate, []).append(v)
        out: dict[str, tuple[int, int, float]] = {}
        for pred, vs in groups.items():
            total = len(vs)
            found = sum(1 for v in vs if v.verdict is Verdict.found)
            out[pred] = (found, total, found / total if total else 0.0)
        return out

    @property
    def macro_recall(self) -> float:
        """Mean of per-predicate recall, weighting every predicate equally (research
        P0 #4). 0.0 when there are no verdicts."""
        per = self.per_predicate_recall
        if not per:
            return 0.0
        return sum(r for _, _, r in per.values()) / len(per)

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


# --------------------------------------------------------------------------- #
# WikiContradict 3-class scoring + name-collision verdicts (SP_013)           #
# --------------------------------------------------------------------------- #
class ContradictionClass(str, Enum):
    """WikiContradict 3-class verdict (research P1 #5)."""

    correct = "CORRECT"      # both conflicting sides named, neither favored/dropped
    partial = "PARTIAL"      # surfaced but only one side has a claim id (a side dropped)
    incorrect = "INCORRECT"  # no contradiction surfaced → silent merge (the worst case)


@dataclass
class ContradictionVerdict:
    contradiction_id: str
    verdict: ContradictionClass
    both_ids_present: bool
    detail: str = ""

    @property
    def passed(self) -> bool:
        return self.verdict is ContradictionClass.correct


@dataclass
class CollisionVerdict:
    collision_id: str
    passed: bool
    detail: str = ""


__all__ = [
    "KNOWN_CHECKS",
    "GATING_CHECKS",
    "SOFT_CHECKS",
    "KNOWN_FORMATS",
    "FactKind",
    "GoldenFact",
    "GoldenContradiction",
    "PredicateSynonym",
    "EntityCollision",
    "GoldenSet",
    "Question",
    "Verdict",
    "FactVerdict",
    "ExtractionReport",
    "CheckResult",
    "AnswerResult",
    "GoalVerdict",
    "wilson_interval",
    "ContradictionClass",
    "ContradictionVerdict",
    "CollisionVerdict",
]
