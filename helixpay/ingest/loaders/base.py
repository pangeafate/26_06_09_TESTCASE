"""Shared substrate for the source connectors (SP_002).

Pure, dependency-light helpers used by every connector:

- ``normalize_text`` / ``compute_content_hash`` — content-addressed idempotency.
  The normalized text is what is hashed *and* stored as ``Document.raw_text`` so a
  re-hash of ``raw_text`` reproduces ``content_hash`` (re-ingest is a no-op).
- ``estimate_tokens`` — a tokenizer-free chars/4 heuristic.
- ``Segment`` + ``chunk_segments`` — boundary-aware chunking. A ``Segment`` carries
  a ``splittable`` flag; tables and individual chat/email messages are
  ``splittable=False`` and are **never** divided. Prose segments larger than the
  budget are soft-split on paragraph then sentence boundaries. An atomic segment
  larger than ``max_tokens`` is emitted whole (atomicity is hard; the budget is
  best-effort) and logged at WARNING.
- ``segment_markdown`` — shared markdown → ``Segment`` list (headings and
  whole-line bold speaker labels attach to the following block; pipe tables are
  kept atomic).
- ``extract_iso_date`` — the document's own date, by precedence: labelled stamp
  (Issued/As-of/Completed/…) > ``Date:`` header > plain ISO/month-name in body >
  a ``YYYY-MM-DD`` in the filename.
- ``render_table`` — renders extracted rows as a markdown pipe table.

No DB access, no network, no contract redefinition (types come from
``helixpay.contracts``). Parse failures are logged with file/format context and
re-raised as ``LoaderError`` — never swallowed; secrets are never logged.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from helixpay.contracts import Chunk

logger = logging.getLogger("helixpay.ingest.loaders")


class LoaderError(RuntimeError):
    """A source file could not be parsed/normalized into the Chunk contract."""


# --------------------------------------------------------------------------- #
# Normalization + content hashing                                             #
# --------------------------------------------------------------------------- #
def normalize_text(text: str) -> str:
    """Normalize line endings to ``\\n`` and strip trailing whitespace per line.

    The output is the canonical content used for both hashing and ``raw_text``.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    # strip() removes both leading and trailing blank lines so two documents that
    # differ only in surrounding blank lines hash identically (idempotent re-ingest)
    return "\n".join(lines).strip("\n")


def compute_content_hash(text: str) -> str:
    """Stable sha256 of normalized text → idempotent re-ingest."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def compute_bytes_hash(data: bytes) -> str:
    """Stable sha256 of raw bytes (used for binary sources like images, whose
    caption text is non-deterministic and must not drive the idempotency key)."""
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------- #
# Token estimate                                                              #
# --------------------------------------------------------------------------- #
def estimate_tokens(text: str) -> int:
    """Rough token count via a chars/4 heuristic (no tokenizer dependency)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


# --------------------------------------------------------------------------- #
# Segments + boundary-aware chunker                                           #
# --------------------------------------------------------------------------- #
@dataclass
class Segment:
    """A unit of source content. ``splittable=False`` segments (tables, single
    chat/email messages) are atomic and are never divided by the chunker."""

    text: str
    splittable: bool = True


_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_PARA_RE = re.compile(r"\n\s*\n")


def _split_prose(text: str, max_tokens: int) -> list[str]:
    """Split an oversize *splittable* segment on paragraph then sentence
    boundaries. A residual piece still over budget is emitted as-is."""
    pieces: list[str] = []
    for para in _PARA_RE.split(text):
        para = para.strip()
        if not para:
            continue
        if estimate_tokens(para) <= max_tokens:
            pieces.append(para)
            continue
        buf = ""
        for sentence in _SENTENCE_RE.split(para):
            candidate = f"{buf} {sentence}".strip() if buf else sentence
            if buf and estimate_tokens(candidate) > max_tokens:
                pieces.append(buf)
                buf = sentence
            else:
                buf = candidate
        if buf:
            pieces.append(buf)
    return pieces or [text]


def chunk_segments(
    segments: list[Segment],
    *,
    max_tokens: int = 800,
    target_tokens: int = 650,
    source_uri: str | None = None,
) -> list[str]:
    """Greedily pack atomic units into ~``target_tokens`` chunks (hard cap
    ``max_tokens``). Splittable prose over budget is soft-split; atomic segments
    are never split (an oversize one becomes its own chunk and is logged)."""
    units: list[str] = []
    for seg in segments:
        text = seg.text.strip("\n")
        if not text.strip():
            continue
        if seg.splittable and estimate_tokens(text) > max_tokens:
            units.extend(_split_prose(text, max_tokens))
        else:
            if estimate_tokens(text) > max_tokens:
                logger.warning(
                    "oversize atomic segment emitted whole",
                    extra={
                        "source_uri": source_uri,
                        "tokens": estimate_tokens(text),
                        "max_tokens": max_tokens,
                    },
                )
            units.append(text)

    chunks: list[str] = []
    buf: list[str] = []
    buf_tokens = 0
    for unit in units:
        unit_tokens = estimate_tokens(unit)
        if buf and buf_tokens + unit_tokens > max_tokens:
            chunks.append("\n\n".join(buf))
            buf, buf_tokens = [], 0
        buf.append(unit)
        buf_tokens += unit_tokens
        if buf_tokens >= target_tokens:
            chunks.append("\n\n".join(buf))
            buf, buf_tokens = [], 0
    if buf:
        chunks.append("\n\n".join(buf))
    return chunks


