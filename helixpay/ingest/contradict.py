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
"""

from __future__ import annotations

import logging
import math
import re
from datetime import date
from typing import Optional

from helixpay.contracts import Claim, Contradiction, Repository

log = logging.getLogger("helixpay.ingest.contradict")

_SCALE = {"k": 1_000.0, "m": 1_000_000.0, "b": 1_000_000_000.0}
_CURRENCY = re.compile(r"\b(sgd|usd|brl|eur|myr)\b|[r$€£]", re.IGNORECASE)
_UNICODE_MINUS = "−"  # − (spreadsheets/PDFs emit this, not ASCII -)
# A value is treated as numeric ONLY when the whole cleaned string is a single number
# (optional magnitude K/M/B, optional trailing %). This deliberately refuses to pull a
# stray digit out of a label: "Q1 2026", "18 months", "v1.0" stay non-numeric and fall
# back to text comparison, so quarter/duration/version strings are never mis-compared as
# magnitudes (Stage-5: _NUM_RE word-boundary / "18 months"→18M defects).
_PURE_NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*\s*([kmb])?\s*%?", re.IGNORECASE)


def normalize_value(value: Optional[str]) -> tuple[str, Optional[float]]:
    """Return ``(casefolded_text, numeric_or_None)``. Strips currency symbols and folds
    magnitude suffixes (K/M/B) so ``"SGD 14.2M"`` and ``"14.2M"`` compare equal, and
    normalizes the Unicode minus sign so ``"−11%"`` and ``"-11%"`` compare equal. A value
    is numeric only when the *entire* cleaned string is a number — never a digit pulled from
    a label."""
    if value is None:
        return "", None
    # text component: casefold + normalize the Unicode minus + collapse whitespace (so the
    # text-comparison fallback also treats "−x" and "-x" as equal). Currency is stripped
    # only for the *numeric* parse, not the returned text.
    text = re.sub(r"\s+", " ", value.strip().casefold().replace(_UNICODE_MINUS, "-")).strip()
    cleaned = re.sub(r"\s+", " ", _CURRENCY.sub(" ", text)).strip()
    numeric: Optional[float] = None
    m = _PURE_NUM_RE.fullmatch(cleaned)
    if m:
        suffix = (m.group(1) or "").lower()
        num_text = cleaned.rstrip("%").strip()
        if suffix:
            num_text = num_text[: num_text.lower().rfind(suffix)]
        try:
            numeric = float(num_text.replace(",", "").strip()) * _SCALE.get(suffix, 1.0)
        except ValueError:
            numeric = None
    return text, numeric


def values_conflict(a: Optional[str], b: Optional[str]) -> bool:
    if a is None or b is None:
        return False  # a missing value is not a competing fact
    ta, na = normalize_value(a)
    tb, nb = normalize_value(b)
    if na is not None and nb is not None:
        return not math.isclose(na, nb, rel_tol=1e-9, abs_tol=1e-9)
    return ta != tb


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
    live = [c for c in repo.get_claims(subject_id, predicate) if c.superseded_by is None]
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
            if not windows_overlap(a, b):
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
        log.info("contradictions detected", extra={"subject_id": subject_id, "predicate": predicate, "count": written})
    return written


__all__ = ["detect", "normalize_value", "values_conflict", "windows_overlap", "classify"]
