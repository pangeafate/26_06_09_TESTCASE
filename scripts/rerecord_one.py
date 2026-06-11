"""Re-record a SINGLE document's extraction (paid, one doc) — SP_026 follow-up.

A full ``record data --force`` re-bills all 44 documents. After a *prompt* change that only
affects one document's shape (here: the sales-pipeline dashboard, which recorded empty —
``{"claims":[],"relations":[]}`` — under the pre-SP_026 prompt), this re-extracts just the
one target path with ``force=True``, reusing the real discover machinery so the
``source_uri`` (hence the cache key and the ``documents`` row) is byte-identical to the
original run. The other 43 documents are filtered out and never touched ($0).

The chunk text and content_hash are unchanged, so ``add_chunks`` is a no-op on the existing
chunk (its real Voyage embedding is retained); only the claims/relations are re-extracted.

Usage (inside the app container, host repo mounted at /src):
    HELIXPAY_PROMPTS_DIR=/src/prompts PYTHONPATH=/src \
    python /src/scripts/rerecord_one.py data/dashboards/sales-pipeline-2026-04-21.html
"""

from __future__ import annotations

import argparse
import sys

from helixpay.db.repository import PostgresRepository
from helixpay.ingest import pipeline
from helixpay.ingest.extract.extractor import ChunkExtractor
from helixpay.ingest.extract.llm import AnthropicClient
from helixpay.ingest.loaders import discover_all
from helixpay.ingest.replay import CachingExtractor


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Re-record one document (paid, single doc).")
    p.add_argument("target", help="exact source path, e.g. data/dashboards/foo.html")
    p.add_argument("--root", default="data")
    p.add_argument("--cache-dir", default=".replay-cache")
    args = p.parse_args(argv)

    all_docs = discover_all(args.root)
    selected = [(c, path) for (c, path) in all_docs if path == args.target]
    if not selected:
        sys.stderr.write(f"refuse: no document matches {args.target!r} under {args.root!r}\n")
        sys.stderr.write("available:\n" + "\n".join(f"  {path}" for _, path in all_docs) + "\n")
        return 2
    if len(selected) != 1:
        sys.stderr.write(f"refuse: {len(selected)} matches for {args.target!r} (expected 1)\n")
        return 2

    sys.stderr.write(f"re-recording (PAID, force): {args.target}\n")
    extractor = CachingExtractor(
        ChunkExtractor(AnthropicClient(), glean_passes=1), args.cache_dir, force=True
    )
    repo = PostgresRepository.from_url()
    report = pipeline.run(
        args.root,
        repo=repo,
        extractor=extractor,
        discover=lambda _root: selected,
        already_ingested=lambda _h: False,
    )
    sys.stderr.write(f"done: {report}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
