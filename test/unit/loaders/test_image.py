"""ImageConnector — the vision call is injectable so unit tests stub it (no
network, no secret). content_hash is over the image BYTES (a non-deterministic
caption must not break idempotent re-ingest).
"""

from __future__ import annotations

import hashlib
import importlib
from datetime import date
from pathlib import Path

from helixpay.contracts import SourceType
from helixpay.ingest.loaders.image import ImageConnector

DATA = Path(__file__).resolve().parents[2].parent / "data"


def test_image_uses_injected_caption_no_network(tmp_path):
    img = tmp_path / "revenue-trend-q1-2026.jpeg"
    img.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg-bytes")
    captured: dict = {}

    def stub(data: bytes, media_type: str) -> str:
        captured["media_type"] = media_type
        captured["nbytes"] = len(data)
        return "Revenue trend chart. Q1 2026 revenue SGD 14.2M as of 2026-03-31."

    doc, chunks = ImageConnector(caption_fn=stub).load(str(img))
    assert doc.source_type == SourceType.image.value
    assert captured["media_type"] == "image/jpeg"
    assert len(chunks) == 1
    assert "14.2M" in chunks[0].text
    assert doc.as_of == date(2026, 3, 31)  # date lifted from the caption text


def test_image_content_hash_is_over_bytes_not_caption(tmp_path):
    img = tmp_path / "x.jpeg"
    payload = b"\xff\xd8\xff\xe0stable-bytes"
    img.write_bytes(payload)
    # two different (non-deterministic) captions must still yield the same hash
    doc1, _ = ImageConnector(caption_fn=lambda d, m: "caption A").load(str(img))
    doc2, _ = ImageConnector(caption_fn=lambda d, m: "totally different caption B").load(str(img))
    assert doc1.content_hash == doc2.content_hash == hashlib.sha256(payload).hexdigest()


def test_image_module_imports_without_anthropic_or_key():
    # importing the package / module must not import anthropic or touch the network
    mod = importlib.import_module("helixpay.ingest.loaders.image")
    assert hasattr(mod, "ImageConnector")
    # constructing the default connector performs no API call (lazy import inside load)
    conn = mod.ImageConnector()
    assert conn.source_type == SourceType.image.value


def test_image_discovers_real_jpegs():
    found = ImageConnector().discover(str(DATA))
    assert len(found) == 4
    assert all(p.endswith(".jpeg") for p in found)
