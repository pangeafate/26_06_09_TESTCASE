"""Coerce module: normalise raw LLM items to frozen contracts before strict validation (SP_014).

Table-driven over every mapping rule.  A Coerced.item that is not None must always
validate against ClaimOut / RelationOut — the property test at the bottom asserts this.
"""

from __future__ import annotations

import pytest

from helixpay.ingest.extract.coerce import Coerced, coerce_item
from helixpay.ingest.extract.schemas import ClaimOut, RelationOut

# ─────────────────────────────────────────────────────────────────────────────
# as_of coercion — claims
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw_as_of, expected", [
    # Quarter → quarter-END (Q1=03-31, Q2=06-30, Q3=09-30, Q4=12-31)
    ("Q1 2026",       "2026-03-31"),
    ("Q2 2026",       "2026-06-30"),
    ("Q3 2026",       "2026-09-30"),
    ("Q4 2026",       "2026-12-31"),
    # Alternative orderings / spacing
    ("2026 Q1",       "2026-03-31"),
    ("2026 Q4",       "2026-12-31"),
    ("Q1 FY2026",     "2026-03-31"),
    ("Q3 FY2025",     "2025-09-30"),
    # Bare year
    ("2026",          "2026-12-31"),
    ("2025",          "2025-12-31"),
    # Already-ISO passthrough (no coercion)
    ("2026-03-31",    "2026-03-31"),
    ("2025-12-31",    "2025-12-31"),
    # None — no coercion, no drop
    (None,            None),
])
def test_as_of_coercion_claim(raw_as_of, expected):
    raw = {"subject": "HelixPay", "predicate": "ARR", "object_value": "1M"}
    if raw_as_of is not None:
        raw["as_of"] = raw_as_of
    result = coerce_item(raw, kind="claim")
    if expected is None:
        # no as_of key → item kept, no as_of in output
        assert result.item is not None
        assert result.item.get("as_of") is None
    else:
        assert result.item is not None, f"Expected item for as_of={raw_as_of!r}"
        assert result.item["as_of"] == expected


def test_as_of_already_iso_records_no_coercion():
    raw = {"subject": "HelixPay", "predicate": "ARR", "object_value": "1M", "as_of": "2026-03-31"}
    result = coerce_item(raw, kind="claim")
    assert "as_of" not in result.coercions


def test_as_of_quarter_records_coercion():
    raw = {"subject": "HelixPay", "predicate": "ARR", "object_value": "1M", "as_of": "Q1 2026"}
    result = coerce_item(raw, kind="claim")
    assert "as_of" in result.coercions


def test_as_of_bare_year_records_coercion():
    raw = {"subject": "HelixPay", "predicate": "ARR", "object_value": "1M", "as_of": "2026"}
    result = coerce_item(raw, kind="claim")
    assert "as_of" in result.coercions


def test_as_of_malformed_drops_with_reason():
    """Malformed ISO (not a valid date) should drop the item."""
    raw = {"subject": "HelixPay", "predicate": "ARR", "object_value": "1M", "as_of": "not-a-date"}
    result = coerce_item(raw, kind="claim")
    assert result.item is None
    assert result.drop_reason == "unparseable_as_of"


def test_as_of_malformed_mixed_text_drops():
    raw = {"subject": "HelixPay", "predicate": "ARR", "object_value": "1M", "as_of": "last quarter"}
    result = coerce_item(raw, kind="claim")
    assert result.item is None
    assert result.drop_reason == "unparseable_as_of"


# ─────────────────────────────────────────────────────────────────────────────
# subject_type coercion — claims only
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw_type, expected_type, coerced", [
    # Valid types — pass through unchanged
    ("person",    "person",    False),
    ("team",      "team",      False),
    ("customer",  "customer",  False),
    ("product",   "product",   False),
    ("metric",    "metric",    False),
    ("other",     "other",     False),
    # Case normalisation — kept, recorded as coerced only if changed
    ("Person",    "person",    True),
    ("METRIC",    "metric",    True),
    # Synonyms → other
    ("company",       "other", True),
    ("organization",  "other", True),
    ("org",           "other", True),
    ("subsidiary",    "other", True),
    ("business",      "other", True),
    ("firm",          "other", True),
    ("corporation",   "other", True),
    # None — leave absent (no drop)
    (None,        None,        False),
])
def test_subject_type_coercion(raw_type, expected_type, coerced):
    raw = {"subject": "HelixPay", "predicate": "ARR", "object_value": "1M"}
    if raw_type is not None:
        raw["subject_type"] = raw_type
    result = coerce_item(raw, kind="claim")
    assert result.item is not None, f"Unexpected drop for subject_type={raw_type!r}"
    if expected_type is None:
        assert result.item.get("subject_type") is None
    else:
        assert result.item["subject_type"] == expected_type
    if coerced:
        assert "subject_type" in result.coercions
    else:
        assert "subject_type" not in result.coercions


