"""Whole-corpus invariant checks (pure functions over ``ClaimRecord``).

Each check returns the violations it found for one claim, so the sweep is just a flat
map over every live claim. The checks encode the properties the research flagged
(``research/provenance-evidence-and-ux-pipeline-design.md``): evidence must verbatim
support the value, provenance must trace to a real document, a subject is resolved or
honestly NULL (never a silent pick), predicates canonicalize. Superseded rows are
history, not live provenance, so most checks skip them.
"""

from __future__ import annotations

from typing import Iterable, Literal

from helixpay.audit.models import ClaimRecord, Severity, Violation
from helixpay.ingest.normalize import normalize_value


def _v(rec: ClaimRecord, category: str, severity: Severity, detail: str) -> Violation:
    return Violation(
        claim_id=rec.id, category=category, severity=severity, detail=detail
    )


def _normalize_span(s: str) -> str:
    """Casefold + collapse every (unicode) whitespace run to a single space.

    Pinned to case + whitespace ONLY — deliberately NOT the looser
    ``grounding._norm_text`` (which also folds punctuation), and never the shared
    ``ingest.normalize`` (8 callers incl. the eval matcher). Folding only case and
    whitespace preserves character identity and order, so a genuinely-wrong span
    (different digits/words, e.g. ``14.2M`` vs ``14.3M``) can never launder into a
    match — it stays ``absent`` → ERROR.

    COUPLING: an auditor must be no looser than the producer it audits. This mirrors
    the case/whitespace tolerance of ``ingest.extract.grounding.locate_span`` (its
    ``\\s+`` / ``IGNORECASE`` path, which stores RAW offsets) but stays stricter than its
    ``_norm_text``. If ``locate_span`` ever widens its tolerance, revisit this — pointing
    the audit at the producer's normalizer would let real wrong-value spans launder to WARN.
    """
    return " ".join(s.split()).casefold()


def evidence_grounding(
    evidence: str, chunk_text: str | None
) -> Literal["exact", "normalized", "absent"]:
    """Three-way verdict on whether ``evidence`` is grounded in ``chunk_text``.

    - ``exact``: byte-exact substring — the provenance-v2 ideal (verbatim span).
    - ``normalized``: substring only after casefold + whitespace-collapse. The producer
      ``ingest.extract.grounding.locate_span`` tolerates exactly this (its ``\\s+`` /
      ``IGNORECASE`` path) and stores RAW offsets, so this is a soft non-verbatim signal,
      not corruption.
    - ``absent``: not present even normalized — a genuine grounding failure.

    The single source of truth for the classification, shared by ``check_evidence``,
    ``is_suspicious`` and ``report._sample_flags`` so they never drift.
    """
    if not evidence or chunk_text is None:
        return "absent"
    if evidence in chunk_text:
        return "exact"
    if _normalize_span(evidence) in _normalize_span(chunk_text):
        return "normalized"
    return "absent"


def check_provenance(rec: ClaimRecord) -> list[Violation]:
    """A live claim must trace to a real chunk and a document with a source_uri."""
    if rec.superseded_by is not None:
        return []
    out: list[Violation] = []
    if rec.source_chunk_id is None:
        # Seeded/back-filled facts legitimately lack a chunk — a soft signal, not a break.
        out.append(
            _v(
                rec,
                "no_source_chunk",
                Severity.warn,
                f"{rec.predicate!r} has no source chunk (seeded or back-filled)",
            )
        )
    elif rec.chunk_text is None:
        out.append(
            _v(
                rec,
                "dangling_chunk_ref",
                Severity.error,
                f"references chunk {rec.source_chunk_id} that does not exist",
            )
        )
    if rec.source_chunk_id is not None and rec.document_source_uri is None:
        out.append(
            _v(
                rec,
                "no_document_source",
                Severity.error,
                "source chunk does not join to a document source_uri",
            )
        )
    return out


def check_resolution(rec: ClaimRecord) -> list[Violation]:
    """An unresolved subject is the recall gap made visible (company-metric facts that
    never matched the roster). WARN, not ERROR — NULL is the honest 'no silent pick'."""
    if rec.superseded_by is not None:
        return []
    if rec.subject_entity_id is None:
        return [
            _v(
                rec,
                "unresolved_subject",
                Severity.warn,
                f"{rec.predicate!r} did not resolve its subject to any entity",
            )
        ]
    return []


def check_confidence(rec: ClaimRecord) -> list[Violation]:
    if rec.confidence is None:
        return []
    if not 0.0 <= rec.confidence <= 1.0:
        return [
            _v(
                rec,
                "confidence_out_of_range",
                Severity.error,
                f"confidence={rec.confidence} outside [0, 1]",
            )
        ]
    return []


