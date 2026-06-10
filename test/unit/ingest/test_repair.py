"""Layer-0 attribution repair (SP_019): a known-company-metric typed as the *subject*
is re-attributed to the document's primary entity, with the metric moved to the predicate.

Conservative by construction: fires ONLY for ``subject_type == "metric"`` whose subject is a
known company metric (period-qualifier aware), and is a strict no-op otherwise — so a
regional/unknown metric ("HelixPay Brasil revenue") is never merged into the company. The
strings below are the actual surface forms observed in the SP_015 ``.replay-cache/`` audit.
"""

from __future__ import annotations

from helixpay.contracts import EntityType
from helixpay.ingest.extract.schemas import ClaimOut
from helixpay.ingest.repair import is_known_metric, repair_metric_subject

PRIMARY = "HelixPay"


def _claim(subject, subject_type, predicate, value="x", as_of=None):
    return ClaimOut(subject=subject, subject_type=subject_type, predicate=predicate,
                    object_value=value, as_of=as_of)


# --------------------------------------------------------------------------- #
# is_known_metric — period-aware gate (HIGH-1)
# --------------------------------------------------------------------------- #
def test_known_metric_recognises_period_qualified_subject():
    assert is_known_metric("Q1 2026 Revenue") is True   # strips "Q1 2026 " -> revenue
    assert is_known_metric("Revenue") is True
    assert is_known_metric("Aggregate NPS") is True      # alias of nps


def test_known_metric_excludes_company_and_regional_and_empty():
    assert is_known_metric("HelixPay") is False          # company name, not a metric (L2's job)
    assert is_known_metric("HelixPay Brasil revenue") is False  # regional -> never merged
    assert is_known_metric("") is False                  # L-3 empty contract


def test_known_metric_excludes_milestone_predicates_with_common_word_aliases():
    # HIGH-1: ga_target/completion_target aliases ("launch", "cutover", "completion") belong to
    # a project/product (e.g. Project Confluence's GA), NOT the company — must NOT trigger repair.
    assert is_known_metric("launch") is False
    assert is_known_metric("cutover") is False
    assert is_known_metric("completion") is False
    assert is_known_metric("go live") is False


def test_known_metric_excludes_pure_period_tokens():
    # HIGH-2: a bare period token strips to empty and must not be treated as a metric.
    assert is_known_metric("2026") is False
    assert is_known_metric("FY") is False
    assert is_known_metric("Q1 2026") is False


# --------------------------------------------------------------------------- #
# repair_metric_subject — re-attribution
# --------------------------------------------------------------------------- #
def test_repairs_period_qualified_metric_subject_to_company():
    # exact dashboard cache shape
    c = _claim("Q1 2026 Revenue", "metric", "Q1 2026 Revenue (SGD)", "SGD 14.2M", "2026-04-21")
    out = repair_metric_subject(c, primary_entity=PRIMARY)
    assert out.subject == PRIMARY
    assert out.subject_type == EntityType.other.value
    # predicate is not itself a known metric ("...(SGD)"), so the subject metric moves in;
    # downstream canonical_predicate strips it to "revenue".
    assert out.predicate == "Q1 2026 Revenue"
    assert out.object_value == "SGD 14.2M"  # value/as_of untouched here


def test_repairs_aggregate_nps_keeping_alias_predicate():
    c = _claim("Aggregate NPS", "metric", "Aggregate NPS", "47", "2026-04-21")
    out = repair_metric_subject(c, primary_entity=PRIMARY)
    assert out.subject == PRIMARY and out.subject_type == "other"
    assert out.predicate == "Aggregate NPS"  # already a known alias -> kept


def test_existing_known_metric_predicate_wins_over_subject():
    # M-1 case 2: predicate is a known alias (arr); it wins over the subject.
    c = _claim("Revenue", "metric", "annual recurring revenue", "SGD 51M")
    out = repair_metric_subject(c, primary_entity=PRIMARY)
    assert out.predicate == "annual recurring revenue"  # arr alias kept, not "Revenue"


def test_non_metric_predicate_is_replaced_by_subject():
    # M-1 case 1: predicate "Q1 2026" is not a metric -> subject moves into predicate.
    c = _claim("Revenue", "metric", "Q1 2026", "SGD 14.2M")
    out = repair_metric_subject(c, primary_entity=PRIMARY)
    assert out.predicate == "Revenue"


# --------------------------------------------------------------------------- #
# no-op cases — the safety surface
# --------------------------------------------------------------------------- #
def test_noop_when_subject_type_not_metric():
    c = _claim("HelixPay", "other", "revenue", "SGD 14.2M")
    assert repair_metric_subject(c, primary_entity=PRIMARY) is c  # unchanged identity


def test_noop_for_regional_metric_no_false_merge():
    # the planted Brasil value must NOT collapse onto the company.
    c = _claim("HelixPay Brasil revenue", "metric", "Brasil revenue", "SGD 4.8M")
    out = repair_metric_subject(c, primary_entity=PRIMARY)
    assert out is c and out.subject == "HelixPay Brasil revenue"


def test_noop_for_company_name_mistyped_metric():
    # "HelixPay" mis-typed metric is L2's case (seeded-snap), not L0's — left untouched.
    c = _claim("HelixPay", "metric", "revenue", "SGD 14.2M")
    out = repair_metric_subject(c, primary_entity=PRIMARY)
    assert out is c


def test_company_type_constant_is_a_real_entity_type():
    # L-1: the hardcoded "other" must equal EntityType.other.value.
    c = _claim("Revenue", "metric", "revenue", "x")
    out = repair_metric_subject(c, primary_entity=PRIMARY)
    assert out.subject_type in {t.value for t in EntityType}


def test_pure_no_repo_calls():
    # repair takes no repo and must not need one (pure transform).
    c = _claim("Revenue", "metric", "revenue", "x")
    out = repair_metric_subject(c, primary_entity=PRIMARY)
    assert out.subject == PRIMARY
