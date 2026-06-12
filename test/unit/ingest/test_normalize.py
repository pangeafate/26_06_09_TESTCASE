"""Shared value-normalization util (SP_009).

This is the one canonical normalizer the contradiction detector, the eval matcher,
and consensus rollup will import (in SP_011/SP_013) so the three never drift. The
contract pinned at the pre-impl review:

* ``normalize_value(value) -> (canonical_text, numeric_or_None)``.
* The numeric (float) path is gated to *pure* numbers only — a unit-bearing quantity
  like ``"18 months"`` stays NON-numeric so it is compared as text, never as a bare
  magnitude. This preserves the deliberate behavior the contradiction detector relies
  on (durations/quarters/versions are not magnitudes) and the planted Q1 revenue/ARR
  conflict.
* Word-numbers ("eighteen") expand in the *text* form; magnitude words/suffixes
  ("million", "M", "K", "B") and approx markers ("~") fold in the *numeric* parse.
* ``~``/approx strips to the literal value with NO ``math.isclose`` tolerance widening.
"""

from __future__ import annotations

import pytest

from helixpay.ingest.normalize import normalize_value, values_conflict, values_equal


# --------------------------------------------------------------------------- #
# normalize_value return contract
# --------------------------------------------------------------------------- #
def test_none_and_empty():
    assert normalize_value(None) == ("", None)
    assert normalize_value("")[1] is None


# --- numeric words expand in TEXT, unit-bearing quantities stay non-numeric --- #
def test_numeric_word_expands_in_text_only():
    text, num = normalize_value("eighteen months")
    assert text == "18 months"
    assert num is None  # unit-bearing → NOT a bare magnitude


def test_eighteen_months_equiv_18_months():
    assert values_equal("eighteen months", "18 months") is True
    assert values_conflict("eighteen months", "18 months") is False


def test_eighteen_months_is_not_eighteen_days():
    # Same digit, different unit — MUST NOT collapse (the critical false-match trap).
    assert values_equal("eighteen months", "18 days") is False
    assert values_conflict("18 months", "18 days") is True


def test_18_months_vs_18M_conflict():
    # "18 months" (non-numeric text) vs "18M" (18,000,000) must conflict, never equate.
    assert values_conflict("18 months", "18M") is True


# --- labels with embedded digits stay non-numeric --- #
def test_quarter_labels_compare_as_text():
    assert normalize_value("Q1 2026")[1] is None
    assert normalize_value("Q2 2026")[1] is None
    assert values_conflict("Q1 2026", "Q2 2026") is True
    assert values_conflict("Q1 2026", "Q1 2026") is False


def test_version_string_not_numeric():
    assert normalize_value("version 2.1")[1] is None
    # abbreviated v-prefix form (no space) must also stay non-numeric — owns the case
    # the removed test_contradict.py::test_normalize_value_refuses_to_pull_digits_from_labels
    # used to pin (SP_030 Item 4 owner-consolidation).
    assert normalize_value("v1.0")[1] is None
    assert values_conflict("version 2.1", "version 2.0") is True


def test_compound_word_numbers_out_of_scope_stay_non_numeric():
    # "hundred" is deliberately NOT expanded (no full cardinal grammar) — it must not
    # accidentally equate "one hundred twenty" with 120.
    assert normalize_value("one hundred twenty")[1] is None
    assert values_conflict("one hundred twenty", "120") is True


# --------------------------------------------------------------------------- #
# currency + magnitude suffix/word folding (numeric path)
# --------------------------------------------------------------------------- #
def test_currency_and_magnitude_word():
    assert normalize_value("14.2 million")[1] == pytest.approx(14_200_000.0)
    assert normalize_value("SGD 14.2M")[1] == pytest.approx(14_200_000.0)
    assert values_conflict("SGD 14.2M", "14.2 million") is False


def test_real_currency_symbol():
    assert normalize_value("R$14.2M")[1] == pytest.approx(14_200_000.0)


def test_magnitude_suffix_variants():
    assert normalize_value("3K")[1] == pytest.approx(3_000.0)
    assert normalize_value("2b")[1] == pytest.approx(2_000_000_000.0)
    assert normalize_value("2bn")[1] == pytest.approx(2_000_000_000.0)
    assert normalize_value("1 thousand")[1] == pytest.approx(1_000.0)
    assert normalize_value("3 billion")[1] == pytest.approx(3_000_000_000.0)


def test_comma_thousands_separator():
    assert normalize_value("14,200,000")[1] == pytest.approx(14_200_000.0)
    assert values_conflict("14,200,000", "14.2M") is False


def test_trailing_zero_formatting():
    assert normalize_value("14200000.0")[1] == pytest.approx(14_200_000.0)
    assert values_conflict("14200000.0", "14200000") is False


# --------------------------------------------------------------------------- #
# approx markers strip to the literal value (NO tolerance widening)
# --------------------------------------------------------------------------- #
def test_approx_tilde_strips_to_exact_value():
    assert normalize_value("~18")[1] == pytest.approx(18.0)
    assert normalize_value("~14.2M")[1] == pytest.approx(14_200_000.0)
    assert values_conflict("~18", "18") is False
    assert values_conflict("~18", "17") is True  # no tolerance: 18 != 17 conflicts


def test_approx_words_strip():
    assert normalize_value("approximately 18")[1] == pytest.approx(18.0)
    assert values_conflict("approx 18", "18") is False


