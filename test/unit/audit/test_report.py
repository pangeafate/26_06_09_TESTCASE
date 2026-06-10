"""Renderers for an AuditReport — format_report (text) and report_to_dict (JSON-able).

Pure, no DB: an AuditReport is assembled from frozen dataclasses in-memory (there is no
reusable AuditReport factory, so it is built here from ClaimRecord/Violation/TrapResult).
"""

from __future__ import annotations

from datetime import date

from helixpay.audit.models import (
    AuditReport,
    ClaimRecord,
    Severity,
    TrapResult,
    Violation,
)
from helixpay.audit.report import format_report, report_to_dict


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


def _report(**over) -> AuditReport:
    base = dict(
        total_claims=3,
        counts={"claims": 3, "links": 1},
        violations=[],
        sample=[_rec()],
        traps=[TrapResult(name="two_marias_distinct", passed=True, detail="2 found")],
        evidence_columns_present=True,
    )
    base.update(over)
    return AuditReport(**base)


# --------------------------------------------------------------------------- #
# format_report — text rendering
# --------------------------------------------------------------------------- #

def test_format_report_includes_title_and_row_counts():
    text = format_report(_report())
    assert "HelixPay extraction audit" in text
    assert "claims" in text and "3" in text
    assert "links" in text


def test_format_report_reports_evidence_columns_present():
    text = format_report(_report(evidence_columns_present=True))
    assert "Evidence columns: present" in text


def test_format_report_reports_evidence_columns_absent():
    text = format_report(_report(evidence_columns_present=False))
    assert "ABSENT" in text


def test_format_report_lists_no_violations_as_none():
    text = format_report(_report(violations=[]))
    assert "(none)" in text
    assert "=> 0 ERROR-level violation(s)" in text


def test_format_report_lists_violation_category_with_severity():
    v = Violation(claim_id=1, category="dangling_chunk_ref", severity=Severity.error, detail="x")
    text = format_report(_report(violations=[v]))
    assert "dangling_chunk_ref" in text
    assert "error" in text
    assert "=> 1 ERROR-level violation(s)" in text


def test_format_report_shows_trap_pass_and_fail():
    traps = [
        TrapResult(name="trap_ok", passed=True, detail="all good"),
        TrapResult(name="trap_bad", passed=False, detail="collapsed"),
    ]
    text = format_report(_report(traps=traps))
    assert "[PASS] trap_ok" in text
    assert "[FAIL] trap_bad" in text


def test_format_report_verdict_clean_when_no_errors_and_traps_pass():
    text = format_report(_report(violations=[], traps=[TrapResult("t", True, "ok")]))
    assert "Verdict: CLEAN" in text


def test_format_report_verdict_issues_when_a_trap_fails():
    text = format_report(_report(traps=[TrapResult("t", False, "broke")]))
    assert "Verdict: ISSUES FOUND" in text


def test_format_report_flags_unresolved_subject_in_sample():
    text = format_report(_report(sample=[_rec(subject_entity_id=None, subject_name=None)]))
    assert "UNRESOLVED" in text
    assert "<unresolved>" in text


def test_format_report_flags_ungrounded_evidence_in_sample():
    # evidence text not contained in chunk_text → ungrounded flag
    text = format_report(_report(sample=[_rec(evidence="NOT IN CHUNK", chunk_text="other body")]))
    assert "ungrounded" in text


# --------------------------------------------------------------------------- #
# report_to_dict — JSON-able summary
# --------------------------------------------------------------------------- #

def test_report_to_dict_has_expected_keys():
    d = report_to_dict(_report())
    assert set(d) == {
        "total_claims", "counts", "evidence_columns_present",
        "violations_by_category", "error_count", "traps",
        "sample_claim_ids", "clean",
    }


def test_report_to_dict_summarizes_counts_and_sample_ids():
    d = report_to_dict(_report(sample=[_rec(id=7), _rec(id=9)]))
    assert d["total_claims"] == 3
    assert d["counts"] == {"claims": 3, "links": 1}
    assert d["sample_claim_ids"] == [7, 9]


def test_report_to_dict_error_count_and_clean_flag():
    v = Violation(claim_id=1, category="dangling_chunk_ref", severity=Severity.error, detail="x")
    d = report_to_dict(_report(violations=[v]))
    assert d["error_count"] == 1
    assert d["violations_by_category"] == {"dangling_chunk_ref": 1}
    assert d["clean"] is False


def test_report_to_dict_clean_true_when_no_errors_and_traps_pass():
    d = report_to_dict(_report(violations=[], traps=[TrapResult("t", True, "ok")]))
    assert d["clean"] is True


def test_report_to_dict_carries_no_chunk_bodies():
    # the dict is a summary — chunk text / evidence spans must not leak into it
    d = report_to_dict(_report(sample=[_rec(chunk_text="SECRET BODY", evidence="SECRET EV")]))
    assert "SECRET BODY" not in repr(d)
    assert "SECRET EV" not in repr(d)
