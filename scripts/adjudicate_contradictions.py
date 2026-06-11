"""Paid LLM contradiction-adjudication sweep (SP_028b) — the gated, operator-invoked CLI.

Wraps ``helixpay.ingest.adjudicate.adjudicate_store`` with the live ``PostgresRepository`` and the
Opus (temperature 0) client. This is the ONLY paid step; everything in the unit/integration suite
runs $0 with a stub. Run AFTER ingest + the SP_028a recompute sweep, before snapshot + deploy.

  # see the plan before spending a cent — prints cluster count + estimated LLM calls, writes nothing
  python -m scripts.adjudicate_contradictions --dry-run

  # the paid run — Opus per surviving cluster; verdicts cached on content hash → re-runs are $0
  python -m scripts.adjudicate_contradictions

Caching: ``--cache-dir`` (default ``.adjudication-cache``) holds one JSON verdict per cluster keyed
on a CONTENT hash, so a second run on an unchanged store issues zero LLM calls. Never logs the
connection string or API key.
"""

from __future__ import annotations

import argparse
import sys

from helixpay.db.repository import PostgresRepository
from helixpay.ingest.adjudicate import (
    ADJUDICATE_MODEL,
    JsonFileCache,
    adjudicate_store,
    build_adjudicator_client,
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="LLM contradiction adjudication sweep (SP_028b).")
    ap.add_argument(
        "--dry-run", action="store_true",
        help="print cluster count + estimated LLM calls; write nothing, spend nothing",
    )
    ap.add_argument("--cache-dir", default=".adjudication-cache", help="content-keyed verdict cache")
    ap.add_argument(
        "--model", default=ADJUDICATE_MODEL,
        help=f"adjudication model (default {ADJUDICATE_MODEL}; the model rides in the cache key, "
        "so a cheaper model uses a separate verdict namespace)",
    )
    args = ap.parse_args(argv)

    repo = PostgresRepository.from_url()
    cache = JsonFileCache(args.cache_dir)

    if args.dry_run:
        stats = adjudicate_store(repo, _NoClient(), cache, dry_run=True, model=args.model)
        print(f"DRY RUN ({args.model}) — nothing written, nothing spent", file=sys.stderr)
    else:
        client = build_adjudicator_client(model=args.model)
        stats = adjudicate_store(repo, client, cache, model=args.model)

    for k, v in stats.items():
        print(f"{k:24} {v}", file=sys.stderr)
    return 0


class _NoClient:
    """A guard client for --dry-run: a dry run must never call the model, so this raises if it
    is ever reached (it should not be — dry_run short-circuits before any generate)."""

    def generate(self, *, system: str, user: str, max_tokens: int) -> str:  # pragma: no cover
        raise RuntimeError("--dry-run must not call the LLM")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
