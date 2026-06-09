"""CodeConnector — code/repository analysis docs (``source_type="code"``).

Owns ``data/code/*.md`` (the contributor-and-repository analysis). Uses the shared
markdown segmenter so the repo/owner/contributor tables stay atomic and the
file/author references are not split apart.
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
    normalize_text,
    segment_markdown,
    to_chunks,
)
from .markdown import read_text

_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_AUTHOR_RE = re.compile(r"Author:\s*([^.\n]+)")


class CodeConnector:
    source_type = SourceType.code.value

    def discover(self, root: str) -> list[str]:
        return sorted(glob.glob(os.path.join(root, "code", "*.md")))

    def load(self, path: str) -> tuple[Document, list[Chunk]]:
        raw = read_text(path)
        if not raw.strip():
            raise LoaderError(f"empty code-analysis file: {path}")
        norm = normalize_text(raw)
        segments = segment_markdown(norm)
        chunks = to_chunks(chunk_segments(segments, source_uri=path))
        title_match = _H1_RE.search(norm)
        author_match = _AUTHOR_RE.search(norm)
        document = Document(
            source_uri=path,
            source_type=self.source_type,
            title=title_match.group(1).strip() if title_match else None,
            author=author_match.group(1).strip() if author_match else None,
            as_of=extract_iso_date(norm, fallback_path=path),
            content_hash=compute_content_hash(raw),
            raw_text=norm,
        )
        return document, chunks


__all__ = ["CodeConnector"]
