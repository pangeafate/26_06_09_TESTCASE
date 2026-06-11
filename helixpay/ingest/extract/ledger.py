"""Per-source extraction loss ledger (SP_014; drop taxonomy extended SP_024).

Accumulates counters for every extraction call so silent losses become measurable.
The ``probe()`` interface is consumed by SP_015's check_smoke — coordinate any key change
with that sprint. SP_024 added one key (``lossy_drops``); the original keys are unchanged.

  DocLoss            per-source accumulator (one instance per source URI)
  LossLedger         collection of DocLoss objects, with bulk mutation helpers
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

# Drop-reason taxonomy (SP_024). Two semantically distinct classes hide behind one counter:
#   • LOSSY — the model emitted content the pipeline could not faithfully represent
#     (schema/enum/date failures). This is potential SIGNAL LOSS and must gate the
#     completeness proof (INCOMPLETE → needs human explanation).
#   • INTENTIONAL — the pipeline CORRECTLY declined to assert a conditional/future statement
#     ("hypothetical") or one unsupported by the source ("ungrounded"). This is the
#     faithfulness contract working as designed; it is expected on every real document and
#     must NOT gate the proof. Conflating the two made items_dropped==0 unreachable, which
#     wrongly forced every cleanly-extracted doc to INCOMPLETE.
#
# IMPORTANT (review): the gate is defined by EXCLUSION from INTENTIONAL_DROP_REASONS, not by
# membership in LOSSY_DROP_REASONS — see DocLoss.lossy_drops. That is the fail-safe direction:
# an unrecognised/new reason counts as lossy (blocks PASS), never silently benign. Do NOT
# rewrite lossy_drops to use LOSSY_DROP_REASONS as a positive allow-list — that reverses the
# fail-safe. LOSSY_DROP_REASONS is documentation-only (the known lossy reasons) and intentionally
# not consulted by the gating logic. NOTE: "ungrounded" is RESERVED — the current pipeline
# penalises an ungrounded claim's confidence and KEEPS it (extractor._apply_grounding); it is
# not emitted as a drop today. It is classified intentional here so that IF a future sprint wires
# ungrounded-as-drop it is non-gating by default; that wiring must be reviewed deliberately.
LOSSY_DROP_REASONS = frozenset({"validation_error", "unmappable_enum", "unparseable_as_of"})
INTENTIONAL_DROP_REASONS = frozenset({"hypothetical", "ungrounded"})


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

    @property
    def lossy_drops(self) -> int:
        """The gating subset of ``items_dropped``: drops that represent genuine signal loss
        (schema/enum/date failures). Intentional non-assertions (hypothetical/ungrounded) are
        excluded. An unrecognised reason counts as lossy (fail-safe: an un-classified drop
        must not silently pass the completeness bar)."""
        return sum(
            n for r, n in self.dropped_by_reason.items() if r not in INTENTIONAL_DROP_REASONS
        )


@dataclass
class LossLedger:
    """Collection of per-source ``DocLoss`` accumulators.

    All ``record_*`` methods create the ``DocLoss`` entry on first use (lazy init),
    so callers need not pre-register URIs.

    ``probe()`` emits per source_uri: ``empty_extractions``, ``truncated_calls``,
    ``items_dropped`` (the original SP_015 keys) plus ``lossy_drops`` (SP_024 — the gating
    subset). The key set is consumed by SP_015's check_smoke; coordinate any change there.
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

        kind in {"as_of", "subject_type", "link_verb", "link_invert",
                 "subject_type_fallback", "link_fallback"}  # last two: SP_025 recovery
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

        Shape (consumed by SP_015 check_smoke; ``lossy_drops`` added SP_024):
        {
            "<uri>": {
                "empty_extractions": int,
                "truncated_calls": int,
                "items_dropped": int,   # TOTAL drops, all reasons (observability)
                "lossy_drops": int,     # gating subset: genuine schema/grounding losses
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
                "lossy_drops": doc.lossy_drops,
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
