"""Replay tier (SP_010): record one real extraction, then re-run the whole post-LLM
pipeline (resolve → canonicalize → persist → supersede → contradict) from cache at
**zero API cost**.

The expensive part of ingestion is the LLM extraction. Everything downstream of it is
deterministic and cheap, so we wrap the injectable ``extractor=`` seam on
``pipeline.run``:

* ``CachingExtractor`` calls the real extractor once and writes each per-chunk
  ``ExtractionOut`` to ``<cache_dir>/<slug(source_uri)>.<digest>.<ordinal>.json`` (the
  slug is human-readable; the ``source_uri`` digest is the collision-free key).
* ``ReplayExtractor`` reconstructs that ``ExtractionOut`` from disk and raises
  ``ReplayCacheMiss`` on a miss — so a replay can never silently fall back to a paid call.

The cache key is ``(source_uri, ordinal)``: ``source_uri`` is unique per document and
``ordinal`` is unique within it, so the key is collision-free across the corpus (hashing
the chunk *text* would collide on boilerplate shared between documents). A change to the
prompt, the chunking, or a document's content is a re-record (Tier 1), not a replay.

CLI: ``python -m helixpay.ingest.replay {record|replay} [root] [--cache-dir DIR]``.
Replay also swaps in a placeholder embedder (``_ConstantEmbedder``) — the chunks already
carry their real embeddings from the record run and ``add_chunks`` is
``ON CONFLICT DO NOTHING``, so replay re-runs with no Voyage call either.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import re
import sys
from pathlib import Path
from typing import Optional, Protocol, Union

from helixpay.config import EMBEDDING_DIM
from helixpay.contracts import Chunk
from helixpay.ingest.extract.extractor import ChunkContext
from helixpay.ingest.extract.schemas import ExtractionOut

log = logging.getLogger("helixpay.ingest.replay")

_DEFAULT_CACHE_DIR = Path(".replay-cache")
_PathLike = Union[str, Path]


class _Extractor(Protocol):
    def extract(self, chunk: Chunk, ctx: ChunkContext) -> ExtractionOut: ...


class ReplayCacheMiss(RuntimeError):
    """No cached extraction exists for a ``(source_uri, ordinal)`` — record before replay."""


def _slug(source_uri: str) -> str:
    """A human-readable, filesystem-safe stem for a ``source_uri`` (for debuggability)."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", source_uri).strip("_") or "doc"


def _cache_path(cache_dir: _PathLike, source_uri: str, ordinal: int) -> Path:
    """Cache file for one chunk. A short ``source_uri`` digest guarantees uniqueness even
    when two distinct paths slugify to the same readable stem (the slug is for humans; the
    digest is the actual key)."""
    digest = hashlib.sha256(source_uri.encode("utf-8")).hexdigest()[:8]
    return Path(cache_dir) / f"{_slug(source_uri)}.{digest}.{ordinal}.json"


class CachingExtractor:
    """Wrap an inner extractor; persist each ``ExtractionOut`` keyed on
    ``(source_uri, ordinal)`` and return the live result unchanged. A pre-existing cache
    file is a hit (the inner — paid — extractor is NOT called) so a re-run never
    re-bills already-recorded chunks; pass ``force=True`` to re-extract and overwrite."""

    def __init__(
        self, inner: _Extractor, cache_dir: _PathLike, *, force: bool = False
    ) -> None:
        self._inner = inner
        self._cache_dir = Path(cache_dir)
        self._force = force

    def extract(self, chunk: Chunk, ctx: ChunkContext) -> ExtractionOut:
        path = _cache_path(self._cache_dir, ctx.source_uri, chunk.ordinal)
        if not self._force and path.exists():
            log.info(
                "record cache hit — skipping paid extraction",
                extra={"source_uri": ctx.source_uri, "ordinal": chunk.ordinal},
            )
            return ExtractionOut.model_validate_json(path.read_text(encoding="utf-8"))
        result = self._inner.extract(chunk, ctx)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(result.model_dump_json(), encoding="utf-8")
        log.info(
            "recorded extraction",
            extra={"source_uri": ctx.source_uri, "ordinal": chunk.ordinal},
        )
        return result