def test_est_abbreviation_is_not_an_approx_marker():
    # "est." (Latin "established") must NOT be stripped as an approx hedge — that would
    # mangle a founding-year value. It stays in the text and parses as non-numeric.
    text, num = normalize_value("est. 2015")
    assert num is None and "2015" in text and text.startswith("est")
    assert values_conflict("est. 2015", "2015") is True


# --------------------------------------------------------------------------- #
# sign / percent / unicode-minus
# --------------------------------------------------------------------------- #
def test_unicode_minus_equals_ascii_minus():
    assert normalize_value("−11%")[1] == pytest.approx(-11.0)
    assert values_conflict("−11%", "-11%") is False
    assert values_conflict("−11%", "11%") is True


def test_percent_values():
    assert normalize_value("100%")[1] == pytest.approx(100.0)
    assert normalize_value("-11%")[1] == pytest.approx(-11.0)


# --------------------------------------------------------------------------- #
# values_conflict guards: a missing value is not a competing fact
# --------------------------------------------------------------------------- #
def test_missing_value_is_not_a_conflict():
    assert values_conflict(None, "18") is False
    assert values_conflict("18", None) is False
    assert values_conflict(None, None) is False


def test_text_values_compare_casefold():
    assert values_equal("Active", "active") is True
    assert values_conflict("Active", "Churned") is True


# --------------------------------------------------------------------------- #
# annotation parentheticals (SP_026) — a paren group carrying a *letter*
# ("(per app)", "(against plan of 10)", "(BRL 22M)") is disambiguating prose, not
# part of the magnitude. It is dropped in the NUMERIC path only, so a value's
# primary number parses and two readings that AGREE on the number but differ only
# in their annotation stop being a false contradiction. Digit-only parens
# (accounting negatives like "(840.00)") are deliberately NOT stripped.
# --------------------------------------------------------------------------- #
def test_annotation_parenthetical_dropped_in_numeric_parse():
    assert normalize_value("9.4 (against plan of 10)")[1] == pytest.approx(9.4)
    assert normalize_value("SGD 4.8M (BRL 22M)")[1] == pytest.approx(4_800_000.0)
    assert normalize_value("R$ 192,660.00 (per app)")[1] == pytest.approx(192_660.0)


def test_annotation_kept_in_canonical_text():
    # The fix touches the numeric copy only — the canonical text still carries the
    # annotation so a genuinely text-only value is never mangled.
    text, num = normalize_value("9.4 (against plan of 10)")
    assert "against plan" in text
    assert num == pytest.approx(9.4)


def test_same_number_different_annotation_is_not_a_conflict():
    # gross_revenue agrees at 192,660 across two reporting channels — no value conflict.
    assert (
        values_conflict(
            "R$ 192,660.00 (per app)", "R$ 192,660.00 (per bank statement)"
        )
        is False
    )


def test_different_number_same_shape_still_conflicts():
    # net_revenue genuinely disagrees app-vs-bank → a real contradiction survives.
    assert (
        values_conflict(
            "R$ 191,390.00 (per app)", "R$ 189,250.00 (per bank statement)"
        )
        is True
    )
    # per-person commit counts differ → still a conflict after the annotation strip.
    assert values_conflict("38 (Yong Wei)", "18 (Camila Souza)") is True


def test_planted_revenue_conflict_survives_annotation_strip():
    # Different magnitudes must still conflict even when both carry a source annotation.
    assert values_conflict("SGD 14.2M (dashboard)", "SGD 13.9M (board deck)") is True


def test_accounting_negative_parens_not_treated_as_annotation():
    # A digit-only paren is an accounting negative, never an annotation — it must NOT be
    # stripped (which would silently parse a positive/None). It stays non-numeric here.
    assert normalize_value("(840.00)")[1] is None
    # Two different refund magnitudes still conflict (compared as text, parens intact).
    assert (
        values_conflict(
            "R$ (840.00) (HelixPay Core cards)", "R$ (310.00) (HelixPay Tap)"
        )
        is True
    )


# --------------------------------------------------------------------------- #
# SP_028a — sign/currency-position equivalence (the ebitda 16-row spurious class) #
# --------------------------------------------------------------------------- #
def test_sign_before_currency_equals_currency_before_sign():
    # "-SGD 2.1M" and "SGD -2.1M" are the SAME negative value — only the sign/currency
    # order differs. Today the former fails the numeric parse (currency strip leaves
    # "- 2.1m" with a space) and the two compare as unequal text → a spurious conflict.
    assert values_conflict("-SGD 2.1M", "SGD -2.1M") is False
    assert normalize_value("-SGD 2.1M")[1] == pytest.approx(-2_100_000.0)


def test_sign_flip_is_still_a_real_conflict():
    # A genuine sign flip must remain a conflict (regression anchor; passes pre-impl too).
    assert values_conflict("-SGD 2.1M", "SGD 2.1M") is True


def test_two_different_negatives_still_conflict():
    assert values_conflict("-SGD 2.1M", "-SGD 3.0M") is True


def test_sign_after_currency_unaffected_by_glue():
    # The already-working "SGD -2.1M" (sign adjacent to digits) must be unchanged.
    assert normalize_value("SGD -2.1M")[1] == pytest.approx(-2_100_000.0)
    assert values_conflict("SGD -2.1M", "SGD -2.1M") is False


def test_bare_minus_space_digit_parsed_as_number():
    # SP_028a step 6b glues the space in "- 5" even when no currency was stripped — correct:
    # "- 5" and "-5" are the same value, not conflicting text. (Documents the side effect.)
    assert normalize_value("- 5")[1] == pytest.approx(-5.0)
    assert values_conflict("- 5", "-5") is False