def check_as_of(rec: ClaimRecord) -> list[Violation]:
    """Without an as_of the claim's staleness can't be judged — the whole point of a
    temporal ontology. Soft signal."""
    if rec.superseded_by is not None:
        return []
    if rec.as_of is None:
        return [_v(rec, "no_as_of", Severity.warn, f"{rec.predicate!r} has no as_of")]
    return []


def check_evidence(rec: ClaimRecord) -> list[Violation]:
    """Grounding: the persisted evidence span must be a verbatim slice of the chunk, the
    offsets must address that exact slice, and the asserted value must appear inside it.
    No-ops on a pre-SP_009 schema and on chunk-less (seeded) claims."""
    if not rec.evidence_columns_present or rec.superseded_by is not None:
        return []
    if rec.source_chunk_id is None:
        return []  # nothing to ground against
    out: list[Violation] = []
    if not rec.evidence:
        out.append(
            _v(
                rec,
                "no_evidence",
                Severity.warn,
                f"{rec.predicate!r} has a source chunk but no persisted evidence span",
            )
        )
        return out
    grounding = evidence_grounding(rec.evidence, rec.chunk_text)
    if grounding == "absent":
        # Only assert absence when the chunk actually exists (a dangling chunk is
        # check_provenance's ERROR, not double-reported here).
        if rec.chunk_text is not None:
            out.append(
                _v(
                    rec,
                    "evidence_not_in_chunk",
                    Severity.error,
                    "evidence is not a substring of its chunk even after "
                    "case/whitespace normalization",
                )
            )
    elif grounding == "normalized":
        # The span is right but stored non-verbatim (the producer's case/whitespace-
        # tolerant locator kept raw offsets) — a soft quality signal, not corruption.
        out.append(
            _v(
                rec,
                "evidence_not_verbatim",
                Severity.warn,
                "evidence matches its chunk only after case/whitespace normalization "
                "(offsets stored raw; not byte-verbatim)",
            )
        )
    elif (
        # grounding == "exact" → the evidence IS a verbatim slice, so the stored offsets
        # must address it byte-for-byte; a mismatch here is a genuine stale-offset bug.
        rec.char_start is not None
        and rec.char_end is not None
        and rec.chunk_text is not None
        and rec.chunk_text[rec.char_start : rec.char_end] != rec.evidence
    ):
        out.append(
            _v(
                rec,
                "offsets_mismatch_evidence",
                Severity.error,
                f"chunk[{rec.char_start}:{rec.char_end}] does not equal the verbatim evidence span",
            )
        )
    if rec.object_value:
        val_text, _ = normalize_value(rec.object_value)
        ev_text, _ = normalize_value(rec.evidence)
        raw_in = rec.object_value.casefold() in rec.evidence.casefold()
        norm_in = bool(val_text) and val_text in ev_text
        if not (raw_in or norm_in):
            out.append(
                _v(
                    rec,
                    "value_not_in_evidence",
                    Severity.warn,
                    f"object_value {rec.object_value!r} not found in its evidence span",
                )
            )
    return out


ALL_CHECKS = (
    check_provenance,
    check_resolution,
    check_confidence,
    check_as_of,
    check_evidence,
)


def run_invariants(records: Iterable[ClaimRecord]) -> list[Violation]:
    out: list[Violation] = []
    for rec in records:
        for check in ALL_CHECKS:
            out.extend(check(rec))
    return out


def is_suspicious(rec: ClaimRecord) -> bool:
    """Records worth oversampling in the manual audit: weak grounding, unresolved
    subject, low confidence, missing as_of, or evidence that doesn't contain the value.
    Random sampling over-weights the easy middle; this is where the bugs hide."""
    if rec.superseded_by is not None:
        return False
    if rec.subject_entity_id is None:
        return True
    if rec.confidence is not None and rec.confidence < 0.5:
        return True
    if rec.as_of is None:
        return True
    if (
        rec.evidence_columns_present
        and rec.source_chunk_id is not None
        and not rec.evidence
    ):
        return True
    if (
        rec.evidence
        and rec.chunk_text
        and evidence_grounding(rec.evidence, rec.chunk_text) == "absent"
    ):
        # genuinely ungrounded is worth a human read; a cosmetic case/whitespace
        # variant (normalized match) is not — it would drown the sample.
        return True
    return False


__all__ = ["ALL_CHECKS", "run_invariants", "is_suspicious", "evidence_grounding"] + [
    c.__name__ for c in ALL_CHECKS
]
