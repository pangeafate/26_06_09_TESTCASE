"""Hybrid retrieval: semantic + lexical → reciprocal-rank fusion (RRF).

We fuse two cheap, complementary signals from the ``Repository``:

* ``search_semantic`` — pgvector cosine over Voyage query embeddings (good at
  paraphrase / concept match).
* ``search_lexical`` — Postgres FTS (good at exact names, metric codes, numbers).

**RRF, not a trained reranker** (explicit scope cut, spec §11): at this corpus
size a cross-encoder is marginal, and RRF needs no training, no extra model, and
is robust to the two signals living on different score scales — it ranks by
*position*, not by raw score, so a 0..1 cosine and an unbounded ``ts_rank`` fuse
cleanly. Equal weight, ``RRF_K = 60`` (the canonical constant from Cormack et
al.). Ties break on ascending chunk id so retrieval is deterministic (tests +
reproducible answer logs).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from helixpay.contracts import Chunk

if TYPE_CHECKING:  # avoid importing the seam/Protocol at module load
    from helixpay.contracts import Repository
    from helixpay.query.clients import Embedder

RRF_K = 60


def reciprocal_rank_fusion(
    rankings: list[list[Chunk]], k: int = RRF_K
) -> list[tuple[Chunk, float]]:
    """Fuse ranked chunk lists by RRF.

    ``score(chunk) = Σ_lists 1 / (k + rank)`` with ``rank`` 1-based within each
    list. A chunk surfaced by multiple signals accrues multiple terms and so
    outranks a chunk seen by one. Deterministic tie-break: ascending chunk id.
    """
    scores: dict[int, float] = {}
    chunks: dict[int, Chunk] = {}
    for ranking in rankings:
        for rank, chunk in enumerate(ranking, start=1):
            cid = chunk.id if chunk.id is not None else id(chunk)
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
            chunks.setdefault(cid, chunk)
    ordered = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return [(chunks[cid], score) for cid, score in ordered]


def hybrid_search(
    repo: "Repository",
    embedder: "Embedder",
    query: str,
    k: int = 8,
    rrf_k: int = RRF_K,
) -> list[tuple[Chunk, float]]:
    """Embed the query once, run semantic + lexical retrieval, fuse, return top-k."""
    qvec = embedder.embed_query(query)
    semantic = [chunk for chunk, _ in repo.search_semantic(qvec, k)]
    lexical = [chunk for chunk, _ in repo.search_lexical(query, k)]
    fused = reciprocal_rank_fusion([semantic, lexical], k=rrf_k)
    return fused[:k]


__all__ = ["RRF_K", "reciprocal_rank_fusion", "hybrid_search"]
