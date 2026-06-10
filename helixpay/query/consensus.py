"""Consensus / dissent rollup (SP_012, gap 5) — a pure, no-LLM grouping step.

The ontology never collapses conflicting facts, so a metric like *runway* can be 7
coexisting claims (``18 months`` / ``eighteen months`` / ``~18 months`` / … / ``24
months``). Dumping all seven is a poor answer; the ranking signal (corroborating count,
freshest ``as_of``) is captured but never surfaced. This module rolls the claims for one
predicate into a single **consensus** value plus explicit **dissent** — and never
collapses a genuine disagreement (CLAUDE.md "never collapse conflicting facts"): every
distinct value survives as either the consensus or a dissent bucket.

Grouping (pinned at the SP_012 pre-impl review):
* group by ``canonical_predicate(predicate)`` FIRST — so ``ARR`` and ``revenue`` never
  co-group even when they share a number (the planted-conflict failure mode);
* within a predicate, bucket members by ``values_equal`` (the shared SP_009 normalizer,
  which folds ``eighteen months`` ≡ ``18 months`` and ``SGD 14.2M`` ≡ ``14.2 million``)
  rather than a raw string key, because numeric equivalence can span distinct canonical
  texts;
* consensus = the largest bucket; deterministic tie-break is freshest ``as_of`` then
  smallest claim id (no ``Math.random`` / unordered-dict dependence);
* a predicate with a single claim has nothing to consolidate and is skipped.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable, Optional

from helixpay.contracts import Claim
from helixpay.ingest.normalize import values_equal

_OLDEST = date.min


@dataclass(frozen=True)
class Bucket:
    """One distinct value within a predicate: its representative text + members."""

    value: Optional[str]
    claim_ids: list[int]
    count: int
    freshest_as_of: Optional[date]


@dataclass(frozen=True)
class ConsensusGroup:
    """The rollup for one canonical predicate: the consensus bucket flattened + dissent."""

    predicate: str
    consensus_value: Optional[str]
    corroborating_count: int
    freshest_as_of: Optional[date]
    member_ids: list[int]
    dissent: list[Bucket]


def _freshest(claims: list[Claim]) -> Optional[date]:
    dated = [c.as_of for c in claims if c.as_of is not None]
    return max(dated) if dated else None


def _bucket(members: list[Claim]) -> Bucket:
    # representative value = the smallest-id member with a non-null value (deterministic),
    # falling back to smallest id so the bucket always has a representative.
    valued = [c for c in members if c.object_value is not None]
    rep = min(valued or members, key=lambda c: c.id or 0)
    ids = sorted(c.id for c in members if c.id is not None)
    return Bucket(
        value=rep.object_value,
        claim_ids=ids,
        count=len(members),
        freshest_as_of=_freshest(members),
    )


def rollup(
    claims: list[Claim], canonicalize: Callable[[str], str]
) -> list[ConsensusGroup]:
    """Roll ``claims`` up into one ``ConsensusGroup`` per canonical predicate that has
    two or more claims. Pure: ``canonicalize`` is ``Repository.canonical_predicate`` (or
    any equivalent map); no I/O, no LLM."""
    by_pred: dict[str, list[Claim]] = {}
    for c in claims:
        by_pred.setdefault(canonicalize(c.predicate), []).append(c)

    groups: list[ConsensusGroup] = []
    for pred in sorted(by_pred):
        members = by_pred[pred]
        if len(members) < 2:
            continue  # a lone claim is not a consensus
        # bucket by value equivalence (values_equal handles numeric + canonical-text)
        buckets: list[list[Claim]] = []
        for c in members:
            for b in buckets:
                if values_equal(c.object_value, b[0].object_value):
                    b.append(c)
                    break
            else:
                buckets.append([c])
        ranked = [_bucket(b) for b in buckets]
        # consensus = most members; tie → freshest, then smallest claim id. Stable sorts
        # compose, so apply the weakest key first and the strongest last.
        ranked.sort(key=lambda b: b.claim_ids[0] if b.claim_ids else 0)
        ranked.sort(key=lambda b: b.freshest_as_of or _OLDEST, reverse=True)
        ranked.sort(key=lambda b: b.count, reverse=True)
        top, dissent = ranked[0], ranked[1:]
        groups.append(
            ConsensusGroup(
                predicate=pred,
                consensus_value=top.value,
                corroborating_count=top.count,
                freshest_as_of=top.freshest_as_of,
                member_ids=top.claim_ids,
                dissent=dissent,
            )
        )
    return groups


__all__ = ["Bucket", "ConsensusGroup", "rollup"]
