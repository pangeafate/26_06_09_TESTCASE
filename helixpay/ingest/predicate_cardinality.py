"""Predicate cardinality — data-driven policy for the contradiction pre-filter (SP_028a).

Pure shared logic (no infra). One home for "is this predicate single-valued?" so the
contradiction sweep can drop clusters where multiplicity is *legitimate* (a person has many
pain points; two values are not a disagreement) BEFORE spending anything on detection or — later
(SP_028b) — an LLM. Rule 18: a data table, not per-predicate code forks.

Classes (every entry grounded in an observed contradiction row in the live `helixpay_full`
266-row set — the count is cited):

* ``set_valued``  — multiplicity is legitimate; two values are NOT a conflict → the sweep SKIPS
  the cluster. (The ONLY class that causes a skip.)
* ``breakdown``   — the value is per-sub-entity (per product line, per reviewer-pair, per person),
  not a competing total. Classified for documentation but **NOT skipped in v1**: a `breakdown`
  predicate like `gross_revenue` is *also* a real company metric, so dropping by predicate would
  lose the genuine conflict. Entity-aware handling is deferred (SP_028b/SP_029).
* ``functional``  — one true value per subject; distinct values are a candidate conflict → KEEP.
* ``unknown``     — not classified here → KEEP (the safe default: an unclassified predicate, incl.
  every link type, is never silently dropped).

Only ``set_valued`` membership changes behavior (``should_skip_predicate``). Keep this table in
lock-step with observed spurious rows; when a new genuinely multi-valued predicate appears in the
data, add it here with its count.
"""

from __future__ import annotations

from typing import Literal

Cardinality = Literal["functional", "set_valued", "breakdown", "unknown"]

# Multiplicity is legitimate — listing two is not a disagreement. (live-data row counts)
_SET_VALUED: frozenset[str] = frozenset(
    {
        "weekly_activity",          # 6 — a person does many activities across the week
        "pain_point",               # 3 — a customer/persona has several pain points
        "q1_miss_driver",           # 3 — a miss is multi-causal; several drivers coexist
        "desired_feature",          # 2 — many requested features
        "tool_used_for",            # 1 — different tools for different purposes
        "weekly_recurring_meeting", # 1 — several standing meetings
        "responsibilities",         # 1 — many responsibilities
        "data_quality_weakness",    # 1 — several weaknesses
        "attendee",                 # 1 — many attendees at an event
    }
)

# Per-sub-entity values (NOT a competing total). Classified, NOT skipped in v1 (see module doc).
_BREAKDOWN: frozenset[str] = frozenset(
    {
        "gross_revenue",   # 9  — Açaí per product line (Core/POS/Tap)
        "net_revenue",     # 10 — per product line
        "refunds",         # 10 — per product line
        "cross_pr_reviews",# 10 — per reviewer-pair
        "commit_count",    # 3  — per person
    }
)

# One true value per subject — distinct values are a genuine candidate conflict. (observed)
_FUNCTIONAL: frozenset[str] = frozenset(
    {
        "ga_target", "completion_target", "revenue", "nps", "ebitda", "revenue_vs_plan",
        "title", "role", "board_meeting_date", "location", "total_paid_merchants",
        "launch_date", "backlog_status",
    }
)


# The three sets are disjoint by design — a predicate has exactly one class. Enforce at import
# so a copy-paste that lands a predicate in two sets fails loudly instead of silently mis-skipping.
assert not (_SET_VALUED & _BREAKDOWN), _SET_VALUED & _BREAKDOWN
assert not (_SET_VALUED & _FUNCTIONAL), _SET_VALUED & _FUNCTIONAL
assert not (_BREAKDOWN & _FUNCTIONAL), _BREAKDOWN & _FUNCTIONAL


def cardinality(predicate: str) -> Cardinality:
    """Classify a (already-canonical) predicate. Unknown → ``"unknown"`` (kept, never skipped)."""
    if predicate in _SET_VALUED:
        return "set_valued"
    if predicate in _BREAKDOWN:
        return "breakdown"
    if predicate in _FUNCTIONAL:
        return "functional"
    return "unknown"


def should_skip_predicate(predicate: str) -> bool:
    """True ONLY for explicitly ``set_valued`` predicates — the one class the contradiction
    sweep drops. functional / breakdown / unknown are all kept (no real conflict is ever
    silently lost). Applied to CLAIM groups only; link groups keep their own gate."""
    return cardinality(predicate) == "set_valued"


__all__ = ["Cardinality", "cardinality", "should_skip_predicate"]
