"""Canonical value normalization (SP_009 — the shared substrate).

One pure, I/O-free home for value normalization so the three consumers that compare
asserted values never drift:

* contradiction detection (``contradict.values_conflict`` — SP_011),
* the eval matcher (predicted-vs-gold equivalence — SP_013),
* consensus rollup (grouping equal values — SP_013).

This sprint (SP_009) only *ships* the util + tests; the consumers are rewired to import
it in their own sprints, so today's ``contradict``/``grounding`` imports keep working.

Contract (pinned at the SP_009 pre-impl review):

``normalize_value(value) -> (canonical_text, numeric_or_None)``

* The **numeric (float)** path is gated to a *pure* number: a unit-bearing quantity
  such as ``"18 months"``, a label like ``"Q1 2026"``, or a version ``"v2.1"`` returns
  ``numeric is None`` and is compared as TEXT. This is deliberate — durations, quarters
  and versions are not magnitudes, and treating them as such would fabricate or mask
  the planted Q1 revenue/ARR contradiction.
* **Word-numbers** ("eighteen") expand in the *text* form, so ``"eighteen months"`` and
  ``"18 months"`` are text-equal while ``"18 days"`` is not. Only simple cardinals are
  expanded (ones 0-19, tens, and tens-ones compounds); "hundred"/"thousand" are NOT
  treated as cardinals, so ``"one hundred twenty"`` stays non-numeric (no false 120).
* **Currency** symbols/codes and **magnitude** suffixes/words (``K``/``M``/``B``/``bn``,
  ``thousand``/``million``/``billion``) fold into the numeric parse so ``"SGD 14.2M"``
  and ``"14.2 million"`` are numerically equal.
* **Approx** markers (``~``, ``≈``, ``approx``/``approximately``/``about``/``around``/
  ``circa``/``roughly``) strip to the literal value with NO tolerance widening — equality
  is still exact (``math.isclose`` at ``1e-9``), so ``"~18" == 18`` but ``"~18" != 17``.
* The **Unicode minus** ``−`` is folded to ASCII ``-`` so ``"−11%"`` and ``"-11%"`` match.
"""

from __future__ import annotations

import math
import re
from typing import Optional

# Magnitude scales for both attached suffixes ("14.2M") and words ("14.2 million").
# "hundred" is intentionally absent — it is not a cardinal we expand (see module docs).
_SCALE = {
    "k": 1_000.0,
    "m": 1_000_000.0,
    "b": 1_000_000_000.0,
    "bn": 1_000_000_000.0,
    "thousand": 1_000.0,
    "million": 1_000_000.0,
    "billion": 1_000_000_000.0,
}

# Currency: ISO codes as whole words, plus single symbols and the Brazilian "R$".
# A bare "r" is deliberately NOT stripped (it would mangle text values like "revenue").
_CURRENCY = re.compile(r"\br\$|\b(?:sgd|usd|brl|eur|myr|gbp|jpy)\b|[$€£¥₹]", re.IGNORECASE)

# Approx markers: the ~/≈ symbols and a small set of hedge words. Note: the bare
# abbreviation "est" is deliberately NOT here — it would strip the Latin "est." from a
# founding-year value ("est. 2015" → ". 2015"); "estimated" already covers the intent.
_APPROX = re.compile(
    r"~|≈|\b(?:approx(?:imately)?|about|around|circa|roughly|estimated)\b",
    re.IGNORECASE,
)

_UNICODE_MINUS = "−"

# A value is numeric ONLY when the entire cleaned string is a single number: optional
# sign, digits with optional decimal, optional magnitude suffix/word, optional percent.
# fullmatch (in _parse_number) enforces the whole-string discipline, so a stray digit
# inside a label ("Q1 2026", "v2.1", "18 months") never parses as a magnitude.
_PURE_NUM_RE = re.compile(
    r"(?P<mant>-?\d+(?:\.\d+)?)\s*(?P<suf>k|m|b|bn|thousand|million|billion)?\s*%?",
    re.IGNORECASE,
)

# Simple cardinals — ones 0-19 and the tens. Composed for "twenty one" → 21.
_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}


def _expand_cardinals(text: str) -> str:
    """Replace simple cardinal words with digits in-place (token-wise). Composes a
    trailing ones word onto a tens word ("twenty one" → "21"). Leaves every other token
    untouched, so units ("months") and labels ("q1") survive for the text comparison."""
    tokens = text.split()
    out: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in _TENS:
            val = _TENS[tok]
            nxt = tokens[i + 1] if i + 1 < len(tokens) else None
            if nxt in _ONES and 1 <= _ONES[nxt] <= 9:
                val += _ONES[nxt]
                i += 1
            out.append(str(val))
        elif tok in _ONES:
            out.append(str(_ONES[tok]))
        else:
            out.append(tok)
        i += 1
    return " ".join(out)


def _parse_number(cleaned: str) -> Optional[float]:
    """Return the float value iff ``cleaned`` is, in its entirety, a single number
    (optionally with a magnitude suffix/word and/or a trailing percent). Otherwise None."""
    m = _PURE_NUM_RE.fullmatch(cleaned)
    if not m:
        return None
    try:
        base = float(m.group("mant"))
    except ValueError:  # pragma: no cover - regex already constrains the shape
        return None
    suf = (m.group("suf") or "").lower()
    return base * _SCALE.get(suf, 1.0)


def normalize_value(value: Optional[str]) -> tuple[str, Optional[float]]:
    """Return ``(canonical_text, numeric_or_None)`` per the module contract."""
    if value is None:
        return "", None
    # 1. casefold + fold the Unicode minus so "−x" and "-x" agree.
    text = value.casefold().replace(_UNICODE_MINUS, "-")
    # 2. drop approx markers (no tolerance change — they only remove noise).
    text = _APPROX.sub(" ", text)
    # 3. split hyphenated number words ("twenty-one" → "twenty one"); a leading sign
    #    hyphen is preceded by no letter, so it is left intact.
    text = re.sub(r"(?<=[a-z])-(?=[a-z])", " ", text)
    # 4. remove digit-grouping commas only ("14,200,000" → "14200000"); other commas stay.
    text = re.sub(r"(?<=\d),(?=\d)", "", text)
    # 5. collapse whitespace, expand cardinals, collapse again.
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+", " ", _expand_cardinals(text)).strip()
    # 6. numeric parse on a currency-stripped copy (text itself keeps currency so a
    #    text-only value is never mangled).
    cleaned = re.sub(r"\s+", " ", _CURRENCY.sub(" ", text)).strip()
    return text, _parse_number(cleaned)


def values_equal(a: Optional[str], b: Optional[str]) -> bool:
    """True when two values are equivalent: numerically close when *both* are pure
    numbers, else canonical-text equal."""
    ta, na = normalize_value(a)
    tb, nb = normalize_value(b)
    if na is not None and nb is not None:
        return math.isclose(na, nb, rel_tol=1e-9, abs_tol=1e-9)
    return ta == tb


def values_conflict(a: Optional[str], b: Optional[str]) -> bool:
    """True when two present values disagree. A missing value (None) is not a competing
    fact, so it never conflicts."""
    if a is None or b is None:
        return False
    return not values_equal(a, b)


__all__ = ["normalize_value", "values_equal", "values_conflict"]
