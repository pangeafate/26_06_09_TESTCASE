"""PdfConnector — PDF decks/reports (``source_type="pdf"``).

Owns ``data/*.pdf``. Extracts page text **and** tables (the tables carry the
financial figures) via pdfplumber. Page prose is a splittable ``Segment``; each
extracted table is rendered as a pipe table and kept atomic. ``render_page`` is a
pure seam (text + rendered tables → string) unit-tested without a real PDF; the
real parse is exercised by the smoke suite.
"""

from __future__ import annotations

import glob
import os
from collections.abc import Sequence

import pdfplumber

from helixpay.contracts import Chunk, Document, SourceType

from .base import (
    LoaderError,
    Segment,
    chunk_segments,
    compute_content_hash,
    extract_iso_date,
    logger,
    normalize_text,
    render_table,
    to_chunks,
)

_PREPARED_RE = ("Prepared by:", "Author:")


def render_page(text: str, tables: Sequence[Sequence[Sequence[str | None]]]) -> str:
    """Render one page's prose followed by its tables as markdown pipe tables."""
    parts: list[str] = []
    if text.strip():
        parts.append(text.strip())
    for table in tables:
        rendered = render_table(table)
        if rendered.strip():
            parts.append(rendered)
    return "\n\n".join(parts)


def _page_segments(text: str, tables: Sequence[Sequence[Sequence[str | None]]]) -> list[Segment]:
    segments: list[Segment] = []
    if text.strip():
        segments.append(Segment(text.strip(), splittable=True))
    for table in tables:
        rendered = render_table(table)
        if rendered.strip():
            segments.append(Segment(rendered, splittable=False))
    return segments


def _title(text: str) -> str | None:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return None


def _author(text: str) -> str | None:
    for line in text.splitlines():
        for marker in _PREPARED_RE:
            if marker in line:
                return line.split(marker, 1)[1].split(".")[0].strip() or None
    return None


class PdfConnector:
    source_type = SourceType.pdf.value

    def discover(self, root: str) -> list[str]:
        return sorted(glob.glob(os.path.join(root, "*.pdf")))

    def load(self, path: str) -> tuple[Document, list[Chunk]]:
        segments: list[Segment] = []
        page_texts: list[str] = []
        try:
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text() or ""
                    tables = page.extract_tables() or []
                    segments.extend(_page_segments(text, tables))
                    page_texts.append(render_page(text, tables))
        except LoaderError:
            raise
        except Exception as exc:  # pdfminer/pdfplumber raise a variety of types
            logger.error("failed to parse PDF", extra={"path": path, "error": str(exc)})
            raise LoaderError(f"cannot parse PDF {path}: {exc}") from exc

        if not segments:
            raise LoaderError(f"no extractable text in PDF: {path}")

        raw_text = normalize_text("\n\n".join(page_texts))
        chunks = to_chunks(chunk_segments(segments, source_uri=path))
        first_page = page_texts[0] if page_texts else ""
        document = Document(
            source_uri=path,
            source_type=self.source_type,
            title=_title(first_page),
            author=_author(raw_text),
            as_of=extract_iso_date(raw_text, fallback_path=path),
            content_hash=compute_content_hash(raw_text),
            raw_text=raw_text,
        )
        return document, chunks


__all__ = ["PdfConnector", "render_page"]
