"""MarkdownConnector — general markdown (``source_type="md"``).

Owns the top-level ``data/*.md`` docs (overview, org-chart, all-hands,
board-update, weekly-review) **and** ``data/interviews/**/*.md``. Discovery is
directory-scoped (non-recursive top level + recursive interviews) so the `.md`
files under ``chat/``, ``email/`` and ``code/`` are left to their own connectors.
Section/speaker/table boundaries are preserved by ``segment_markdown``.
"""

from __future__ import annotations

import glob
import os
import re

from helixpay.contracts import Chunk, Document, SourceType

from .base import (
    LoaderError,
    chunk_segments,
    compute_content_hash,
    extract_iso_date,
    logger,
    normalize_text,
    segment_markdown,
    to_chunks,
)

_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_NAME_RE = re.compile(r"^\s*[-*]?\s*\*\*(?:Name|Author)\:?\*\*\s*(.+?)\s*$", re.MULTILINE)
_LANG_RE = re.compile(r"\*\*Language\:?\*\*\s*([A-Za-z-]+)")


def read_text(path: str) -> str:
    """Read a UTF-8 text file, raising LoaderError (never swallowing) on failure."""
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError as exc:
        logger.error("failed to read source file", extra={"path": path, "error": str(exc)})
        raise LoaderError(f"cannot read {path}: {exc}") from exc


def _title(text: str) -> str | None:
    match = _H1_RE.search(text)
    return match.group(1).strip() if match else None


def _author(text: str) -> str | None:
    match = _NAME_RE.search(text)
    return match.group(1).strip() if match else None


def _lang(text: str) -> str | None:
    match = _LANG_RE.search(text)
    return match.group(1).strip() if match else None


class MarkdownConnector:
    source_type = SourceType.md.value

    def discover(self, root: str) -> list[str]:
        top = glob.glob(os.path.join(root, "*.md"))  # non-recursive: top-level only
        interviews = glob.glob(os.path.join(root, "interviews", "**", "*.md"), recursive=True)
        return sorted(set(top) | set(interviews))

    def load(self, path: str) -> tuple[Document, list[Chunk]]:
        raw = read_text(path)
        if not raw.strip():
            raise LoaderError(f"empty markdown file: {path}")
        norm = normalize_text(raw)
        segments = segment_markdown(norm)
        chunks = to_chunks(chunk_segments(segments, source_uri=path))
        document = Document(
            source_uri=path,
            source_type=self.source_type,
            title=_title(norm),
            author=_author(norm),
            lang=_lang(norm),
            as_of=extract_iso_date(norm, fallback_path=path),
            content_hash=compute_content_hash(raw),
            raw_text=norm,
        )
        return document, chunks


__all__ = ["MarkdownConnector", "read_text"]
