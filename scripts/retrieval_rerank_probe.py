#!/usr/bin/env python3
"""A/B retrieval experiment: equal RRF vs lexical-weighted RRF vs Voyage reranker.

Exploratory sibling of ``retrieval_recall_probe.py`` (read-only dev-tooling,
CLAUDE.md §15). It does NOT touch the frozen ``helixpay/query/retrieval.py`` — the
goal is to MEASURE whether a fusion-weight change (free) or a cross-encoder reranker
(paid per call) would lift the MCP ``search`` tool's recall@k, before any production
seam is changed.

For each golden bar-fact it embeds the value-free query once, pulls a wide candidate
pool (semantic top-N ∪ lexical top-N), and scores five rankings on the SAME pool:

  semantic      pgvector cosine only
  lexical       Postgres FTS only
  rrf-equal     current production fusion (equal weight) — the baseline
  rrf-wlex      RRF with the lexical list weighted ``--lex-weight`` (default 2.0)
  rerank        Voyage ``rerank-2.5`` cross-encoder over the union pool

A "hit@k" = some top-k chunk's source_uri matches the fact's (grader's _uri_matches).
Cost: one Voyage *embed* + one Voyage *rerank* call per fact (cents). No Anthropic.

Usage::

    DATABASE_URL=… VOYAGE_API_KEY=… uv run python -m scripts.retrieval_rerank_probe
    uv run python -m scripts.retrieval_rerank_probe --pool 30 --lex-weight 2.0 \
        --k 1,3,5,8,10,20 --json workspace/acceptance/retrieval_rerank.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from eval.run import _uri_matches, load_golden  # noqa: E402
from helixpay.config import load_config  # noqa: E402
from helixpay.query.clients import VoyageEmbedder  # noqa: E402
from scripts.retrieval_recall_probe import _hit_at_ks, _query_for  # noqa: E402

DEFAULT_KS = (1, 3, 5, 8, 10, 20)
SIGNALS = ("semantic", "lexical", "rrf-equal", "rrf-wlex", "rerank")
RRF_K = 60


def _weighted_rrf(ranked_lists: list[tuple[list, float]], k: int = RRF_K) -> list:
    """RRF with a per-list weight. ``score(c) = Σ w_list / (k + rank)``. Equal weights
    reproduce the production fusion exactly; a >1 weight on the lexical list lifts
    exact-name / metric-code matches that the semantic vectors under-rank."""
    scores: dict[int, float] = {}
    chunks: dict[int, object] = {}
    for ranking, weight in ranked_lists:
        for rank, chunk in enumerate(ranking, start=1):
            cid = chunk.id if chunk.id is not None else id(chunk)
            scores[cid] = scores.get(cid, 0.0) + weight / (k + rank)
            chunks.setdefault(cid, chunk)
    ordered = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return [chunks[cid] for cid, _ in ordered]


class _VoyageReranker:
    """Lazy Voyage rerank client (mirrors clients.VoyageEmbedder's lazy key/import)."""

    def __init__(self, model: str = "rerank-2.5") -> None:
        self._model = model
        self._client = None

    def _ensure(self):
        if self._client is None:
            import importlib

            voyageai = importlib.import_module("voyageai")
            self._client = voyageai.Client(api_key=load_config().voyage_api_key)
        return self._client

    def rerank(self, query: str, chunks: list) -> list:
        """Return ``chunks`` reordered most→least relevant by the cross-encoder."""
        if not chunks:
            return []
        docs = [c.text for c in chunks]
        result = self._ensure().rerank(query, docs, model=self._model, top_k=len(docs))
        # result.results: objects with .index into `docs`, sorted by relevance.
        return [chunks[r.index] for r in result.results]


def _uris_in_order(repo, chunks: list) -> list[str]:
    ids = [c.id for c in chunks if c.id is not None]
    by_id = {cit.chunk_id: cit for cit in repo.get_chunk_sources(ids)}
    out: list[str] = []
    for c in chunks:
        cit = by_id.get(c.id) if c.id is not None else None
        if cit and cit.source_uri:
            out.append(cit.source_uri)
    return out


def probe(repo, embedder, reranker, ks, pool: int, lex_weight: float) -> dict:
    golden = load_golden()
    facts = golden.bar_facts
    max_k = max(ks)

    with repo.conn.cursor() as cur:
        cur.execute("SELECT DISTINCT source_uri FROM documents WHERE source_uri IS NOT NULL")
        stored_uris = [r["source_uri"] for r in cur.fetchall()]

    def _present(uri: str) -> bool:
        return any(_uri_matches(uri, s) for s in stored_uris)

    rows = []
    for fact in facts:
        if not _present(fact.source_uri):
            rows.append({"id": fact.id, "status": "source-absent"})
            continue
        query = _query_for(fact)
        qvec = embedder.embed_query(query)
        sem = [c for c, _ in repo.search_semantic(qvec, pool)]
        lex = [c for c, _ in repo.search_lexical(query, pool)]

        rankings = {
            "semantic": sem,
            "lexical": lex,
            "rrf-equal": _weighted_rrf([(sem, 1.0), (lex, 1.0)]),
            "rrf-wlex": _weighted_rrf([(sem, 1.0), (lex, lex_weight)]),
        }
        # rerank over the union pool (dedup by chunk id, semantic order first).
        union, seen = [], set()
        for c in sem + lex:
            if c.id not in seen:
                seen.add(c.id)
                union.append(c)
        rankings["rerank"] = reranker.rerank(query, union)

        hits = {}
        for sig, chunks in rankings.items():
            uris = _uris_in_order(repo, chunks[:max_k])
            hits[sig] = _hit_at_ks(uris, fact.source_uri, ks)
        rows.append({"id": fact.id, "status": "scored", "query": query, "hits": hits})

    scored = [r for r in rows if r["status"] == "scored"]

    def _recall(sig: str, k: int) -> float:
        return sum(1 for r in scored if r["hits"][sig][k]) / len(scored) if scored else 0.0

    summary = {sig: {k: round(_recall(sig, k), 3) for k in ks} for sig in SIGNALS}
    misses = {
        sig: [r["id"] for r in scored if not r["hits"][sig][max_k]] for sig in SIGNALS
    }
    return {
        "ks": list(ks),
        "pool": pool,
        "lex_weight": lex_weight,
        "n_scored": len(scored),
        "recall": summary,
        "misses_at_maxk": misses,
        "rows": rows,
    }


def _print(result: dict) -> None:
    ks = result["ks"]
    print(
        f"\nReranker A/B (pool={result['pool']}, lex_weight={result['lex_weight']}, "
        f"scored={result['n_scored']}) — read-only experiment, frozen retrieval untouched\n"
    )
    header = "  signal       " + "".join(f"{('@' + str(k)):>8}" for k in ks)
    print(header)
    print("  " + "-" * (len(header) - 2))
    for sig in SIGNALS:
        cells = "".join(f"{result['recall'][sig][k]:>8.0%}" for k in ks)
        print(f"  {sig:<13}{cells}")
    print("")
    rr = result["misses_at_maxk"]["rerank"]
    print(f"  rerank misses at top-{max(ks)} ({len(rr)}): {', '.join(rr) if rr else 'NONE'}")
    print("")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Reranker / weighted-RRF A/B (read-only).")
    ap.add_argument("--k", default=",".join(str(k) for k in DEFAULT_KS))
    ap.add_argument("--pool", type=int, default=30, help="candidate pool per leg before fusion/rerank")
    ap.add_argument("--lex-weight", type=float, default=2.0, help="RRF weight on the lexical list")
    ap.add_argument("--model", default="rerank-2.5", help="Voyage rerank model")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(argv)

    ks = tuple(sorted({int(x) for x in args.k.split(",") if x.strip()}))
    from helixpay.db.repository import PostgresRepository  # lazy: needs DATABASE_URL

    repo = PostgresRepository.from_url()
    result = probe(repo, VoyageEmbedder(), _VoyageReranker(args.model), ks, args.pool, args.lex_weight)
    _print(result)
    if args.json:
        args.json.write_text(json.dumps(result, indent=2))
        print(f"  full JSON → {args.json}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
