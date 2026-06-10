"""Contradiction detection — first-class rows, never collapse (CLAUDE.md §7, spec §2/§4).

Claims about the same ``(subject, canonical_predicate)`` whose values disagree over
overlapping validity windows become a ``contradictions`` row. The conflicting claims
**coexist** — detection only reads claims and writes contradiction rows; it never edits,
supersedes, or deletes a claim.

Overlap is computed over each claim's validity interval ``[valid_from|as_of,
valid_to|as_of]`` with ``None`` meaning open (±∞). Two concrete, *different* ``as_of``
points therefore do **not** overlap — so a periodic metric's Q4 vs Q1 values are not a
contradiction, while two same-period sources that disagree are. This keeps precision on the
planted dashboard-vs-board-deck conflict (both stamped Q1 2026) without flooding false
positives across quarters.

The exception is ``_TARGET_PREDICATES`` (GA/completion targets): there ``as_of`` is the
assertion date, not a validity window, so two differing forward targets stated on
different dates are a real temporal slip and bypass the overlap gate (the planted
Confluence GA contradiction). They still pass through ``values_conflict``, so identical
target phrasings agree and only a genuine change surfaces.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from helixpay.contracts import Claim, Contradiction, Repository

# Value normalization is the shared SP_009 substrate — one definition across contradiction
# detection, the eval matcher, and consensus rollup, so equality never drifts between them.
# Re-exported (see __all__) so existing `from helixpay.ingest.contradict import
# normalize_value` imports (e.g. grounding.py) keep working without a second copy.
from helixpay.ingest.normalize import normalize_value, values_conflict

log = logging.getLogger("helixpay.ingest.contradict")

# Predicates whose value is a forward target date and whose ``as_of`` is the assertion
# date, not a validity window. A changed value across two assertion dates is a genuine
# temporal slip (the planted Confluence GA contradiction), so ``detect`` skips the
# window-overlap gate for these — scoped narrowly so periodic metrics stay unaffected.
_TARGET_PREDICATES = frozenset({"ga_target", "completion_target"})


def _window(c: Claim) -> tuple[Optional[date], Optional[date]]:
    lo = c.valid_from or c.as_of
    hi = c.valid_to or c.as_of
    return lo, hi


def windows_overlap(a: Claim, b: Claim) -> bool:
    a_lo, a_hi = _window(a)
    b_lo, b_hi = _window(b)
    # None = open bound. Overlap iff a_lo <= b_hi and b_lo <= a_hi.
    if a_lo is not None and b_hi is not None and a_lo > b_hi:
        return False
    if b_lo is not None and a_hi is not None and b_lo > a_hi:
        return False
    return True


def classify(a: Claim, b: Claim) -> str:
    """Non-overlapping decision tree:
    (1) ``source_disagreement`` — different documents over a compatible period (same
        ``as_of``, or either ``as_of`` unknown);
    (2) ``temporal`` — both dated and the ``as_of`` values differ;
    (3) ``value_conflict`` — otherwise (same document, or undated within one source).

    Undated claims count as period-compatible rather than forcing a ``temporal`` label, so a
    cross-source disagreement where one side is undated is still a ``source_disagreement``
    (Stage-5 fix)."""
    period_compatible = a.as_of == b.as_of or a.as_of is None or b.as_of is None
    if (
        a.document_id is not None
        and b.document_id is not None
        and a.document_id != b.document_id
        and period_compatible
    ):
        return "source_disagreement"
    if a.as_of is not None and b.as_of is not None and a.as_of != b.as_of:
        return "temporal"
    return "value_conflict"


def detect(repo: Repository, subject_id: int, predicate: str) -> int:
    """Detect and persist contradictions among the live claims for one
    ``(subject_id, predicate)`` group. Returns the number of contradiction rows written
    (the repo dedupes pairs, so a re-run adds none). ``predicate`` must already be
    canonicalized by the caller."""
    live = [
        c for c in repo.get_claims(subject_id, predicate) if c.superseded_by is None
    ]
    # Pairs already recorded — so a re-run detects nothing new and ``written`` reflects only
    # newly-added rows (the repo also dedupes, but the count must be honest too).
    seen_pairs: set[tuple[int, int]] = {
        (min(c.claim_a_id, c.claim_b_id), max(c.claim_a_id, c.claim_b_id))
        for c in repo.get_contradictions(subject_id)
        if c.claim_a_id is not None and c.claim_b_id is not None
    }
    written = 0
    for i in range(len(live)):
        for j in range(i + 1, len(live)):
            a, b = live[i], live[j]
            if a.id is None or b.id is None:
                log.warning(
                    "skip contradiction with unpersisted claim",
                    extra={"subject_id": subject_id, "predicate": predicate},
                )
                continue
            pair = (min(a.id, b.id), max(a.id, b.id))
            if pair in seen_pairs:
                continue  # already recorded — re-run is a no-op
            if not values_conflict(a.object_value, b.object_value):
                continue
            # Target/deadline predicates carry an assertion-date as_of, not a validity
            # window, so a changed target across two dates is a real slip — skip the
            # window gate for them (scoped, so periodic-metric time-series stay clean).
            if predicate not in _TARGET_PREDICATES and not windows_overlap(a, b):
                continue
            seen_pairs.add(pair)
            kind = classify(a, b)
            repo.add_contradiction(
                Contradiction(
                    subject_entity_id=subject_id,
                    predicate=predicate,
                    claim_a_id=a.id,
                    claim_b_id=b.id,
                    kind=kind,
                    note=f"{a.object_value!r} ({a.as_of}) vs {b.object_value!r} ({b.as_of})",
                )
            )
            written += 1
    if written:
        log.info(
            "contradictions detected",
            extra={"subject_id": subject_id, "predicate": predicate, "count": written},
        )
    return written


__all__ = [
    "detect",
    "normalize_value",
    "values_conflict",
    "windows_overlap",
    "classify",
]