def to_chunks(texts: list[str]) -> list[Chunk]:
    """Wrap chunk strings in ``Chunk``s with sequential ``ordinal``s.

    ``document_id`` stays ``None`` — it is assigned at persist time by the pipeline.
    """
    return [Chunk(ordinal=i, text=text) for i, text in enumerate(texts)]


# --------------------------------------------------------------------------- #
# Markdown segmenter (shared by the md + code connectors)                     #
# --------------------------------------------------------------------------- #
_HEADING_RE = re.compile(r"^#{1,6}\s")
_BOLD_LINE_RE = re.compile(r"^\*\*.+\*\*$")


def _is_table_line(line: str) -> bool:
    return line.strip().startswith("|")


def segment_markdown(text: str) -> list[Segment]:
    """Split markdown into ``Segment``s on blank-line blocks. A heading line or a
    whole-line bold speaker label attaches to the following block; a run of pipe
    table lines is one atomic (``splittable=False``) segment."""
    lines = text.split("\n")
    segments: list[Segment] = []
    buf: list[str] = []
    pending_label: str | None = None

    def flush_buf() -> None:
        nonlocal buf, pending_label
        body = "\n".join(buf).strip("\n")
        buf = []
        if not body.strip():
            return
        if pending_label:
            body = f"{pending_label}\n{body}"
            pending_label = None
        segments.append(Segment(body, splittable=True))

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if _is_table_line(line):
            flush_buf()
            table: list[str] = []
            while i < n and _is_table_line(lines[i]):
                table.append(lines[i])
                i += 1
            table_text = "\n".join(table)
            if pending_label:
                table_text = f"{pending_label}\n{table_text}"
                pending_label = None
            segments.append(Segment(table_text, splittable=False))
            continue
        stripped = line.strip()
        if not stripped:
            flush_buf()
            i += 1
            continue
        if _HEADING_RE.match(line) or _BOLD_LINE_RE.match(stripped):
            flush_buf()
            # Accumulate consecutive heading / bold-label lines (no body between)
            # so e.g. "# Interview: X" + "## Meta" both survive and attach to the
            # following block — a lone label is never silently overwritten/dropped.
            pending_label = stripped if pending_label is None else f"{pending_label}\n{stripped}"
            i += 1
            continue
        buf.append(line)
        i += 1
    flush_buf()
    if pending_label:  # a dangling label with no following body
        segments.append(Segment(pending_label, splittable=True))
    return segments


# --------------------------------------------------------------------------- #
# Date extraction                                                             #
# --------------------------------------------------------------------------- #
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_MONTH_DAY_YEAR_RE = re.compile(r"\b([A-Za-z]{3,9})\s+(\d{1,2}),\s*(\d{4})\b")  # April 15, 2026
_DAY_MONTH_YEAR_RE = re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})\b")  # 15 April 2026 / 22 Apr 2026
# Labelled stamps, in priority order: an authoritative single-event stamp first
# (so a labelled "Generated/Issued/As of" date wins over an unlabelled reporting-
# period *start* date), then a Date: header.
_LABEL_GROUPS = [
    re.compile(
        r"(?:issued|as[\s-]?of|effective|dated|completed|generated|exported|published)"
        r"\b[\s:*\-—]*",
        re.IGNORECASE,
    ),
    re.compile(r"\bdate\b[\s:*\-—]*", re.IGNORECASE),
]


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _month_num(token: str) -> int | None:
    return _MONTHS.get(token.lower()[:3])


def _find_date_token(text: str) -> date | None:
    m = _ISO_RE.search(text)
    if m:
        d = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            return d
    m = _MONTH_DAY_YEAR_RE.search(text)
    if m:
        month = _month_num(m.group(1))
        if month:
            d = _safe_date(int(m.group(3)), month, int(m.group(2)))
            if d:
                return d
    m = _DAY_MONTH_YEAR_RE.search(text)
    if m:
        month = _month_num(m.group(2))
        if month:
            d = _safe_date(int(m.group(3)), month, int(m.group(1)))
            if d:
                return d
    return None


def extract_iso_date(text: str, *, fallback_path: str | None = None) -> date | None:
    """Best-effort document date. Precedence: labelled stamp > Date: header >
    first plain date in the body > a ``YYYY-MM-DD`` embedded in the filename."""
    for group in _LABEL_GROUPS:
        for match in group.finditer(text):
            window = text[match.end(): match.end() + 60]
            found = _find_date_token(window)
            if found:
                return found
    found = _find_date_token(text)
    if found:
        return found
    if fallback_path:
        return _find_date_token(os.path.basename(fallback_path))
    return None


# --------------------------------------------------------------------------- #
# Table rendering                                                             #
# --------------------------------------------------------------------------- #
def render_table(rows: Sequence[Sequence[str | None]]) -> str:
    """Render extracted rows (e.g. from pdfplumber / a parsed HTML table) as a
    markdown pipe table. ``None`` cells become empty strings."""
    rendered: list[str] = []
    for row in rows:
        cells = [(cell or "").strip().replace("\n", " ") for cell in row]
        rendered.append("| " + " | ".join(cells) + " |")
    return "\n".join(rendered)


__all__ = [
    "LoaderError",
    "Segment",
    "logger",
    "normalize_text",
    "compute_content_hash",
    "compute_bytes_hash",
    "estimate_tokens",
    "chunk_segments",
    "to_chunks",
    "segment_markdown",
    "extract_iso_date",
    "render_table",
]
