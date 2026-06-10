"""Smoke tests over the real data/ dump (excluded from the fast unit suite via the
`smoke` mark). These guard the actual 44-file partition and prove every connector
parses its real files into contract-valid Document + Chunks.

The image connector's smoke test self-skips without ANTHROPIC_API_KEY (a real
vision call needs network + secret) — same spirit as the `db`-gated tests.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from helixpay.contracts import Document, SourceType
from helixpay.ingest.loaders import all_connectors, discover_all
from helixpay.ingest.loaders.html import HtmlConnector
from helixpay.ingest.loaders.image import ImageConnector

DATA = Path(__file__).resolve().parents[2].parent / "data"

EXPECTED_COUNTS = {
    "md": 29,
    "pdf": 2,
    "html": 3,
    "slack": 3,
    "email": 2,
    "code": 1,
    "image": 4,
}
ISO_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


@pytest.mark.smoke
def test_discover_all_claims_every_file_exactly_once():
    pairs = discover_all(str(DATA))
    paths = [p for _, p in pairs]
    on_disk = {str(p) for p in DATA.rglob("*") if p.is_file()}
    assert len(paths) == len(set(paths)) == 44, "every file claimed exactly once"
    assert set(paths) == on_disk, "discovery covers exactly the files on disk"


@pytest.mark.smoke
def test_per_connector_counts_match():
    by_type: dict[str, int] = {}
    for conn, path in discover_all(str(DATA)):
        by_type[conn.source_type] = by_type.get(conn.source_type, 0) + 1
    assert by_type == EXPECTED_COUNTS


@pytest.mark.smoke
def test_every_non_image_file_parses_to_valid_document_and_chunks():
    for conn, path in discover_all(str(DATA)):
        if conn.source_type == SourceType.image.value:
            continue  # needs a vision call — covered separately/gated
        doc, chunks = conn.load(path)
        assert isinstance(doc, Document)
        assert doc.source_uri == path
        assert doc.source_type in {e.value for e in SourceType}
        assert doc.content_hash, f"no content_hash for {path}"
        assert chunks, f"no chunks produced for {path}"
        assert all(c.text.strip() for c in chunks), f"empty chunk in {path}"
        assert [c.ordinal for c in chunks] == list(range(len(chunks)))


@pytest.mark.smoke
def test_ingestion_is_idempotent_on_content_hash():
    # re-loading the same file yields the same content_hash (idempotent re-ingest)
    conn = next(c for c in all_connectors() if c.source_type == "md")
    path = str(DATA / "overview.md")
    h1 = conn.load(path)[0].content_hash
    h2 = conn.load(path)[0].content_hash
    assert h1 == h2


@pytest.mark.smoke
def test_real_dashboard_chunks_carry_value_and_as_of():
    path = str(DATA / "dashboards" / "april-2026-kpi-dashboard.html")
    doc, chunks = HtmlConnector().load(path)
    assert doc.as_of is not None
    # at least one chunk pairs a numeric metric value with an ISO as-of date
    assert any(ISO_RE.search(c.text) and re.search(r"\d", c.text) for c in chunks)
    # the planted Q1 revenue figure is present with its date
    assert any("14.2" in c.text and "2026-04-21" in c.text for c in chunks)


@pytest.mark.smoke
def test_real_images_caption_via_vision():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set — skipping live vision caption smoke test")
    for path in ImageConnector().discover(str(DATA)):
        doc, chunks = ImageConnector().load(path)
        assert doc.source_type == SourceType.image.value
        assert chunks and chunks[0].text.strip()
