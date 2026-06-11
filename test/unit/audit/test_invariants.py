"""Invariant checks over hand-built ClaimRecords — pure, no DB."""

from __future__ import annotations

from datetime import date

from helixpay.audit.invariants import (
    evidence_grounding,
    is_suspicious,
    run_invariants,
)
from helixpay.audit.models import ClaimRecord, Severity


def _rec(**over) -> ClaimRecord:
    base = dict(
        id=1,
        subject_entity_id=10,
        subject_name="HelixPay",
        subject_type="other",
        predicate="revenue",
        object_value="SGD 14.2M",
        as_of=date(2026, 3, 31),
        confidence=0.9,
        superseded_by=None,
        source_chunk_id=100,
        document_id=5,
        chunk_text="Q1 2026 Revenue: SGD 14.2M as of 2026-03-31",
        document_source_uri="data/dash.html",
        evidence="Revenue: SGD 14.2M",
        char_start=8,
        char_end=26,
        evidence_columns_present=True,
    )
    base.update(over)
    return ClaimRecord(**base)


def _cats(records) -> dict[str, str]:
    return {v.category: v.severity.value for v in run_invariants(records)}


def test_clean_claim_has_no_violations():
    # the default offsets (8, 26) address the exact evidence span
    rec = _rec()
    assert rec.chunk_text[8:26] == "Revenue: SGD 14.2M"
    assert run_invariants([rec]) == []


def test_unresolved_subject_warns():
    cats = _cats([_rec(subject_entity_id=None, subject_name=None)])
    assert cats["unresolved_subject"] == Severity.warn.value


def test_dangling_chunk_ref_is_error():
    cats = _cats([_rec(chunk_text=None)])
    assert cats["dangling_chunk_ref"] == Severity.error.value


def test_seeded_claim_without_chunk_warns_not_errors():
    cats = _cats(
        [
            _rec(
                source_chunk_id=None,
                chunk_text=None,
                document_id=None,
                document_source_uri=None,
                evidence=None,
            )
        ]
    )
    assert cats["no_source_chunk"] == Severity.warn.value
    assert "dangling_chunk_ref" not in cats
    assert "no_evidence" not in cats  # no chunk → nothing to ground


def test_confidence_out_of_range_is_error():
    cats = _cats([_rec(confidence=1.4)])
    assert cats["confidence_out_of_range"] == Severity.error.value


def test_missing_as_of_warns():
    assert "no_as_of" in _cats([_rec(as_of=None)])


def test_evidence_not_in_chunk_is_error():
    cats = _cats([_rec(evidence="Revenue: SGD 99.9M", char_start=None, char_end=None)])
    assert cats["evidence_not_in_chunk"] == Severity.error.value


def test_offsets_mismatch_is_error():
    cats = _cats([_rec(char_start=0, char_end=5)])  # chunk[0:5] != evidence
    assert cats["offsets_mismatch_evidence"] == Severity.error.value


def test_value_not_in_evidence_warns():
    cats = _cats([_rec(object_value="SGD 99.9M", char_start=None, char_end=None)])
    assert cats["value_not_in_evidence"] == Severity.warn.value


def test_value_in_evidence_is_casefold_tolerant():
    # value cased differently from the span still counts as present (casefold match)
    rec = _rec(
        object_value="sgd 14.2m",
        evidence="Revenue: SGD 14.2M",
        char_start=None,
        char_end=None,
    )
    cats = _cats([rec])
    assert "value_not_in_evidence" not in cats


def test_superseded_rows_are_skipped():
    assert (
        run_invariants([_rec(superseded_by=2, subject_entity_id=None, as_of=None)])
        == []
    )


def test_evidence_checks_noop_on_pre_v2_schema():
    rec = _rec(evidence=None, evidence_columns_present=False)
    assert "no_evidence" not in _cats([rec])


