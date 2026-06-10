"""SP_015 operator smoke harness — record the one-per-type corpus doc-by-doc into the
isolated proving DB, then run the $0 per-doc proving bar (golden + ledger + embedding).

Designed to run **from CWD ``eval/smoke``** (so the loader globs ``data/<subpath>`` and the
emitted ``source_uri`` matches the golden oracle + the manifest verbatim) with
``PYTHONPATH`` pointing at the repo root. ``DATABASE_URL`` selects the isolated DB
(``helixpay_smoke``) and the API keys come from the environment (never logged).

Two phases, decoupled so a doc-by-doc record can be inspected/aborted without re-paying:

  * ``--record`` (PAID, default): extract + Voyage-embed + persist each requested doc. The
    replay cache is empty for these ``data/`` keys, so each doc is one real extraction of the
    CURRENT code; its loss-ledger entry is appended to ``ledger.json`` so the final check can
    read it even across separate invocations (the in-process ledger would otherwise be lost).
  * ``--check`` ($0): load the persisted per-doc ledger + a DB embedding audit + the Level-1
    golden grader, combine via ``eval.smoke.check_smoke``, and write the machine result the
    ``scripts/full_run.py`` gate re-derives from.

USAGE (inside the app container, CWD /work/eval/smoke, PYTHONPATH=/work):
  python /work/scripts/run_smoke.py --record --only data/overview.md
  python /work/scripts/run_smoke.py --record                 # all 9
  python /work/scripts/run_smoke.py --check
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from eval.run import load_golden
from eval.smoke import check_smoke
from eval.smoke.manifest import SOURCE_URIS
from helixpay.db.repository import PostgresRepository
from helixpay.ingest import pipeline
from helixpay.ingest.embed import VoyageEmbedder
from helixpay.ingest.extract.extractor import ChunkExtractor
from helixpay.ingest.extract.llm import AnthropicClient
from helixpay.ingest.loaders import discover_all
from helixpay.ingest.replay import CachingExtractor

LEDGER_FILE = Path("ledger.json")  # eval/smoke/ledger.json — accumulates per-doc ledger entries


def _load_table() -> dict:
    return json.loads(LEDGER_FILE.read_text()) if LEDGER_FILE.exists() else {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="run_smoke")
    ap.add_argument("--record", action="store_true", help="PAID: record the requested docs")
    ap.add_argument("--check", action="store_true", help="$0: run the proving bar + write result")
    ap.add_argument("--only", action="append", default=None,
                    help="source_uri to record (repeatable); default = all 9")
    ap.add_argument("--cache-dir", default="/work/.replay-cache")
    ap.add_argument("--result", default="SP015_smoke_result.json")
    ap.add_argument("--force", action="store_true",
                    help="re-extract even on a cache hit (a prompt/chunking change)")
    args = ap.parse_args(argv)

    if not (args.record or args.check):
        ap.error("nothing to do: pass --record and/or --check")

    repo = PostgresRepository.from_url()  # DATABASE_URL -> helixpay_smoke
    pairs = {path: (conn, path) for conn, path in discover_all("data")}
    missing = [u for u in SOURCE_URIS if u not in pairs]
    if missing:
        sys.stderr.write(f"discover missed manifest docs: {missing}\n")
        return 2

    if args.record:
        # Resilient Anthropic client: the default SDK retry budget (2) was exhausted by a
        # transient "server disconnected" mid-batch. Bump retries + timeout so a network blip
        # is absorbed *inside* a single extract call — keeping the per-doc loss ledger whole
        # (a cross-run retry would leave already-cached chunks uncounted). Harness-only; no
        # production-code change. Falls back to the default client if injection is unavailable.
        import anthropic  # noqa: PLC0415

        from helixpay.config import load_config  # noqa: PLC0415

        resilient = anthropic.Anthropic(
            api_key=load_config().anthropic_api_key, max_retries=8, timeout=120.0
        )
        ext = ChunkExtractor(AnthropicClient(client=resilient), glean_passes=1)
        caching = CachingExtractor(ext, args.cache_dir, force=args.force)
        emb = VoyageEmbedder()
        targets = args.only or SOURCE_URIS
        table = _load_table()
        for uri in targets:
            if uri not in pairs:
                sys.stderr.write(f"unknown --only uri (not in manifest discovery): {uri}\n")
                return 2
            rep = pipeline.run(
                "data",
                repo=repo,
                discover=lambda _root, p=[pairs[uri]]: p,
                extractor=caching,
                embedder=emb,
                already_ingested=lambda _h: False,
            )
            entry = ext.ledger.probe().get(uri, {})
            table[uri] = entry
            LEDGER_FILE.write_text(json.dumps(table, indent=2, sort_keys=True))
            print(
                f"[REC] {uri}  docs={rep.documents} chunks={rep.chunks} "
                f"claims={rep.claims} links={rep.links} "
                f"dropped_mentions={rep.dropped_mentions} contradictions={rep.contradictions} "
                f"ledger={entry}",
                flush=True,
            )

    if args.check:
        golden = load_golden(Path("facts.yaml"))
        emb_map = repo.audit_chunk_embeddings(SOURCE_URIS)
        table = _load_table()
        result = check_smoke.check(
            repo,
            golden,
            source_root=Path("."),
            ledger_probe=check_smoke.ledger_probe_from(table),
            embedding_probe=check_smoke.embedding_probe_from(emb_map),
        )
        check_smoke.write_result(result, Path(args.result))
        for uri, d in result["docs"].items():
            print(f"  {d['verdict']:11s} {uri}  {('; '.join(d['reasons'])) or 'clean'}")
        print(f"\nPASSED {result['passed']}/{result['total']}  all_green={result['all_green']}")
        print(f"result -> {args.result}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
