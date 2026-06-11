"""Stratified sampler for the manual audit (pure, deterministic).

Pure random over-samples the dominant predicate and the easy middle. This sampler:

* reserves up to ``suspicious_fraction`` of the budget for ``suspicious`` records
  (oversampling exactly where precision bugs hide), then
* spreads the remainder round-robin across strata (default = predicate) so one busy
  predicate can't crowd out the rest.

Deterministic: same ``seed`` → same sample, so an audit is reproducible.
"""

from __future__ import annotations

import random
from typing import Callable, Iterable, Optional

from helixpay.audit.models import ClaimRecord


def stratified_sample(
    records: Iterable[ClaimRecord],
    *,
    k: int,
    seed: int,
    stratum: Callable[[ClaimRecord], str] = lambda r: r.predicate,
    suspicious: Optional[Callable[[ClaimRecord], bool]] = None,
    suspicious_fraction: float = 0.5,
) -> list[ClaimRecord]:
    pool = list(records)
    if k <= 0 or not pool:
        return []
    rng = random.Random(seed)

    chosen: list[ClaimRecord] = []
    chosen_ids: set[int] = set()

    if suspicious is not None:
        susp = [r for r in pool if suspicious(r)]
        rng.shuffle(susp)
        n_susp = min(len(susp), int(round(k * suspicious_fraction)))
        for r in susp[:n_susp]:
            chosen.append(r)
            chosen_ids.add(r.id)

    buckets: dict[str, list[ClaimRecord]] = {}
    for r in pool:
        if r.id in chosen_ids:
            continue
        buckets.setdefault(stratum(r), []).append(r)
    for bucket in buckets.values():
        rng.shuffle(bucket)

    keys = sorted(buckets)
    rng.shuffle(keys)  # seed-randomized which stratum leads, but reproducible
    i = 0
    while len(chosen) < k and any(buckets[key] for key in keys):
        key = keys[i % len(keys)]
        if buckets[key]:
            r = buckets[key].pop()
            chosen.append(r)
            chosen_ids.add(r.id)
        i += 1

    return chosen[:k]


__all__ = ["stratified_sample"]
