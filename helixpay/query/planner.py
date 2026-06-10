"""Lightweight question planner — routes {structured | retrieval | both}.

Cheap lexical classification (no LLM, no DB) of what an answer needs:

* **structured** — pure graph/claim lookup (e.g. a bare reporting-line question).
* **retrieval** — open narrative with no structured anchor.
* **both** — the common case: gather claims/links *and* retrieved chunks.

Two deliberate rules from the Stage-3 review:

* A **metric/value** question always probes for contradictions, even when phrased
  without "disagree"/"conflict" (review arch-C1/code-L2) — that is where the
  planted Q1 revenue conflict hides.
* A hierarchy question carrying a freshness cue ("as of", "latest") routes to
  ``both`` so the temporal/staleness path runs (review code-H4).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Route(str, Enum):
    structured = "structured"
    retrieval = "retrieval"
    both = "both"


@dataclass(frozen=True)
class Plan:
    route: Route
    wants_hierarchy: bool
    wants_contradictions: bool
    wants_ownership: bool
    wants_freshness: bool


_HIERARCHY = (
    "report to", "reports to", "report into", "reports into", "reporting line",
    "reporting to", "org chart", "org-chart", "hierarchy", "who does", "head of",
    "manager", "manages", "managed by", "dotted line", "dotted-line", "reports up",
)
_OWNERSHIP = ("owns", "owner", "owned by", "who owns", "responsible for", "account manager", "relationship")
_CONTRADICTION = (
    "disagree", "conflict", "contradict", "mismatch", "differ", "discrepanc",
    "inconsistent", "don't match", "do not match", "which is correct", "which is right",
)
_METRIC = (
    "revenue", "arr", "recurring revenue", "ebitda", "burn", "runway", "nps",
    "churn", "merchant", "headcount", "head count", "margin", "target", "kpi",
    "metric", "how much", "what was", "figure", "growth",
)
_FRESHNESS = ("as of", "latest", "most recent", "currently", "current ", "right now", "as-of")


def _any(text: str, needles: tuple[str, ...]) -> bool:
    return any(n in text for n in needles)


def _has_proper_noun(question: str) -> bool:
    """A capitalised mid-sentence token suggests a named entity (subject)."""
    tokens = question.split()
    for tok in tokens[1:]:
        stripped = tok.strip(".,?!:;'\"")
        core = "".join(ch for ch in stripped if ch.isalpha())  # tolerate CEO's, ARR, etc.
        if len(core) > 1 and stripped[:1].isupper():
            return True
    return False


def route(question: str) -> Plan:
    ql = question.lower()
    wants_hierarchy = _any(ql, _HIERARCHY)
    wants_ownership = _any(ql, _OWNERSHIP)
    wants_contradictions = _any(ql, _CONTRADICTION) or _any(ql, _METRIC)
    wants_freshness = _any(ql, _FRESHNESS)

    structured_signal = (
        wants_hierarchy or wants_ownership or wants_contradictions or _has_proper_noun(question)
    )

    if wants_hierarchy and not wants_freshness and not wants_contradictions and not wants_ownership:
        chosen = Route.structured
    elif structured_signal:
        chosen = Route.both
    else:
        chosen = Route.retrieval

    return Plan(
        route=chosen,
        wants_hierarchy=wants_hierarchy,
        wants_contradictions=wants_contradictions,
        wants_ownership=wants_ownership,
        wants_freshness=wants_freshness,
    )


__all__ = ["Route", "Plan", "route"]
