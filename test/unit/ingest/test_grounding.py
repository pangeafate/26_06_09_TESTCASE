"""Evidence-span grounding gate: flag-and-penalize, never drop (validated narrowing).

Checks that the value the model claims is actually restorable from its cited evidence
(and the span from the chunk). ``as_of`` is intentionally NOT graded (it is document-level
on dashboards/emails). Ungrounded claims are flagged, not dropped — dashboard facts are
split across DOM nodes and a hard drop would nuke recall on the planted contradictions.
"""

from __future__ import annotations

from helixpay.ingest.extract.grounding import GRADE_UNGROUNDED, grade, locate_span
from helixpay.ingest.extract.schemas import ClaimOut

_GROUNDED = {"exact", "value_only"}


def _c(object_value, evidence):
    return ClaimOut(subject="HelixPay", predicate="revenue", object_value=object_value, evidence=evidence)


def test_exact_prose_match():
    chunk = "Q1 closed at SGD 14.2M against a 16M plan (−11%)."
    assert grade(_c("14.2M", "Q1 closed at SGD 14.2M against a 16M plan"), chunk) == "exact"


def test_dashboard_split_dom_nodes_is_grounded_not_dropped():
    # value + label live in separate DOM nodes; the model's reconstructed evidence is still
    # recognized as grounded (exact via token-overlap, or value_only) — the key point is it
    # is NOT ungrounded, so it survives the gate (recall on the planted contradiction).
    chunk = "<td>Q1 2026 Revenue (SGD)</td> ... <td>14.2M</td> ... As of 2026-04-21"
    assert grade(_c("14.2M", "Q1 2026 Revenue (SGD): 14.2M"), chunk) in _GROUNDED


def test_heavily_paraphrased_span_with_right_value_is_value_only():
    # evidence shares the value but few words with the chunk -> span_in_chunk fails the
    # token-overlap floor, yet the value is restorable -> value_only (kept, not penalized)
    chunk = "Topline came to 14.2M for the period."
    assert grade(_c("14.2M", "ARR figure reported as 14.2M total annual"), chunk) == "value_only"


def test_currency_and_unicode_minus_match_numerically():
    chunk = "EBITDA Q1 (SGD) −2.1M vs −3.4M in Q1 25."
    assert grade(_c("−2.1M", "EBITDA Q1 (SGD) −2.1M vs −3.4M in Q1 25"), chunk) == "exact"


def test_brl_scale_match():
    chunk = "Brasil (BRL) R$22.0M against R$28.0M plan."
    assert grade(_c("R$22.0M", "Brasil (BRL) R$22.0M against R$28.0M plan"), chunk) == "exact"


def test_hallucinated_number_is_ungrounded():
    chunk = "Q1 revenue closed at SGD 14.2M."
    # evidence is a real span but the claimed value (14.5M) is not in it
    assert grade(_c("14.5M", "Q1 revenue closed at SGD 14.2M"), chunk) == "ungrounded"


def test_missing_evidence_is_ungrounded():
    assert grade(_c("14.2M", None), "anything") == "ungrounded"
    assert grade(_c("14.2M", "   "), "anything") == "ungrounded"


def test_non_numeric_status_text_path():
    chunk = "Confluence GA is re-baselining from end-of-Q2 to end-of-Q3."
    assert grade(_c("end of Q3", "re-baselining ... to end-of-Q3"), chunk) in {"exact", "value_only"}


def test_label_year_not_confused_with_value():
    # object "Q1 2026" is non-numeric (whole-string gate) -> text path, a stray 2026 in the
    # span must not numerically satisfy it
    chunk = "Reporting period: Q1 2026 dashboard."
    assert grade(_c("Q1 2026", "Reporting period: Q1 2026 dashboard"), chunk) == "exact"


def test_small_integer_not_falsely_grounded_by_quarter_label():
    # object "1" must NOT ground against the "1" inside "Q1" (sub-digit false match)
    chunk = "Q1 2026 revenue grew this period."
    assert grade(_c("1", "Q1 2026 revenue grew"), chunk) == GRADE_UNGROUNDED


def test_object_value_none_is_grounded_when_span_present():
    # a relation-ish claim with no value can't fabricate a number
    chunk = "Sara Wijaya reports to Daniel Tan."
    assert grade(_c(None, "Sara Wijaya reports to Daniel Tan"), chunk) == "exact"


# --------------------------------------------------------------------------- #
# locate_span (SP_011): raw char offsets of the evidence span into the chunk text
# --------------------------------------------------------------------------- #
def test_locate_span_exact_substring():
    chunk = "Q1 closed at SGD 14.2M against a 16M plan (−11%)."
    evidence = "SGD 14.2M against a 16M plan"
    span = locate_span(evidence, chunk)
    assert span is not None
    start, end = span
    assert chunk[start:end] == evidence  # offsets index the raw chunk


def test_locate_span_case_and_whitespace_tolerant_keeps_raw_offsets():
    # the model's evidence differs in case + whitespace from the chunk; offsets must still
    # land on the raw chunk text (not a normalized copy)
    chunk = "Sara Wijaya  reports to   Daniel Tan, VP Eng."
    evidence = "sara wijaya reports to daniel tan"
    span = locate_span(evidence, chunk)
    assert span is not None
    start, end = span
    assert chunk[start:end].lower().split() == evidence.split()


def test_locate_span_paraphrase_not_a_substring_returns_none():
    # heavily paraphrased evidence (value_only grade) is not a contiguous span → no offsets
    chunk = "Topline came to 14.2M for the period."
    evidence = "ARR figure reported as 14.2M total annual"
    assert locate_span(evidence, chunk) is None


def test_locate_span_empty_or_none_evidence_is_none():
    assert locate_span(None, "anything") is None
    assert locate_span("   ", "anything") is None
    assert locate_span("", "") is None


def test_locate_span_ambiguous_repeated_whitespace_span_returns_none():
    # the whitespace-normalized span occurs twice (differing internal spacing each time),
    # so the leftmost regex match could anchor the wrong occurrence → degrade to None
    chunk = "reports to  Daniel; later, reports to   Daniel again"
    evidence = "reports to daniel"
    assert locate_span(evidence, chunk) is None
