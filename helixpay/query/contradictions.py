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
    from helixpay.contracts import Repository


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


__all__ = ["find", "relevant"]
