"""Hybrid retrieval + reciprocal-rank fusion."""

from __future__ import annotations

from helixpay.contracts import Chunk
from helixpay.query.retrieval import RRF_K, hybrid_search, reciprocal_rank_fusion


def _c(cid: int) -> Chunk:
    return Chunk(id=cid, document_id=1, ordinal=cid, text=f"chunk {cid}")


def test_rrf_rewards_items_ranked_in_both_lists():
    # chunk 1 is mid in both lists; chunk 2 is top of one only.
    semantic = [_c(2), _c(1)]   # 2 then 1
    lexical = [_c(3), _c(1)]    # 3 then 1
    fused = reciprocal_rank_fusion([semantic, lexical])
    order = [c.id for c, _ in fused]
    # chunk 1 appears in both (rank2+rank2) and must outrank 2 and 3 (each single-list top)
    assert order[0] == 1
    # 1/(K+1) (single top) for 2 and 3; 2*(1/(K+2)) for 1
    assert order[0] == 1 and set(order) == {1, 2, 3}


def test_rrf_score_formula():
    fused = reciprocal_rank_fusion([[_c(5)]])
    chunk, score = fused[0]
    assert chunk.id == 5
    assert abs(score - 1.0 / (RRF_K + 1)) < 1e-12


def test_rrf_tie_break_is_ascending_chunk_id():
    # chunk 7 and chunk 4 each appear once at rank 0 → identical RRF score.
    fused = reciprocal_rank_fusion([[_c(7)], [_c(4)]])
    scores = {c.id: s for c, s in fused}
    assert abs(scores[7] - scores[4]) < 1e-12  # equal score
    assert [c.id for c, _ in fused] == [4, 7]   # lower id first


def test_hybrid_search_fuses_repo_semantic_and_lexical(repo, embedder):
    repo.semantic = [(_c(2), 0.9), (_c(1), 0.5)]
    repo.lexical = [(_c(3), 2.0), (_c(1), 1.0)]
    fused = hybrid_search(repo, embedder, "q1 revenue", k=8)
    order = [c.id for c, _ in fused]
    assert order[0] == 1              # in both lists
    assert embedder.calls == ["q1 revenue"]   # query was embedded once


def test_hybrid_search_respects_k(repo, embedder):
    repo.semantic = [(_c(1), 1.0), (_c(2), 0.9), (_c(3), 0.8)]
    repo.lexical = []
    fused = hybrid_search(repo, embedder, "q", k=2)
    assert len(fused) == 2
