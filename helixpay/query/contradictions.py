"""Contradiction surfacing.

Contradictions are first-class rows the answer layer must surface (never silently
resolve). This module gathers the ones relevant to a question by **two** paths,
unioned, because a topic can name either a subject or a metric and the two can
diverge (review arch-H1):

* **subject** — ``resolve_entity(topic)`` → ``get_contradictions(subject_id)``.
* **predicate** — ``canonical_predicate(topic)`` matched against each
  contradiction's predicate (filtering on the *canonical* key, not the raw
  string, or "ARR" vs "annual recurring revenue" would miss — review code-H2).

``arr`` and ``revenue`` are distinct canonical keys, so ``find("ARR")`` honestly
returns ``[]`` when the only seeded conflict is on ``revenue`` (it is not a bug;
the planted fixture conflict is a revenue value-conflict).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from helixpay.contracts import Contradiction

if TYPE_CHECKING:
    from helixpay.contracts import Claim, Repository

# Human labels for the stored ``ContradictionKind`` enum (models.py). DRAGged-style
# typing tells the synthesizer the *kind* of conflict before it writes (+5–9pp on correct
# articulation per the query design doc). The label vocabulary is aligned to the enum —
# there is no separate "opinion" key; ``source_disagreement`` is the source/opinion case.
_KIND_LABELS = {
    "value_conflict": "value",
    "temporal": "temporal",
    "source_disagreement": "source disagreement",
}


def label_for(c: Contradiction, claims_by_id: dict[int, "Claim"]) -> str:
    """Type a surfaced conflict for the synthesis prompt.

    Trusts the stored ``Contradiction.kind`` when present (never re-derives a value that
    is already authoritative). Only when ``kind`` is unset (``None`` / unknown) does it
    infer: a link-pair conflict is ``relationship``; otherwise ``temporal`` when both
    claim sides are dated and disagree, else ``value``. Pure — the caller passes the
    already-gathered claim map, so this makes no DB read (avoids an N+1)."""
    if c.kind in _KIND_LABELS:
        return _KIND_LABELS[c.kind]
    if c.kind is not None:
        # A stored kind we don't have a friendly label for (e.g. a future enum value):
        # trust it and pass it through verbatim rather than silently re-deriving.
        return c.kind
    if c.link_a_id is not None or c.link_b_id is not None:
        return "relationship"
    a = claims_by_id.get(c.claim_a_id) if c.claim_a_id is not None else None
    b = claims_by_id.get(c.claim_b_id) if c.claim_b_id is not None else None
    if a is not None and b is not None and a.as_of is not None and b.as_of is not None:
        if a.as_of != b.as_of:
            return "temporal"
    return "value"


def _key(c: Contradiction) -> object:
    return c.id if c.id is not None else (c.claim_a_id, c.claim_b_id)


def _collect(
    repo: "Repository", subject_ids: set[int], topics: list[str]
) -> list[Contradiction]:
    out: dict[object, Contradiction] = {}
    for sid in subject_ids:
        for c in repo.get_contradictions(subject_id=sid):
            out[_key(c)] = c
    if topics:
        # Canonicalize once per distinct topic, then predicate-match. This is the
        # path that catches a metric conflict even when the metric's *entity*
        # never resolved (review code-C2) — e.g. "What was Q1 revenue?".
        canon = {repo.canonical_predicate(t) for t in topics}
        for c in repo.get_contradictions():
            if c.predicate is not None and c.predicate in canon:
                out[_key(c)] = c
    return list(out.values())


def _subject_ids_for_topic(repo: "Repository", topic: str) -> set[int]:
    ids: set[int] = set()
    ent = repo.resolve_entity(topic)
    if ent is not None and ent.id is not None:
        ids.add(ent.id)
    return ids


def find(repo: "Repository", topic: Optional[str] = None) -> list[Contradiction]:
    """Public ``find_contradictions`` body. ``topic=None`` → every contradiction."""
    if topic is None:
        return repo.get_contradictions()
    return _collect(repo, _subject_ids_for_topic(repo, topic), [topic])


def relevant(
    repo: "Repository",
    subject_ids: list[int],
    topics: Optional[list[str]] = None,
) -> list[Contradiction]:
    """Contradictions relevant to an ``ask`` — across resolved subjects AND any
    canonicalized topic term (so a metric conflict surfaces even when the metric
    entity did not resolve from the question)."""
    return _collect(repo, set(subject_ids), topics or [])


__all__ = ["find", "relevant", "label_for"]
