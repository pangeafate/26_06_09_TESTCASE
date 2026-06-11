"""ImageConnector — the vision call is injectable so unit tests stub it (no
network, no secret). content_hash is over the image BYTES (a non-deterministic
caption must not break idempotent re-ingest).
"""

from __future__ import annotations

import hashlib
import importlib
import re
from datetime import date
from pathlib import Path

from helixpay.contracts import SourceType
from helixpay.ingest.loaders.image import _CAPTION_PROMPT, ImageConnector

_ROOT = Path(__file__).resolve().parents[2].parent
DATA = _ROOT / "data"
_EXTRACT_PROMPT = _ROOT / "prompts" / "extract_claims.md"

# A representative STRUCTURED caption (what the sharpened vision pass should emit) — used to
# prove the loader passes per-series, number-bearing lines through to the chunk verbatim. The
# numbers here are fixture data, NOT baked into any prompt.
_STRUCTURED_CAPTION = (
    "HelixPay — Revenue by region (SGD millions). Source: FP&A · Q1 2026 close "
    "(period end 2026-03-31).\n"
    "Series (solid = actual, dashed = plan/target):\n"
    "- SEA actual: Q1 2025 9.0; Q2 2025 9.6; Q3 2025 10.0; Q4 2025 10.1; Q1 2026 9.4\n"
    "- Brasil actual (SGD eq): Q1 2025 4.5; Q2 2025 4.7; Q3 2025 4.9; Q4 2025 5.3; Q1 2026 4.8\n"
    "- SEA plan (dashed, target): Q1 2026 10.0\n"
    "- Brasil plan (dashed, target): Q1 2026 6.0\n"
)


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


# --- SP_021: structured chart extraction -------------------------------------------------


def test_image_passes_structured_caption_through(tmp_path):
    # the loader must carry the full per-series transcription (every number-bearing line)
    # into the chunk so the downstream extractor can emit a claim per datapoint.
    img = tmp_path / "revenue-trend-q1-2026.jpeg"
    img.write_bytes(b"\xff\xd8\xff\xe0fake")
    doc, chunks = ImageConnector(caption_fn=lambda d, m: _STRUCTURED_CAPTION).load(str(img))
    text = chunks[0].text
    for needle in ("SEA actual", "Brasil actual", "9.4", "4.8", "5.3", "plan", "actual"):
        assert needle in text, f"structured caption lost {needle!r}"


def test_image_as_of_from_q1_close_line(tmp_path):
    # "Q1 2026 close" in the caption resolves the document as_of to the quarter end.
    img = tmp_path / "revenue-trend-q1-2026.jpeg"
    img.write_bytes(b"\xff\xd8\xff\xe0fake")
    doc, _ = ImageConnector(caption_fn=lambda d, m: _STRUCTURED_CAPTION).load(str(img))
    assert doc.as_of == date(2026, 3, 31)


def test_caption_prompt_requests_structured_per_series_actual_vs_plan():
    # the vision pass must ask for a structured per-series transcription and explicitly
    # distinguish actual vs plan/target by line style — guard against reverting to a prose
    # caption (Stage-5 M2: assert the solid/dashed marker logic, not just the words).
    p = _CAPTION_PROMPT.lower()
    assert "series" in p, "caption prompt must ask for per-series transcription"
    assert "plan" in p or "target" in p, "caption prompt must distinguish actual vs plan/target"
    assert "solid" in p and "dashed" in p, "caption prompt must key actual/plan to line style"


def test_image_as_of_prefers_reporting_close_not_earliest_series_date(tmp_path):
    # Stage-5 M1 regression: extract_iso_date is "first ISO wins". The header carries the
    # reporting close (latest quarter); series lines must NOT carry earlier ISO dates that would
    # be picked up as the document as_of. The prompt now confines ISO dates to the header line.
    img = tmp_path / "revenue-trend-q1-2026.jpeg"
    img.write_bytes(b"\xff\xd8\xff\xe0fake")
    caption = (
        "HelixPay — Revenue by region (SGD M). Source: FP&A · Q1 2026 close (2026-03-31).\n"
        "- SEA actual: Q1 25 9.0; Q1 26 9.4\n"  # bare period labels, no ISO dates here
    )
    doc, _ = ImageConnector(caption_fn=lambda d, m: caption).load(str(img))
    assert doc.as_of == date(2026, 3, 31)


def test_extract_prompt_has_charts_section_without_baked_numbers():
    # the extractor must have generic chart guidance; and that section must contain NO numeric
    # values (extract_claims.md already bakes 14.2M/4.8M elsewhere — do not compound it).
    text = _EXTRACT_PROMPT.read_text(encoding="utf-8")
    marker = "## Charts"
    assert marker in text, "extract_claims.md missing a '## Charts' guidance section"
    section = text[text.index(marker):]
    nxt = section.find("\n## ", 1)
    section = section[:nxt] if nxt != -1 else section
    leaked = re.findall(r"\b\d+\.?\d*\s*[MmKkBb]\b", section)
    assert not leaked, f"Charts section leaks corpus-shaped numbers: {leaked}"
