"""Shared `as_of` parsing for the REST + MCP adapters — `_dates.parse_as_of` (pure)."""

from __future__ import annotations

from datetime import date

import pytest

from helixpay.api._dates import parse_as_of


@pytest.mark.parametrize("value, expected", [
    ("2026-03-31", date(2026, 3, 31)),
    ("2025-12-31", date(2025, 12, 31)),
    ("2026-01-01", date(2026, 1, 1)),
])
def test_valid_iso_date_parses(value, expected):
    assert parse_as_of(value) == expected


def test_none_returns_none():
    assert parse_as_of(None) is None


def test_empty_string_returns_none():
    assert parse_as_of("") is None


@pytest.mark.parametrize("value", [
    "not-a-date",
    "Q1 2026",
    "2026/03/31",
    "31-03-2026",
    "2026-13-01",   # month out of range
    "2026-02-30",   # day out of range
])
def test_malformed_value_raises_valueerror(value):
    with pytest.raises(ValueError):
        parse_as_of(value)


def test_valueerror_message_names_as_of_and_echoes_value():
    with pytest.raises(ValueError) as exc:
        parse_as_of("nope")
    msg = str(exc.value)
    assert "as_of" in msg
    assert "nope" in msg
