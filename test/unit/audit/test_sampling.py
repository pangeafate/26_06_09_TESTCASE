"""Stratified sampler — determinism, suspicious oversampling, spread, bounds."""

from __future__ import annotations

from datetime import date

from helixpay.audit.models import ClaimRecord
from helixpay.audit.sampling import stratified_sample


def _rec(i: int, predicate: str = "revenue", suspicious: bool = False) -> ClaimRecord:
    return ClaimRecord(
        id=i,
        subject_entity_id=None if suspicious else 1,
        subject_name=None if suspicious else "HelixPay",
        subject_type="other",
        predicate=predicate,
        object_value="x",
        as_of=date(2026, 3, 31),
        confidence=0.9,
        superseded_by=None,
        source_chunk_id=i,
        document_id=1,
        chunk_text="x",
        document_source_uri="data/x.md",
    )


def _suspicious(r: ClaimRecord) -> bool:
    return r.subject_entity_id is None


def test_deterministic_same_seed():
    pool = [_rec(i, predicate=f"p{i % 4}") for i in range(40)]
    a = [r.id for r in stratified_sample(pool, k=10, seed=42)]
    b = [r.id for r in stratified_sample(pool, k=10, seed=42)]
    assert a == b


def test_different_seed_differs():
    pool = [_rec(i, predicate=f"p{i % 4}") for i in range(40)]
    a = [r.id for r in stratified_sample(pool, k=10, seed=1)]
    b = [r.id for r in stratified_sample(pool, k=10, seed=2)]
    assert a != b


def test_respects_k_and_no_duplicates():
    pool = [_rec(i) for i in range(30)]
    out = stratified_sample(pool, k=8, seed=7)
    assert len(out) == 8
    assert len({r.id for r in out}) == 8


def test_k_larger_than_pool_returns_all():
    pool = [_rec(i) for i in range(5)]
    out = stratified_sample(pool, k=50, seed=7)
    assert {r.id for r in out} == {0, 1, 2, 3, 4}


def test_empty_and_nonpositive_k():
    assert stratified_sample([], k=5, seed=1) == []
    assert stratified_sample([_rec(1)], k=0, seed=1) == []


def test_suspicious_oversampled():
    pool = [_rec(i, suspicious=(i < 5)) for i in range(40)]  # 5 suspicious, 35 clean
    out = stratified_sample(
        pool, k=8, seed=3, suspicious=_suspicious, suspicious_fraction=0.5
    )
    n_susp = sum(1 for r in out if _suspicious(r))
    # ~half the budget (4) reserved for suspicious; all 5 available, so >= 4 appear.
    assert n_susp >= 4


def test_spreads_across_strata():
    pool = [_rec(i, predicate=f"p{i % 5}") for i in range(50)]
    out = stratified_sample(pool, k=10, seed=11)
    assert len({r.predicate for r in out}) >= 4  # not all from one predicate
