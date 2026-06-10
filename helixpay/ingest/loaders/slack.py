"""SlackConnector — chat exports (``source_type="slack"``).

Owns ``data/chat/*.md``. Each message (``**<Day Mon DD HH:MM> — speaker**`` header
plus its body) becomes one atomic ``Segment`` so speaker and timestamp boundaries
are preserved and never split mid-turn. Body text (including non-English lines) is
passed through verbatim.
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
    to_chunks,
)
from .markdown import read_text

# A message header: a whole-line bold "<timestamp with HH:MM> — <speaker>" (em-dash
# or hyphen). Requiring a clock time avoids false-matching an inline bold phrase that
# merely happens to contain a dash (e.g. "**Revenue — confirmed**").
_MSG_HEADER_RE = re.compile(
    r"^\*\*(?P<meta>[^*\n]*\d{1,2}:\d{2}[^*\n]*?)\s+[—-]\s+(?P<who>[^*\n]+?)\*\*$"
)
# Cheap O(1) pre-check before the regex: a real header is a short, fully bold-
# delimited line. This short-circuits a hostile unclosed "**...long..." line that
# would otherwise drive quadratic backtracking on the regex above (ReDoS guard).
_MAX_HEADER_LEN = 200


def _is_msg_header(line: str) -> bool:
    return (
        len(line) <= _MAX_HEADER_LEN
        and line.startswith("**")
        and line.endswith("**")
        and _MSG_HEADER_RE.match(line) is not None
    )
_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


def _segment_messages(text: str) -> list[Segment]:
    """Split a chat export into one atomic Segment per message; any preamble
    (channel header / export note) before the first message is its own segment."""
    lines = text.split("\n")
    segments: list[Segment] = []
    preamble: list[str] = []
    current: list[str] | None = None

    def flush(buf: list[str], *, splittable: bool) -> None:
        body = "\n".join(buf).strip("\n")
        if body.strip():
            segments.append(Segment(body, splittable=splittable))

    for line in lines:
        if _is_msg_header(line.strip()):
            if current is not None:
                flush(current, splittable=False)
            elif preamble:
                flush(preamble, splittable=True)
                preamble = []
            current = [line]
        elif current is not None:
            current.append(line)
        else:
            preamble.append(line)
    if current is not None:
        flush(current, splittable=False)
    elif preamble:
        flush(preamble, splittable=True)
    return segments


class SlackConnector:
    source_type = SourceType.slack.value

    def discover(self, root: str) -> list[str]:
        return sorted(glob.glob(os.path.join(root, "chat", "*.md")))

    def load(self, path: str) -> tuple[Document, list[Chunk]]:
        raw = read_text(path)
        if not raw.strip():
            raise LoaderError(f"empty chat export: {path}")
        norm = normalize_text(raw)
        segments = _segment_messages(norm)
        chunks = to_chunks(chunk_segments(segments, source_uri=path))
        title_match = _H1_RE.search(norm)
        document = Document(
            source_uri=path,
            source_type=self.source_type,
            title=title_match.group(1).strip() if title_match else None,
            as_of=extract_iso_date(norm, fallback_path=path),
            content_hash=compute_content_hash(raw),
            raw_text=norm,
        )
        return document, chunks


__all__ = ["SlackConnector"]
