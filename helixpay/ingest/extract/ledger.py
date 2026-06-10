"""Per-source extraction loss ledger (SP_014).

Accumulates counters for every extraction call so silent losses become measurable.
The ``probe()`` method has a FROZEN interface consumed by SP_015's check_smoke —
do not change the key names or structure without coordinating with that sprint.

  DocLoss            per-source accumulator (one instance per source URI)
  LossLedger         collection of DocLoss objects, with bulk mutation helpers
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class DocLoss:
    """Counters for a single source document."""

    chunks: int = 0
    empty_extractions: int = 0
    truncated_calls: int = 0
    items_emitted: int = 0
    items_dropped: int = 0
    dropped_by_reason: Counter[str] = field(default_factory=Counter)
    coerced_by_kind: Counter[str] = field(default_factory=Counter)


@dataclass
class LossLedger:
    """Collection of per-source ``DocLoss`` accumulators.

    All ``record_*`` methods create the ``DocLoss`` entry on first use (lazy init),
    so callers need not pre-register URIs.

    ``probe()`` emits exactly the three keys ``empty_extractions``,
    ``truncated_calls``, ``items_dropped`` per source_uri — this shape is FROZEN
    and consumed by SP_015's check_smoke.
    """

    per_source: dict[str, DocLoss] = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    # Internal accessor
    # ------------------------------------------------------------------ #

    def _doc(self, uri: str) -> DocLoss:
        if uri not in self.per_source:
            self.per_source[uri] = DocLoss()
        return self.per_source[uri]

    # ------------------------------------------------------------------ #
    # Mutation helpers
    # ------------------------------------------------------------------ #

    def record_chunk(self, uri: str) -> None:
        """Count one chunk processed for this source."""
        self._doc(uri).chunks += 1

    def record_empty(self, uri: str) -> None:
        """Count one extraction that returned zero items (model undecodable or empty)."""
        self._doc(uri).empty_extractions += 1

    def record_truncated(self, uri: str) -> None:
        """Count one call whose stop_reason was max_tokens."""
        self._doc(uri).truncated_calls += 1

    def record_emitted(self, uri: str, n: int = 1) -> None:
        """Count raw items emitted by the model (before coercion or validation)."""
        self._doc(uri).items_emitted += n

    def record_coerced(self, uri: str, kind: str) -> None:
        """Count one coercion action.

        kind in {"as_of", "subject_type", "link_verb", "link_invert"}
        """
        self._doc(uri).coerced_by_kind[kind] += 1

    def record_drop(self, uri: str, reason: str) -> None:
        """Count one dropped item.

        reason in {"validation_error", "unmappable_enum", "unparseable_as_of",
                   "hypothetical", "ungrounded"}
        """
        doc = self._doc(uri)
        doc.items_dropped += 1
        doc.dropped_by_reason[reason] += 1

    # ------------------------------------------------------------------ #
    # Query helpers
    # ------------------------------------------------------------------ #

    def probe(self) -> dict[str, dict]:
        """Return a compact loss summary keyed by source URI.

        Shape is FROZEN (consumed by SP_015 check_smoke):
        {
            "<uri>": {
                "empty_extractions": int,
                "truncated_calls": int,
                "items_dropped": int,
            },
            ...
        }

        NOTE (intentional, not a bug): every URI that recorded a chunk appears here, even
        with all-zero counters. This is load-bearing for the SP_015 seam — a cleanly-extracted
        doc must be PRESENT-with-zeros (→ eligible to PASS), and must be distinguishable from a
        doc that was never extracted at all (ABSENT from the table → check_smoke treats a
        missing entry as completeness-unverified → INCOMPLETE, never a silent PASS). Filtering
        zero-loss URIs out would collapse that distinction.
        """
        return {
            uri: {
                "empty_extractions": doc.empty_extractions,
                "truncated_calls": doc.truncated_calls,
                "items_dropped": doc.items_dropped,
            }
            for uri, doc in self.per_source.items()
        }

    def summary(self) -> dict:
        """Return a JSON-serialisable full summary.

        Shape:
        {
            "totals": {
                "chunks": int,
                "empty_extractions": int,
                "truncated_calls": int,
                "items_emitted": int,
                "items_dropped": int,
                "dropped_by_reason": {reason: count, ...},
                "coerced_by_kind": {kind: count, ...},
            },
            "by_source": {
                "<uri>": {
                    "chunks": int,
                    "empty_extractions": int,
                    "truncated_calls": int,
                    "items_emitted": int,
                    "items_dropped": int,
                    "dropped_by_reason": {reason: count, ...},
                    "coerced_by_kind": {kind: count, ...},
                },
                ...
            },
        }

        Counters are converted to plain dict for JSON compatibility.
        """
        totals_chunks = 0
        totals_empty = 0
        totals_truncated = 0
        totals_emitted = 0
        totals_dropped = 0
        totals_dropped_by_reason: Counter[str] = Counter()
        totals_coerced_by_kind: Counter[str] = Counter()

        by_source: dict[str, dict] = {}
        for uri, doc in self.per_source.items():
            totals_chunks += doc.chunks
            totals_empty += doc.empty_extractions
            totals_truncated += doc.truncated_calls
            totals_emitted += doc.items_emitted
            totals_dropped += doc.items_dropped
            totals_dropped_by_reason.update(doc.dropped_by_reason)
            totals_coerced_by_kind.update(doc.coerced_by_kind)

            by_source[uri] = {
                "chunks": doc.chunks,
                "empty_extractions": doc.empty_extractions,
                "truncated_calls": doc.truncated_calls,
                "items_emitted": doc.items_emitted,
                "items_dropped": doc.items_dropped,
                # Convert Counter → plain dict for JSON serialisability
                "dropped_by_reason": dict(doc.dropped_by_reason),
                "coerced_by_kind": dict(doc.coerced_by_kind),
            }

        return {
            "totals": {
                "chunks": totals_chunks,
                "empty_extractions": totals_empty,
                "truncated_calls": totals_truncated,
                "items_emitted": totals_emitted,
                "items_dropped": totals_dropped,
                "dropped_by_reason": dict(totals_dropped_by_reason),
                "coerced_by_kind": dict(totals_coerced_by_kind),
            },
            "by_source": by_source,
        }


__all__ = ["DocLoss", "LossLedger"]
