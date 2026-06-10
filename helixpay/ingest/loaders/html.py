"""HtmlConnector — KPI / pipeline dashboards (``source_type="html"``).

Owns ``data/dashboards/*.html``. Each KPI card and each section/table becomes an
atomic ``Segment`` that carries the metric **value AND the dashboard's as-of date**
— that value+date pairing is exactly where the planted contradictions hide, so it
must never be separated. The as-of date is parsed from the ``.subtitle`` (an
``As of YYYY-MM-DD`` label or a bare ISO date) with the export ``.stamp`` and the
filename as fallbacks.
"""

from __future__ import annotations

import glob
import os

from bs4 import BeautifulSoup

from helixpay.contracts import Chunk, Document, SourceType

from .base import (
    LoaderError,
    Segment,
    chunk_segments,
    compute_content_hash,
    extract_iso_date,
    normalize_text,
    render_table,
    to_chunks,
)
from .markdown import read_text


def _text(node) -> str:
    return node.get_text(" ", strip=True) if node is not None else ""


class HtmlConnector:
    source_type = SourceType.html.value

    def discover(self, root: str) -> list[str]:
        return sorted(glob.glob(os.path.join(root, "dashboards", "*.html")))

    def load(self, path: str) -> tuple[Document, list[Chunk]]:
        raw = read_text(path)
        if not raw.strip():
            raise LoaderError(f"empty html file: {path}")
        soup = BeautifulSoup(raw, "html.parser")

        subtitle = _text(soup.select_one(".subtitle"))
        stamp = _text(soup.select_one(".stamp"))
        as_of = extract_iso_date(f"{subtitle}\n{stamp}", fallback_path=path)
        as_of_tag = f"(as of {as_of.isoformat()})" if as_of else "(as of unknown)"

        title = soup.title.string.strip() if soup.title and soup.title.string else None
        segments: list[Segment] = []

        for card in soup.select(".card"):
            parts = [
                _text(card.select_one(".label")),
                _text(card.select_one(".value")),
                _text(card.select_one(".delta")),
            ]
            line = " — ".join(p for p in parts if p)
            if line:
                segments.append(Segment(f"{line} {as_of_tag}", splittable=False))

        for section in soup.select(".section"):
            heading = _text(section.select_one("h2"))
            table = section.find("table")
            if table is not None:
                rows = [
                    [_text(cell) for cell in tr.find_all(["th", "td"])]
                    for tr in table.find_all("tr")
                ]
                body = render_table(rows)
            else:
                body = _text(section)
            block = f"{heading} {as_of_tag}\n{body}".strip()
            if block:
                segments.append(Segment(block, splittable=False))

        # Banners / notes that carry contextual numbers but live outside cards/sections.
        for extra in soup.select(".banner, .note"):
            note = _text(extra)
            if note:
                segments.append(Segment(f"{note} {as_of_tag}", splittable=False))

        if not segments:  # fall back to the whole-document text rather than emit nothing
            whole = _text(soup.body or soup)
            if not whole:
                raise LoaderError(f"no extractable content in html: {path}")
            segments.append(Segment(f"{whole} {as_of_tag}", splittable=True))

        chunks = to_chunks(chunk_segments(segments, source_uri=path))
        document = Document(
            source_uri=path,
            source_type=self.source_type,
            title=title,
            as_of=as_of,
            content_hash=compute_content_hash(raw),
            raw_text=normalize_text(soup.get_text("\n", strip=True)),
        )
        return document, chunks


__all__ = ["HtmlConnector"]
