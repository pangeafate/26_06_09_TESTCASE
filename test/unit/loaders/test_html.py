"""HtmlConnector — dashboard chunks must carry the metric value AND its as-of date
(that pairing is where the planted contradictions hide). Inline fixture covers both
an `As of`-labelled subtitle and a bare-ISO subtitle (the sales-pipeline shape).
"""

from __future__ import annotations

from datetime import date

from helixpay.contracts import SourceType
from helixpay.ingest.loaders.html import HtmlConnector

_DASH = """<!DOCTYPE html><html><head><title>KPI Dashboard</title></head><body>
<div class="subtitle">Internal · As of 2026-04-21 · Owner: FP&amp;A</div>
<div class="grid">
  <div class="card"><div class="label">Q1 2026 Revenue (SGD)</div><div class="value">14.2M</div><div class="delta down">-11% vs plan</div></div>
</div>
<div class="section"><h2>Revenue by region — Q1 2026</h2>
  <table><tr><th>Region</th><th>Q1 Actual</th></tr><tr><td>SEA (SGD)</td><td>9.4M</td></tr></table>
</div>
<div class="stamp">exported 2026-04-21 09:14 SGT</div>
</body></html>"""

_BARE = """<html><head><title>Sales Pipeline</title></head><body>
<div class="subtitle">Hybrid view (HubSpot SEA + Pipedrive BR) · 2026-04-21 09:00 SGT</div>
<div class="card"><div class="label">Total open pipeline</div><div class="value">SGD 4.2M</div></div>
</body></html>"""


def _write(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return str(p)


def test_html_chunk_carries_value_and_as_of(tmp_path):
    path = _write(tmp_path, "april-2026-kpi-dashboard.html", _DASH)
    doc, chunks = HtmlConnector().load(path)
    assert doc.source_type == SourceType.html.value
    assert doc.as_of == date(2026, 4, 21)
    # at least one chunk pairs the metric value with the as-of date
    assert any("14.2M" in c.text and "2026-04-21" in c.text for c in chunks)
    # the region table figure is present too
    assert any("9.4M" in c.text for c in chunks)


def test_html_bare_iso_subtitle_still_dates(tmp_path):
    path = _write(tmp_path, "sales-pipeline-2026-04-21.html", _BARE)
    doc, chunks = HtmlConnector().load(path)
    assert doc.as_of == date(2026, 4, 21)  # parsed despite no "As of" label
    assert any("SGD 4.2M" in c.text and "2026-04-21" in c.text for c in chunks)
