"""Source connectors + registry (SP_002, Agent 1).

One ``SourceConnector`` implementation per ``source_type`` (md, pdf, html, image,
slack, email, code). Each normalizes one file into a frozen ``Document`` + ordered
``Chunk``s. Discovery is **disjoint by directory** (no file is claimed by two
connectors), so the same `.md` extension can back several logical types without
collision.

The pipeline (Agent 2) discovers connectors through this registry:

    from helixpay.ingest.loaders import all_connectors, discover_all

``discover_all(root)`` returns ``(connector, path)`` pairs and raises
``LoaderError`` if any path is claimed by more than one connector.
"""

from __future__ import annotations

from helixpay.contracts import SourceConnector

from .base import LoaderError
from .code import CodeConnector
from .email import EmailConnector
from .html import HtmlConnector
from .image import ImageConnector
from .markdown import MarkdownConnector
from .pdf import PdfConnector
from .slack import SlackConnector


def all_connectors() -> list[SourceConnector]:
    """Every connector implementation, one per ``source_type`` (disjoint discovery)."""
    return [
        MarkdownConnector(),
        PdfConnector(),
        HtmlConnector(),
        SlackConnector(),
        EmailConnector(),
        CodeConnector(),
        ImageConnector(),
    ]


def discover_all(root: str) -> list[tuple[SourceConnector, str]]:
    """Discover every owned file under ``root`` across all connectors.

    Raises ``LoaderError`` on the first path claimed by two connectors, so a future
    data-layout drift fails loudly instead of double-ingesting.
    """
    pairs: list[tuple[SourceConnector, str]] = []
    claimed: dict[str, str] = {}
    for connector in all_connectors():
        for path in connector.discover(root):
            if path in claimed:
                raise LoaderError(
                    f"path {path!r} claimed by both {claimed[path]!r} and "
                    f"{connector.source_type!r} connectors"
                )
            claimed[path] = connector.source_type
            pairs.append((connector, path))
    return pairs


__all__ = [
    "LoaderError",
    "all_connectors",
    "discover_all",
    "MarkdownConnector",
    "PdfConnector",
    "HtmlConnector",
    "SlackConnector",
    "EmailConnector",
    "CodeConnector",
    "ImageConnector",
]
