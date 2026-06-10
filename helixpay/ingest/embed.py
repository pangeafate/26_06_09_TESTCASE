"""Voyage embeddings — the embedding seam (CLAUDE.md §7: embeddings = voyage, 1024-dim).

The ingest pipeline computes embeddings here and passes them to
``Repository.add_chunks(chunks, embeddings)``; the lexical ``tsv`` is a DB-generated
column and is never produced in Python.

The low-level Voyage client is **injectable** so unit tests stub it — the real
``voyageai`` SDK is imported lazily inside :func:`_default_voyage_client`, so the suite
runs with neither the package installed nor ``VOYAGE_API_KEY`` set.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from helixpay.config import EMBEDDING_DIM, EMBEDDING_MODEL, load_config

log = logging.getLogger("helixpay.ingest.embed")

_DEFAULT_BATCH = 128


@runtime_checkable
class VoyageClient(Protocol):
    """The slice of the Voyage SDK we depend on (``voyageai.Client``)."""

    def embed(self, texts: list[str], *, model: str, input_type: str): ...


def _default_voyage_client() -> VoyageClient:
    """Build the real Voyage client. Imported lazily (via importlib, so the static type
    checker doesn't require the optional SDK) — the unit suite needs neither the
    ``voyageai`` package nor ``VOYAGE_API_KEY``."""
    import importlib  # noqa: PLC0415

    voyageai = importlib.import_module("voyageai")  # External-Tool-Isolation: lazy
    return voyageai.Client(api_key=load_config().voyage_api_key)


class VoyageEmbedder:
    """Batched, dimension-checked embeddings over an injectable client.

    ``input_type="document"`` is used at ingest (queries use ``"query"`` in the query
    layer). Every returned vector must be exactly ``EMBEDDING_DIM`` wide — the
    ``chunks.embedding`` column is ``VECTOR(1024)`` and a mismatch must fail loudly here,
    not as an opaque server-side error at ``add_chunks``.
    """

    def __init__(
        self,
        client: VoyageClient | None = None,
        *,
        model: str = EMBEDDING_MODEL,
        dim: int = EMBEDDING_DIM,
        batch_size: int = _DEFAULT_BATCH,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        self._client = client
        self.model = model
        self.dim = dim
        self.batch_size = batch_size

    @property
    def client(self) -> VoyageClient:
        if self._client is None:
            self._client = _default_voyage_client()
        return self._client

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        out: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            result = self.client.embed(batch, model=self.model, input_type="document")
            vectors = list(result.embeddings)
            if len(vectors) != len(batch):
                raise ValueError(
                    f"embedding count mismatch: asked for {len(batch)} vectors, got {len(vectors)}"
                )
            for vec in vectors:
                vec = [float(x) for x in vec]
                if len(vec) != self.dim:
                    raise ValueError(
                        f"embedding dimension mismatch: expected {self.dim}, got {len(vec)}"
                    )
                out.append(vec)
        log.info(
            "embedded chunks", extra={"count": len(out), "model": self.model, "operation": "embed"}
        )
        return out


__all__ = ["VoyageEmbedder", "VoyageClient"]