def test_unmappable_subject_type_drops():
    raw = {"subject": "HelixPay", "predicate": "ARR", "object_value": "1M", "subject_type": "wizard"}
    result = coerce_item(raw, kind="claim")
    assert result.item is None
    assert result.drop_reason == "unmappable_enum"


def test_unmappable_subject_type_role_drops():
    raw = {"subject": "CEO", "predicate": "title", "object_value": "CEO", "subject_type": "role"}
    result = coerce_item(raw, kind="claim")
    assert result.item is None
    assert result.drop_reason == "unmappable_enum"


# ─────────────────────────────────────────────────────────────────────────────
# link_type coercion — relations
# ─────────────────────────────────────────────────────────────────────────────

# --- manages → reports_to with inversion ---

def test_manages_inverts_from_to():
    """'A manages B' → B reports_to A (from=B, to=A)."""
    raw = {"from_entity": "Alice", "to_entity": "Bob", "link_type": "manages"}
    result = coerce_item(raw, kind="relation")
    assert result.item is not None
    assert result.item["link_type"] == "reports_to"
    assert result.item["from_entity"] == "Bob"   # inverted
    assert result.item["to_entity"] == "Alice"   # inverted
    assert "link_verb" in result.coercions
    assert "link_invert" in result.coercions


def test_manage_singular_inverts():
    raw = {"from_entity": "Alice", "to_entity": "Bob", "link_type": "manage"}
    result = coerce_item(raw, kind="relation")
    assert result.item is not None
    assert result.item["link_type"] == "reports_to"
    assert result.item["from_entity"] == "Bob"
    assert result.item["to_entity"] == "Alice"


# --- reports_to / managed by variants — no invert ---

@pytest.mark.parametrize("verb", [
    "reports_to",
    "reports to",
    "report to",
    "reports into",
    "managed by",
    "is managed by",
])
def test_reports_to_variants_no_invert(verb):
    raw = {"from_entity": "Alice", "to_entity": "Bob", "link_type": verb}
    result = coerce_item(raw, kind="relation")
    assert result.item is not None
    assert result.item["link_type"] == "reports_to"
    # Direction unchanged: Alice still from, Bob still to
    assert result.item["from_entity"] == "Alice"
    assert result.item["to_entity"] == "Bob"
    assert "link_invert" not in result.coercions


# --- leads → dotted_line_to, NEVER reports_to (direction corrected in Stage-5) ---

@pytest.mark.parametrize("verb", ["leads", "lead", "functional lead"])
def test_leads_superiority_phrasing_inverts_to_dotted_line(verb):
    # "Alice leads Bob" → Alice is the functional superior → from=subordinate(Bob)→to=superior(Alice).
    # Same superiority-verb inversion as "manages"; type is dotted_line_to (functional), NOT reports_to.
    raw = {"from_entity": "Alice", "to_entity": "Bob", "link_type": verb}
    result = coerce_item(raw, kind="relation")
    assert result.item is not None
    assert result.item["link_type"] == "dotted_line_to"
    assert result.item["from_entity"] == "Bob"   # inverted (subordinate first)
    assert result.item["to_entity"] == "Alice"   # inverted (superior)
    assert "link_invert" in result.coercions


@pytest.mark.parametrize("verb", [
    "dotted line",
    "dotted-line",
    "dotted line to",
    "dotted-line to",
    "dotted_line_to",
])
def test_dotted_line_subordinate_phrasing_no_invert(verb):
    # "A dotted-line to B" is already subordinate→superior — no inversion.
    raw = {"from_entity": "Alice", "to_entity": "Bob", "link_type": verb}
    result = coerce_item(raw, kind="relation")
    assert result.item is not None
    assert result.item["link_type"] == "dotted_line_to"
    assert result.item["from_entity"] == "Alice"
    assert result.item["to_entity"] == "Bob"
    assert "link_invert" not in result.coercions


def test_leads_is_never_reports_to():
    """Critical (the invariant the plan cared about): 'leads' is dotted_line_to, NEVER
    reports_to — even though, post-Stage-5, its direction is correctly inverted."""
    raw = {"from_entity": "Alice", "to_entity": "Bob", "link_type": "leads"}
    result = coerce_item(raw, kind="relation")
    assert result.item is not None
    assert result.item["link_type"] == "dotted_line_to"
    assert result.item["link_type"] != "reports_to"


def test_ambiguous_multi_quarter_as_of_drops():
    """Stage-5 L1: two quarter tokens in one as_of is ambiguous — drop, never guess."""
    raw = {"subject": "X", "predicate": "p", "object_value": "v", "as_of": "Q1 2026 Q2 2026"}
    result = coerce_item(raw, kind="claim")
    assert result.item is None
    assert result.drop_reason == "unparseable_as_of"


# --- member_of / owns / mentions — no invert ---

