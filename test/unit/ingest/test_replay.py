"""Replay tier: record an extraction once, then re-run the post-LLM pipeline from
cache with zero LLM calls. Round-trip fidelity + cache-miss behavior are the contract."""

from __future__ import annotations

import pytest

from helixpay.config import EMBEDDING_DIM
from helixpay.contracts import Chunk
from helixpay.ingest.extract.extractor import ChunkContext
from helixpay.ingest.extract.schemas import ClaimOut, ExtractionOut, RelationOut
from helixpay.ingest.replay import (
    CachingExtractor,
    ReplayCacheMiss,
    ReplayExtractor,
    _cache_path,
    _ConstantEmbedder,
)


class _SpyExtractor:
    """Records call count so we can assert the replay path never invokes the inner LLM."""

    def __init__(self, out: ExtractionOut) -> None:
        self._out = out
        self.calls = 0

    def extract(self, chunk: Chunk, ctx: ChunkContext) -> ExtractionOut:
        self.calls += 1
        return self._out


def _ctx(uri: str = "data/dashboards/april-2026-kpi-dashboard.html") -> ChunkContext:
    return ChunkContext(source_type="html", source_uri=uri, as_of="2026-03-31")


def _out() -> ExtractionOut:
    return ExtractionOut(
        claims=[
            ClaimOut(
                subject="HelixPay",
                subject_type="other",
                predicate="revenue",
                evidence="Q1 2026 Revenue (SGD) 14.2M",
                object_value="SGD 14.2M",
                as_of="2026-03-31",
                confidence=0.91,
                hypothetical=False,
            )
        ],
        relations=[
            RelationOut(
                from_entity="Sara Wijaya",
                to_entity="Daniel Tan",
                link_type="reports_to",
            )
        ],
    )


def test_caching_extractor_records_then_replay_roundtrips(tmp_path):
    chunk = Chunk(ordinal=0, text="Q1 2026 Revenue (SGD) 14.2M (−11% vs plan).")
    ctx = _ctx()
    spy = _SpyExtractor(_out())

    caching = CachingExtractor(spy, tmp_path)
    recorded = caching.extract(chunk, ctx)
    assert spy.calls == 1
    assert recorded == _out()

    # Replay reads from disk and must NOT touch any inner extractor.
    replay = ReplayExtractor(tmp_path)
    replayed = replay.extract(chunk, ctx)
    assert spy.calls == 1  # inner never called again on replay
    assert replayed == recorded  # field-equal pydantic round-trip


def test_replay_preserves_every_claim_field(tmp_path):
    chunk = Chunk(ordinal=0, text="…")
    ctx = _ctx()
    CachingExtractor(_SpyExtractor(_out()), tmp_path).extract(chunk, ctx)

    claim = ReplayExtractor(tmp_path).extract(chunk, ctx).claims[0]
    assert claim.confidence == 0.91
    assert claim.evidence == "Q1 2026 Revenue (SGD) 14.2M"
    assert claim.object_value == "SGD 14.2M"
    assert claim.hypothetical is False
    assert claim.subject_type == "other"


def test_replay_cache_miss_raises(tmp_path):
    with pytest.raises(ReplayCacheMiss):
        ReplayExtractor(tmp_path).extract(Chunk(ordinal=0, text="x"), _ctx())


def test_distinct_source_uris_do_not_collide(tmp_path):
    # Same ordinal, different documents → distinct cache entries (no text-hash collision).
    chunk = Chunk(ordinal=0, text="boilerplate header repeated across docs")
    a_out = ExtractionOut(
        claims=[ClaimOut(subject="A", predicate="revenue", object_value="1")]
    )
    b_out = ExtractionOut(
        claims=[ClaimOut(subject="B", predicate="revenue", object_value="2")]
    )

    CachingExtractor(_SpyExtractor(a_out), tmp_path).extract(chunk, _ctx("data/a.md"))
    CachingExtractor(_SpyExtractor(b_out), tmp_path).extract(chunk, _ctx("data/b.md"))

    replay = ReplayExtractor(tmp_path)
    assert replay.extract(chunk, _ctx("data/a.md")) == a_out
    assert replay.extract(chunk, _ctx("data/b.md")) == b_out


def test_cache_key_disambiguates_uris_that_slugify_alike(tmp_path):
    # "data/a b.md" and "data/a/b.md" collapse to the same readable slug; the source_uri
    # digest must keep their cache files distinct.
    p1 = _cache_path(tmp_path, "data/a b.md", 0)
    p2 = _cache_path(tmp_path, "data/a/b.md", 0)
    assert p1 != p2


def test_recording_an_existing_chunk_is_a_cache_hit_and_skips_the_paid_call(tmp_path):
    chunk = Chunk(ordinal=0, text="…")
    ctx = _ctx()
    spy = _SpyExtractor(_out())

    first = CachingExtractor(spy, tmp_path)
    first.extract(chunk, ctx)
    assert spy.calls == 1

    # A fresh CachingExtractor over the same cache must NOT re-bill the inner extractor.
    spy2 = _SpyExtractor(_out())
    second = CachingExtractor(spy2, tmp_path)
    assert second.extract(chunk, ctx) == _out()
    assert spy2.calls == 0  # cache hit — paid call skipped

    # force=True overrides the hit and re-extracts.
    spy3 = _SpyExtractor(_out())
    CachingExtractor(spy3, tmp_path, force=True).extract(chunk, ctx)
    assert spy3.calls == 1


def test_relation_as_of_survives_the_round_trip(tmp_path):
    out = ExtractionOut(
        relations=[
            RelationOut(
                from_entity="Sara Wijaya",
                to_entity="Daniel Tan",
                link_type="reports_to",
                as_of="2026-04-15",
                confidence=0.8,
            )
        ]
    )
    chunk = Chunk(ordinal=2, text="…")
    ctx = _ctx("data/org-chart.md")
    CachingExtractor(_SpyExtractor(out), tmp_path).extract(chunk, ctx)

    rel = ReplayExtractor(tmp_path).extract(chunk, ctx).relations[0]
    assert rel.as_of == "2026-04-15"
    assert rel.confidence == 0.8


def test_constant_embedder_returns_fixed_dimension_zero_vectors():
    vecs = _ConstantEmbedder().embed(["a", "b", "c"])
    assert len(vecs) == 3
    assert all(len(v) == EMBEDDING_DIM and set(v) == {0.0} for v in vecs)
