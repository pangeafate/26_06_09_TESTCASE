#!/usr/bin/env python3
"""Retrieval-recall@k diagnostic — is the golden chunk reachable by retrieval?

This is a **read-only development-tooling probe** (CLAUDE.md §15), not part of the
graded eval path. It answers one question the end-to-end eval can't isolate: for
each golden bar-fact, does the chunk that *carries that fact's source* appear in the
top-k of retrieval? If recall@k is ~100%, the recall gap is **resolution-bound, not
retrieval-bound** (SOLUTION.md:226) and embedding/reranker work would polish the
wrong stage. If it's not, you've found the first genuinely retrieval-bound miss.

It reuses the real query stack — ``hybrid_search`` (RRF over pgvector + FTS), the
live Voyage query embedder, and the eval golden set — against an **already-embedded**
store (point ``DATABASE_URL`` at ``helixpay_full``; the replay cache uses constant
vectors and is useless here). Cost: one Voyage *query* embedding per fact (cents),
no Anthropic calls.

Modeling choice (read the number with this in mind): the golden facts are
``(subject, predicate, value, source_uri)`` with no natural-language query attached,
so we synthesize the query from **subject + predicate** (for links: from + link_type
+ to) and deliberately **exclude the value** — putting the answer in the query would
inflate recall. A "hit@k" = some top-k chunk's ``source_uri`` matches the fact's via
the same ``_uri_matches`` the grader uses. Facts whose source document isn't present
in the store are reported separately (``source-absent``) so a missing doc never
masquerades as a retrieval miss.

Usage::

    DATABASE_URL=postgres://… VOYAGE_API_KEY=… \
        uv run python -m scripts.retrieval_recall_probe
    uv run python -m scripts.retrieval_recall_probe --k 1,3,5,8,10,20 --json out.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from eval.models import GoldenFact  # noqa: E402
from eval.run import _uri_matches, load_golden  # noqa: E402 — reuse grader's URI match
from helixpay.query.clients import VoyageEmbedder  # noqa: E402
from helixpay.query.retrieval import hybrid_search, reciprocal_rank_fusion  # noqa: E402

DEFAULT_KS = (1, 3, 5, 8, 10, 20)


def _query_for(fact: GoldenFact) -> str:
    """Synthesize a value-free query from a golden fact (the 'question', not the answer)."""
    if fact.kind.value == "link":
        link_type = fact.link_type or fact.predicate
        frm = fact.from_ or fact.subject
        to = fact.to or fact.value
        return f"{frm} {link_type} {to}".strip()
    return f"{fact.subject} {fact.predicate}".strip()


def _source_uris_for_chunks(repo, chunk_ids: list[int]) -> list[str]:
    """source_uri per chunk id, IN THE GIVEN RANK ORDER. ``get_chunk_sources`` re-sorts
    its result by chunk_id, so we must re-key by chunk_id and re-emit in input order —
    recall@k slices the first k and is meaningless if the rank order is lost."""
    if not chunk_ids:
        return []
    by_id = {cit.chunk_id: cit.source_uri for cit in repo.get_chunk_sources(chunk_ids)}
    return [by_id[cid] for cid in chunk_ids if by_id.get(cid)]


def _hit_at_ks(ranked_uris: list[str], target: str, ks: tuple[int, ...]) -> dict[int, bool]:
    return {k: any(_uri_matches(target, u) for u in ranked_uris[:k]) for k in ks}


def probe(repo, embedder, ks: tuple[int, ...]) -> dict:
    golden = load_golden()
    facts = golden.bar_facts
    max_k = max(ks)

    # Partition out facts whose source document isn't in this store — a missing doc
    # is NOT a retrieval miss, and counting it as one would slander the embedder.
    # NB: stored source_uris carry a leading "./" (e.g. ./data/overview.md) while the
    # golden URIs don't, so presence must use the SAME basename/substring match the
    # retrieval side uses (_uri_matches) — exact-key audit silently mis-flags every
    # fact as absent. One small read of the stored URIs (diagnostic script).
    with repo.conn.cursor() as cur:
        cur.execute("SELECT DISTINCT source_uri FROM documents WHERE source_uri IS NOT NULL")
        stored_uris = [r["source_uri"] for r in cur.fetchall()]

    def _src_present(uri: str) -> bool:
        return any(_uri_matches(uri, s) for s in stored_uris)

    rows = []
    for fact in facts:
        if not _src_present(fact.source_uri):
            rows.append({"id": fact.id, "status": "source-absent", "source_uri": fact.source_uri})
            continue
        query = _query_for(fact)
        qvec = embedder.embed_query(query)
        sem = [c for c, _ in repo.search_semantic(qvec, max_k)]
        lex = [c for c, _ in repo.search_lexical(query, max_k)]
        hyb = [c for c, _ in reciprocal_rank_fusion([sem, lex])][:max_k]

        sem_uris = _source_uris_for_chunks(repo, [c.id for c in sem if c.id is not None])
        lex_uris = _source_uris_for_chunks(repo, [c.id for c in lex if c.id is not None])
        hyb_uris = _source_uris_for_chunks(repo, [c.id for c in hyb if c.id is not None])

        rows.append(
            {
                "id": fact.id,
                "status": "scored",
                "query": query,
                "source_uri": fact.source_uri,
                "hybrid": _hit_at_ks(hyb_uris, fact.source_uri, ks),
                "semantic": _hit_at_ks(sem_uris, fact.source_uri, ks),
                "lexical": _hit_at_ks(lex_uris, fact.source_uri, ks),
            }
        )

    scored = [r for r in rows if r["status"] == "scored"]
    absent = [r for r in rows if r["status"] == "source-absent"]

    def _recall(signal: str, k: int) -> float:
        if not scored:
            return 0.0
        return sum(1 for r in scored if r[signal][k]) / len(scored)

    summary = {
        sig: {k: round(_recall(sig, k), 3) for k in ks} for sig in ("hybrid", "semantic", "lexical")
    }
    # retrieval-bound misses: not found by hybrid even at the largest k.
    misses = [r["id"] for r in scored if not r["hybrid"][max_k]]
    return {
        "ks": list(ks),
        "n_bar_facts": len(facts),
        "n_scored": len(scored),
        "n_source_absent": len(absent),
        "source_absent_ids": [r["id"] for r in absent],
        "recall": summary,
        "retrieval_bound_misses": misses,
        "rows": rows,
    }


def _print_report(result: dict) -> None:
    ks = result["ks"]
    print("\nRetrieval-recall@k probe (read-only diagnostic — not the graded eval)\n")
    print(
        f"  bar facts: {result['n_bar_facts']}   scored: {result['n_scored']}   "
        f"source-absent: {result['n_source_absent']}"
    )
    if result["source_absent_ids"]:
        print(f"  source-absent (doc not in store, excluded): {', '.join(result['source_absent_ids'])}")
    header = "  signal    " + "".join(f"{('@' + str(k)):>8}" for k in ks)
    print("\n" + header)
    print("  " + "-" * (len(header) - 2))
    for sig in ("hybrid", "semantic", "lexical"):
        cells = "".join(f"{result['recall'][sig][k]:>8.0%}" for k in ks)
        print(f"  {sig:<10}{cells}")
    misses = result["retrieval_bound_misses"]
    print("")
    if misses:
        print(f"  retrieval-bound misses (not in hybrid top-{max(ks)}): {', '.join(misses)}")
        print("  → these are the ONLY facts a reranker / better embedding could rescue.")
    else:
        print(f"  retrieval-bound misses: NONE — every scored fact's source is in hybrid top-{max(ks)}.")
        print("  → the recall gap is resolution-bound, not retrieval-bound (SOLUTION.md:226).")
    print("")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Retrieval-recall@k diagnostic (read-only).")
    ap.add_argument("--k", default=",".join(str(k) for k in DEFAULT_KS), help="comma-separated k values")
    ap.add_argument("--json", type=Path, default=None, help="also write the full result JSON here")
    args = ap.parse_args(argv)

    ks = tuple(sorted({int(x) for x in args.k.split(",") if x.strip()}))
    if not ks:
        ap.error("--k must list at least one positive integer")

    from helixpay.db.repository import PostgresRepository  # lazy: needs DATABASE_URL

    repo = PostgresRepository.from_url()
    embedder = VoyageEmbedder()  # real Voyage query embeddings (input_type='query')

    result = probe(repo, embedder, ks)
    _print_report(result)
    if args.json:
        args.json.write_text(json.dumps(result, indent=2))
        print(f"  full JSON → {args.json}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