@pytest.mark.parametrize("verb, expected", [
    ("member of",  "member_of"),
    ("member_of",  "member_of"),
    ("part of",    "member_of"),
    ("part_of",    "member_of"),
    ("belongs to", "member_of"),
    ("owns",       "owns"),
    ("own",        "owns"),
    ("owner of",   "owns"),
    ("mentions",   "mentions"),
    ("mention",    "mentions"),
    ("references", "mentions"),
])
def test_other_link_verbs_no_invert(verb, expected):
    raw = {"from_entity": "Alice", "to_entity": "Bob", "link_type": verb}
    result = coerce_item(raw, kind="relation")
    assert result.item is not None
    assert result.item["link_type"] == expected
    assert result.item["from_entity"] == "Alice"
    assert result.item["to_entity"] == "Bob"


def test_link_verb_coercion_records_link_verb():
    """Any verb that changes the canonical type records 'link_verb'."""
    raw = {"from_entity": "Alice", "to_entity": "Bob", "link_type": "member of"}
    result = coerce_item(raw, kind="relation")
    assert "link_verb" in result.coercions


def test_already_canonical_link_type_no_coercion():
    """An already-canonical link_type records no coercions."""
    raw = {"from_entity": "Alice", "to_entity": "Bob", "link_type": "reports_to"}
    result = coerce_item(raw, kind="relation")
    assert result.item is not None
    assert "link_verb" not in result.coercions


def test_unmappable_link_verb_drops():
    raw = {"from_entity": "Alice", "to_entity": "Bob", "link_type": "advises"}
    result = coerce_item(raw, kind="relation")
    assert result.item is None
    assert result.drop_reason == "unmappable_enum"


def test_none_link_type_drops():
    raw = {"from_entity": "Alice", "to_entity": "Bob"}
    result = coerce_item(raw, kind="relation")
    assert result.item is None
    assert result.drop_reason == "unmappable_enum"


# ─────────────────────────────────────────────────────────────────────────────
# Direction contrast: manages vs managed-by
# ─────────────────────────────────────────────────────────────────────────────

def test_manages_a_b_inverts_but_managed_by_a_b_does_not():
    """'A manages B' → from=B, to=A; 'A managed by B' → from=A, to=B (B is manager)."""
    manages = coerce_item({"from_entity": "a", "to_entity": "b", "link_type": "manages"}, "relation")
    managed_by = coerce_item({"from_entity": "a", "to_entity": "b", "link_type": "managed by"}, "relation")

    assert manages.item["from_entity"] == "b"    # inverted
    assert manages.item["to_entity"] == "a"      # inverted

    assert managed_by.item["from_entity"] == "a"  # not inverted
    assert managed_by.item["to_entity"] == "b"    # not inverted

    assert manages.item["link_type"] == "reports_to"
    assert managed_by.item["link_type"] == "reports_to"


# ─────────────────────────────────────────────────────────────────────────────
# Property: coerced item always validates against frozen schema or is None
# ─────────────────────────────────────────────────────────────────────────────

def _all_claim_raws():
    """Yield raw claim dicts exercising coerce paths."""
    yield {"subject": "HelixPay", "predicate": "ARR", "object_value": "1M", "as_of": "Q1 2026", "subject_type": "company"}
    yield {"subject": "HelixPay", "predicate": "ARR", "object_value": "1M", "as_of": "2026"}
    yield {"subject": "X", "predicate": "p", "subject_type": "wizard"}
    yield {"subject": "X", "predicate": "p", "as_of": "bad-date"}
    yield {"subject": "X", "predicate": "p", "subject_type": "person", "as_of": "Q3 2025"}


def _all_relation_raws():
    yield {"from_entity": "a", "to_entity": "b", "link_type": "manages"}
    yield {"from_entity": "a", "to_entity": "b", "link_type": "leads"}
    yield {"from_entity": "a", "to_entity": "b", "link_type": "advises"}
    yield {"from_entity": "a", "to_entity": "b", "link_type": "reports_to"}
    yield {"from_entity": "a", "to_entity": "b", "link_type": "member of"}


@pytest.mark.parametrize("raw", list(_all_claim_raws()))
def test_coerced_claim_validates_or_is_none(raw):
    result = coerce_item(raw, kind="claim")
    if result.item is not None:
        # Must not raise
        ClaimOut.model_validate(result.item)


@pytest.mark.parametrize("raw", list(_all_relation_raws()))
def test_coerced_relation_validates_or_is_none(raw):
    result = coerce_item(raw, kind="relation")
    if result.item is not None:
        RelationOut.model_validate(result.item)


# ─────────────────────────────────────────────────────────────────────────────
# as_of on relations
# ─────────────────────────────────────────────────────────────────────────────

def test_as_of_coercion_on_relation():
    raw = {"from_entity": "Alice", "to_entity": "Bob", "link_type": "reports_to", "as_of": "Q1 2026"}
    result = coerce_item(raw, kind="relation")
    assert result.item is not None
    assert result.item["as_of"] == "2026-03-31"
    assert "as_of" in result.coercions


def test_as_of_bad_on_relation_drops():
    raw = {"from_entity": "Alice", "to_entity": "Bob", "link_type": "reports_to", "as_of": "whenever"}
    result = coerce_item(raw, kind="relation")
    assert result.item is None
    assert result.drop_reason == "unparseable_as_of"
