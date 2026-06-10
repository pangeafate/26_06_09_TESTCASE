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
