"""Unit tests for the Voyage embedding seam (no real API, injected stub client)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from helixpay.config import EMBEDDING_DIM
from helixpay.ingest.embed import VoyageEmbedder


class StubVoyage:
    """Mimics voyageai.Client.embed: returns ``.embeddings`` (1024-d per text).

    Encodes ``len(text)`` into element 0 so tests can assert order is preserved.
    """

    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        self.dim = dim
        self.calls: list[list[str]] = []

    def embed(self, texts, *, model: str, input_type: str):
        self.calls.append(list(texts))
        embeddings = [[float(len(t))] + [0.0] * (self.dim - 1) for t in texts]
        return SimpleNamespace(embeddings=embeddings)


def test_embed_returns_one_vector_per_text_in_order():
    stub = StubVoyage()
    emb = VoyageEmbedder(client=stub)
    texts = ["a", "bbb", "cc", "dddd"]

    vecs = emb.embed(texts)

    assert len(vecs) == len(texts)
    assert [v[0] for v in vecs] == [1.0, 3.0, 2.0, 4.0]  # order preserved
    assert all(len(v) == EMBEDDING_DIM for v in vecs)


def test_embed_batches_large_inputs():
    stub = StubVoyage()
    emb = VoyageEmbedder(client=stub, batch_size=2)

    vecs = emb.embed(["t0", "t1", "t2", "t3", "t4"])

    assert len(vecs) == 5
    assert [len(c) for c in stub.calls] == [2, 2, 1]  # batched 2+2+1


def test_embed_empty_input_makes_no_call():
    stub = StubVoyage()
    emb = VoyageEmbedder(client=stub)

    assert emb.embed([]) == []
    assert stub.calls == []


def test_wrong_dimension_is_rejected():
    stub = StubVoyage(dim=512)  # server returned the wrong width
    emb = VoyageEmbedder(client=stub)

    with pytest.raises(ValueError, match="dimension"):
        emb.embed(["x"])


def test_count_mismatch_is_rejected():
    class ShortStub(StubVoyage):
        def embed(self, texts, *, model, input_type):
            self.calls.append(list(texts))
            return SimpleNamespace(embeddings=[[0.0] * self.dim])  # one vector for many texts

    emb = VoyageEmbedder(client=ShortStub())
    with pytest.raises(ValueError, match="count"):
        emb.embed(["a", "b"])
