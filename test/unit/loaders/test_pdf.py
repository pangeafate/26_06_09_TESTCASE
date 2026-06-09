"""PdfConnector — the table-rendering seam is pure and unit-tested here; the
real PDF parse is exercised by the smoke suite (no real PDF needed at unit level).
"""

from __future__ import annotations

from helixpay.ingest.loaders.pdf import render_page


def test_render_page_emits_prose_and_table_figures():
    text = "Q1 2026 Results\nRevenue came in under plan."
    tables = [[["Metric", "Q1 2026", "Q1 Plan"], ["Revenue", "14.2", "16.0"]]]
    out = render_page(text, tables)
    assert "Revenue came in under plan." in out
    # the table figures survive into the rendered text as a pipe table
    assert "Revenue" in out and "14.2" in out and "16.0" in out and "|" in out


def test_render_page_handles_no_tables():
    out = render_page("just prose", [])
    assert out.strip() == "just prose"


def test_render_page_handles_empty_text():
    out = render_page("", [[["a", "b"], ["1", "2"]]])
    assert "a" in out and "1" in out