def test_is_suspicious_flags_the_right_records():
    assert is_suspicious(_rec(subject_entity_id=None))
    assert is_suspicious(_rec(confidence=0.2))
    assert is_suspicious(_rec(as_of=None))
    assert is_suspicious(_rec(evidence=None))
    assert is_suspicious(
        _rec(evidence="not in the chunk at all", char_start=None, char_end=None)
    )
    assert not is_suspicious(_rec(char_start=9, char_end=27))


# --- SP_029: evidence three-way classification (cosmetic WARN vs genuine ERROR) ---


def test_evidence_grounding_three_way():
    chunk = "Revenue: SGD 14.2M as of 2026-03-31"
    assert evidence_grounding("Revenue: SGD 14.2M", chunk) == "exact"
    assert evidence_grounding("revenue: sgd 14.2m", chunk) == "normalized"  # case-only
    assert evidence_grounding("Revenue:  SGD 14.2M", chunk) == "normalized"  # whitespace
    assert evidence_grounding("Revenue: SGD 14.3M", chunk) == "absent"  # wrong digit
    assert evidence_grounding("anything", None) == "absent"  # dangling chunk
    assert evidence_grounding("", chunk) == "absent"  # empty never launders to a match


def test_case_only_mismatch_is_warn_not_error():
    # evidence lower-cased relative to the chunk: the span is right, only casing differs.
    cats = _cats([_rec(evidence="revenue: sgd 14.2m")])
    assert cats["evidence_not_verbatim"] == Severity.warn.value
    assert "evidence_not_in_chunk" not in cats


def test_whitespace_only_mismatch_is_warn_not_error():
    cats = _cats([_rec(evidence="Revenue:  SGD 14.2M", char_start=None, char_end=None)])
    assert cats["evidence_not_verbatim"] == Severity.warn.value
    assert "evidence_not_in_chunk" not in cats


def test_genuine_wrong_value_stays_error_not_laundered():
    # a wrong digit must NOT fold into a normalized match — stays a real ERROR.
    cats = _cats([_rec(evidence="Revenue: SGD 14.3M", char_start=None, char_end=None)])
    assert cats["evidence_not_in_chunk"] == Severity.error.value
    assert "evidence_not_verbatim" not in cats


def test_cosmetic_match_with_raw_offsets_warns_only_no_offset_error():
    # the producer stored RAW offsets (8:26 → "Revenue: SGD 14.2M") for a lower-cased
    # evidence span; the offset check is gated to the byte-exact path, so this must
    # produce exactly ONE warn and zero ERRORs (no double-report).
    cats = _cats([_rec(evidence="revenue: sgd 14.2m", char_start=8, char_end=26)])
    assert cats.get("evidence_not_verbatim") == Severity.warn.value
    assert "offsets_mismatch_evidence" not in cats
    assert "evidence_not_in_chunk" not in cats


def test_verbatim_evidence_with_wrong_offsets_is_error():
    # byte-exact evidence but the stored offsets point elsewhere → genuine offset bug.
    cats = _cats([_rec(char_start=0, char_end=5)])
    assert cats["offsets_mismatch_evidence"] == Severity.error.value
    assert "evidence_not_verbatim" not in cats


def test_empty_evidence_is_no_evidence_not_verbatim():
    cats = _cats([_rec(evidence="")])
    assert cats["no_evidence"] == Severity.warn.value
    assert "evidence_not_verbatim" not in cats
    assert "evidence_not_in_chunk" not in cats


def test_cosmetic_mismatch_is_not_suspicious():
    # a cosmetic case/whitespace variant must not be oversampled as "suspicious".
    assert not is_suspicious(_rec(evidence="revenue: sgd 14.2m"))


def test_evidence_reclassification_noop_on_pre_v2_schema():
    cats = _cats([_rec(evidence="revenue: sgd 14.2m", evidence_columns_present=False)])
    assert "evidence_not_verbatim" not in cats
    assert "evidence_not_in_chunk" not in cats