class ReplayExtractor:
    """Reconstruct a cached ``ExtractionOut`` from disk. Makes **zero** API calls; raises
    ``ReplayCacheMiss`` when the chunk was never recorded."""

    def __init__(self, cache_dir: _PathLike) -> None:
        self._cache_dir = Path(cache_dir)

    def extract(self, chunk: Chunk, ctx: ChunkContext) -> ExtractionOut:
        path = _cache_path(self._cache_dir, ctx.source_uri, chunk.ordinal)
        if not path.exists():
            raise ReplayCacheMiss(
                f"no cached extraction at {path} — run `make ingest-record` first"
            )
        return ExtractionOut.model_validate_json(path.read_text(encoding="utf-8"))


class _ConstantEmbedder:
    """A $0 embedder for the replay path. Chunks already carry their real embeddings from
    the record run, and ``add_chunks`` is ``ON CONFLICT DO NOTHING``, so these
    fixed-dimension placeholders are never persisted — they exist only to satisfy the
    pipeline's embed step without a Voyage call."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * EMBEDDING_DIM for _ in texts]


def _build_extractor(
    mode: str, cache_dir: _PathLike, *, force: bool = False
) -> _Extractor:
    if mode == "replay":
        return ReplayExtractor(cache_dir)
    # record: the one paid run. Lazy imports keep the replay path free of the API client.
    from helixpay.ingest.extract.extractor import ChunkExtractor  # noqa: PLC0415
    from helixpay.ingest.extract.llm import AnthropicClient  # noqa: PLC0415

    return CachingExtractor(
        ChunkExtractor(AnthropicClient(), glean_passes=1), cache_dir, force=force
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m helixpay.ingest.replay",
        description="Record one real extraction, or replay the post-LLM pipeline from cache ($0).",
    )
    parser.add_argument(
        "mode",
        choices=["record", "replay"],
        help="record a paid run, or replay from cache",
    )
    parser.add_argument(
        "root", nargs="?", default="data", help="corpus root (default: data)"
    )
    parser.add_argument(
        "--cache-dir", default=str(_DEFAULT_CACHE_DIR), help="replay cache directory"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="record mode: re-extract and overwrite cached chunks (a prompt/chunking change)",
    )
    args = parser.parse_args(argv)

    from helixpay.ingest import pipeline  # noqa: PLC0415 — lazy (no DB/API at import)

    extractor = _build_extractor(args.mode, args.cache_dir, force=args.force)
    # Re-process every document (the record run already persisted them); replay also
    # swaps in the $0 embedder so no Voyage call is made.
    kwargs: dict = {"already_ingested": lambda _h: False}

    try:
        repo = None
        if args.mode == "replay":
            from helixpay.db.repository import PostgresRepository  # noqa: PLC0415

            repo = PostgresRepository.from_url()
            # Replay re-uses the chunk embeddings the record run persisted; if those rows
            # are absent (fresh/empty DB), the $0 embedder would write zero vectors and
            # silently break retrieval — so refuse rather than corrupt the index.
            if not repo.known_content_hashes():
                sys.stderr.write(
                    "replay needs a prior `make ingest-record` on this DB "
                    "(no ingested documents found)\n"
                )
                return 2
            kwargs["embedder"] = _ConstantEmbedder()
        report = pipeline.run(args.root, repo=repo, extractor=extractor, **kwargs)
    except ReplayCacheMiss as exc:
        sys.stderr.write(f"replay cache miss: {exc}\n")
        return 2
    except Exception as exc:  # noqa: BLE001 — surface a clean nonzero exit for the make target
        sys.stderr.write(
            f"{args.mode} failed for {args.root!r}: {type(exc).__name__}: {exc}\n"
        )
        return 1
    sys.stdout.write(f"{args.mode} complete: {report}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
