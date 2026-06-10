"""ImageConnector — chart/screenshot JPEGs (``source_type="image"``).

Owns ``data/images/*.jpeg``. Runs a **caption-level** vision pass (deep figure OCR
is an explicit scope cut — degrade to a caption). The vision call is an injectable
``caption_fn`` so unit tests stub it: no network, no secret in the unit suite. The
default implementation lazily builds an Anthropic client (``config.EXTRACTION_MODEL``)
— ``anthropic`` is imported inside the function so importing this module needs
neither the SDK nor ``ANTHROPIC_API_KEY``.

``content_hash`` is computed over the image **bytes**, not the caption: a vision
caption is non-deterministic and must not break idempotent re-ingest.
"""

from __future__ import annotations

import glob
import os
from pathlib import Path
from typing import Callable

from helixpay.contracts import Chunk, Document, SourceType

from .base import (
    LoaderError,
    compute_bytes_hash,
    extract_iso_date,
    logger,
    normalize_text,
    to_chunks,
)

# (image_bytes, media_type) -> caption text
CaptionFn = Callable[[bytes, str], str]

_MEDIA_TYPES = {".jpeg": "image/jpeg", ".jpg": "image/jpeg", ".png": "image/png"}

_CAPTION_PROMPT = (
    "This is an internal HelixPay chart, dashboard screenshot, or org-chart image. "
    "Caption it factually: describe what it shows and transcribe every visible number, "
    "label, axis, legend, and date exactly as shown. Note any as-of/reporting date. "
    "Be concise; do not speculate beyond what is visible."
)


def _default_caption_fn(image_bytes: bytes, media_type: str) -> str:
    """Real Anthropic vision caption. Imports the SDK lazily so the module (and the
    unit suite) load without ``anthropic`` installed or a key present."""
    import base64
    from typing import Any, cast

    import anthropic  # lazy: not needed unless a real caption is requested

    from helixpay.config import EXTRACTION_MODEL

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the env
    content: Any = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.standard_b64encode(image_bytes).decode("ascii"),
            },
        },
        {"type": "text", "text": _CAPTION_PROMPT},
    ]
    message = client.messages.create(
        model=EXTRACTION_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": content}],
    )
    return "".join(
        cast("str", getattr(block, "text", ""))
        for block in message.content
        if getattr(block, "type", None) == "text"
    ).strip()


class ImageConnector:
    source_type = SourceType.image.value

    def __init__(self, caption_fn: CaptionFn | None = None) -> None:
        self._caption_fn: CaptionFn = caption_fn or _default_caption_fn

    def discover(self, root: str) -> list[str]:
        found: list[str] = []
        for ext in _MEDIA_TYPES:  # .jpeg / .jpg / .png — keep in sync with media types
            found.extend(glob.glob(os.path.join(root, "images", f"*{ext}")))
        return sorted(set(found))

    def load(self, path: str) -> tuple[Document, list[Chunk]]:
        try:
            data = Path(path).read_bytes()
        except OSError as exc:
            logger.error("failed to read image", extra={"path": path, "error": str(exc)})
            raise LoaderError(f"cannot read image {path}: {exc}") from exc

        media_type = _MEDIA_TYPES.get(Path(path).suffix.lower(), "image/jpeg")
        try:
            caption = self._caption_fn(data, media_type)
        except Exception as exc:  # surface vision failures, never swallow
            logger.error("image caption failed", extra={"path": path, "error": str(exc)})
            raise LoaderError(f"vision caption failed for {path}: {exc}") from exc

        caption = (caption or "").strip()
        text = normalize_text(caption) if caption else f"[image: {Path(path).stem}]"
        document = Document(
            source_uri=path,
            source_type=self.source_type,
            title=Path(path).stem,
            as_of=extract_iso_date(caption, fallback_path=path),
            content_hash=compute_bytes_hash(data),  # stable on bytes, not the caption
            raw_text=text,
        )
        return document, to_chunks([text])


__all__ = ["ImageConnector", "CaptionFn"]
