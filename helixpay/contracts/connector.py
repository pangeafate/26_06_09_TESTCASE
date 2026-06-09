"""SourceConnector contract (spec §4).

Agent 1 (loaders) implements one ``SourceConnector`` per format (md, pdf, html,
image, slack, email, code). Each normalizes one file into a ``Document`` plus its
``Chunk`` list. Adding *live* ingestion later is a new connector, not a rewrite —
that is the "moving target" seam.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import Chunk, Document


@runtime_checkable
class SourceConnector(Protocol):
    source_type: str

    def discover(self, root: str) -> list[str]:
        """Return the paths under ``root`` that this connector owns."""
        ...

    def load(self, path: str) -> tuple[Document, list[Chunk]]:
        """Normalize one file into a Document and its ordered Chunks."""
        ...


__all__ = ["SourceConnector"]
