"""Render an ``AuditReport`` to text or a JSON-able dict (pure)."""

from __future__ import annotations

from typing import Any

from helixpay.audit.invariants import evidence_grounding
from helixpay.audit.models import AuditReport, ClaimRecord

_RULE = "=" * 72


def _sample_flags(r: ClaimRecord) -> str:
    flags: list[str] = []
    if r.subject_entity_id is None:
        flags.append("UNRESOLVED")
    if r.as_of is None:
        flags.append("no-as_of")
    if r.evidence_columns_present and r.source_chunk_id is not None and not r.evidence:
        flags.append("no-evidence")
    if r.evidence and r.chunk_text:
        # mirror the invariant's three-way split so the sample line never contradicts
        # the violations table (cosmetic non-verbatim is NOT "ungrounded").
        grounding = evidence_grounding(r.evidence, r.chunk_text)
        if grounding == "absent":
            flags.append("ungrounded")
        elif grounding == "normalized":
            flags.append("non-verbatim")
    return ("  !" + ",".join(flags)) if flags else ""


def format_report(report: AuditReport) -> str:
    lines = [_RULE, "HelixPay extraction audit", _RULE, "", "Row counts:"]
    for table, n in report.counts.items():
        lines.append(f"  {table:<16}{n:>9}")

    ev = (
        "present"
        if report.evidence_columns_present
        else "ABSENT (pre-SP_009 schema — evidence checks skipped)"
    )
    lines += [
        "",
        f"Evidence columns: {ev}",
        "",
        f"Invariant violations over {report.total_claims} live+superseded claims:",
    ]
    by_cat = report.violations_by_category()
    if not by_cat:
        lines.append("  (none)")
    else:
        sev_of = {v.category: v.severity.value for v in report.violations}
        for cat in sorted(by_cat, key=lambda c: (-by_cat[c], c)):
            lines.append(f"  [{sev_of[cat]:<5}] {cat:<26}{by_cat[cat]:>7}")
    lines.append(f"  => {report.error_count()} ERROR-level violation(s)")

    lines += ["", "Planted-trap checks:"]
    for t in report.traps:
        lines.append(f"  [{'PASS' if t.passed else 'FAIL'}] {t.name}")
        lines.append(f"         {t.detail}")

    lines += [
        "",
        f"Stratified audit sample ({len(report.sample)} claims to read by eye):",
    ]
    for r in report.sample:
        subj = r.subject_name or "<unresolved>"
        src = r.document_source_uri or "<no-source>"
        snippet = (r.evidence or r.chunk_text or "")[:90].replace("\n", " ")
        lines.append(
            f"  #{r.id} [{r.predicate}] {subj} = {r.object_value!r}  ({src}){_sample_flags(r)}"
        )
        if snippet:
            lines.append(f"        span: {snippet!r}")

    verdict = "CLEAN" if report.clean() else "ISSUES FOUND"
    lines += ["", _RULE, f"Verdict: {verdict}", _RULE]
    return "\n".join(lines)


def report_to_dict(report: AuditReport) -> dict[str, Any]:
    """A JSON-able summary (dates/ids only, no chunk bodies)."""
    return {
        "total_claims": report.total_claims,
        "counts": report.counts,
        "evidence_columns_present": report.evidence_columns_present,
        "violations_by_category": report.violations_by_category(),
        "error_count": report.error_count(),
        "traps": [
            {"name": t.name, "passed": t.passed, "detail": t.detail}
            for t in report.traps
        ],
        "sample_claim_ids": [r.id for r in report.sample],
        "clean": report.clean(),
    }


__all__ = ["format_report", "report_to_dict"]
