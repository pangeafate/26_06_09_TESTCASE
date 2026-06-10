"""EmailConnector — email threads (``source_type="email"``).

Owns ``data/email/*.md``. Parses the leading ``From/To/Cc/Date/Subject`` header
block (kept atomic so thread/subject/participants survive together), then chunks
the body. ``as_of`` is the **first** ``Date:`` header — the outermost / most-recent
message of a forwarded thread.
"""

from __future__ import annotations

import glob
import os
import re

from helixpay.contracts import Chunk, Document, SourceType

from .base import (
    LoaderError,
    Segment,
    chunk_segments,
    compute_content_hash,
    extract_iso_date,
    normalize_text,
    segment_markdown,
    to_chunks,
)
from .markdown import read_text

_HEADER_RE = re.compile(r"^([A-Za-z-]+):\s*(.*)$")


def _parse_headers(norm: str) -> tuple[dict[str, str], str, str]:
    """Return (headers, header_block_text, body_text). First value wins per key."""
    lines = norm.split("\n")
    headers: dict[str, str] = {}
    i = 0
    while i < len(lines) and lines[i].strip():
        match = _HEADER_RE.match(lines[i])
        if match:
            headers.setdefault(match.group(1).lower(), match.group(2).strip())
        i += 1
    header_block = "\n".join(lines[:i]).strip("\n")
    body = "\n".join(lines[i:]).strip("\n")
    return headers, header_block, body


class EmailConnector:
    source_type = SourceType.email.value

    def discover(self, root: str) -> list[str]:
        return sorted(glob.glob(os.path.join(root, "email", "*.md")))

    def load(self, path: str) -> tuple[Document, list[Chunk]]:
        raw = read_text(path)
        if not raw.strip():
            raise LoaderError(f"empty email file: {path}")
        norm = normalize_text(raw)
        headers, header_block, body = _parse_headers(norm)

        segments: list[Segment] = []
        if header_block:
            segments.append(Segment(header_block, splittable=False))
        segments.extend(segment_markdown(body))
        chunks = to_chunks(chunk_segments(segments, source_uri=path))

        as_of = extract_iso_date(headers["date"]) if "date" in headers else None
        if as_of is None:
            as_of = extract_iso_date(norm, fallback_path=path)
        document = Document(
            source_uri=path,
            source_type=self.source_type,
            title=headers.get("subject"),
            author=headers.get("from"),
            as_of=as_of,
            content_hash=compute_content_hash(raw),
            raw_text=norm,
        )
        return document, chunks


__all__ = ["EmailConnector"]
