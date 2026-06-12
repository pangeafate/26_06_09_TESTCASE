"""SP_031 I4+I7 — DB-free branch coverage for the serving path (`ask()` + `get_org_chart`).

These exercise the real `HelixQueryEngine` wiring through `FakeRepository` (no Postgres),
covering the branches the SP_030 `db`-integration gate cannot reach without a database:

- **I4** the per-`ask()` resolution memo — proves `resolve_entity` is called ≤1× per
  *distinct normalized* term, that a `None` miss is not re-queried within a call, and that
  the memo is **fresh per `ask()`** (two calls each re-resolve — it is NOT an instance-level
  cache that would leak a stale `None`/entity across requests).
- **I7** the genuine `ask()` route branches (multi-entity, route=`both` vs structured-only,
  contradictions-always-surfaced, synthesis-failure degradation) + the `get_org_chart`
  serving surface (the real home of `get_org_subtree` — `ask()` never calls it).
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from helixpay.contracts import (
    Chunk,
    Citation,
    Claim,
    Contradiction,
    Entity,
    OrgNode,
)
from helixpay.query import HelixQueryEngine

from fakes import FakeEmbedder, FakeRepository, FakeSynthesizer


class CountingRepo(FakeRepository):
    """Records every `resolve_entity` name argument so tests can assert call counts."""

    def __init__(self) -> None:
        super().__init__()
        self.resolve_calls: list[str] = []

    def resolve_entity(
        self,
        name: str,
        entity_type: Optional[str] = None,
        context: Optional[dict] = None,
    ) -> Optional[Entity]:
        self.resolve_calls.append(name)
        return super().resolve_entity(name, entity_type, context)


def _engine(repo, synth=None):
    return HelixQueryEngine(repo, FakeEmbedder(), synth or FakeSynthesizer(), k=8)


# --------------------------------------------------------------------------- #
# I4 — per-ask() resolution memo
# --------------------------------------------------------------------------- #
def test_resolve_entity_memoized_by_normalized_term():
    """A question mixing case variants of the same name must resolve it ≤1×."""
    repo = CountingRepo()
    repo.add_entity(Entity(id=1, canonical_name="Revenue", entity_type="metric"))
    repo.vocab = {"revenue": "revenue"}
    eng = _engine(repo)

    # "Revenue" and "revenue" both normalize to the same lookup; "Maria"/"maria" miss.
    eng.ask("What was Revenue and revenue growth for Maria and maria?")

    normalized = [n.strip().lower() for n in repo.resolve_calls]
    dupes = {k for k in normalized if normalized.count(k) > 1}
    assert not dupes, f"resolve_entity re-queried normalized terms: {dupes}"


def test_cached_miss_not_requeried_and_never_a_silent_pick():
    repo = CountingRepo()  # no entities seeded → every lookup misses
    eng = _engine(repo)
    bundle = eng.ask("Who does Maria report to and who does maria manage?")

    normalized = [n.strip().lower() for n in repo.resolve_calls]
    assert normalized.count("maria") == 1, "ambiguous miss should be cached, not re-queried"
    assert eng.last_trace["subject_ids"] == [], "a miss must never become a silent pick"
    assert bundle.contradictions == []


def test_memo_is_fresh_per_ask_not_instance_level():
    """Two ask() calls must each re-resolve — an instance-level cache would make the
    second call skip the repo entirely (and could serve a stale None after an ingest)."""
    repo = CountingRepo()
    repo.add_entity(Entity(id=1, canonical_name="Revenue", entity_type="metric"))
    eng = _engine(repo)

    eng.ask("What was Revenue growth?")
    first = len(repo.resolve_calls)
    assert first > 0
    repo.resolve_calls.clear()
    eng.ask("What was Revenue growth?")
    assert repo.resolve_calls, "second ask() did not re-resolve — memo leaked across calls"


# --------------------------------------------------------------------------- #
# I7 — genuine ask() route branches + get_org_chart serving surface
# --------------------------------------------------------------------------- #
def _two_entity_world(repo):
    repo.add_entity(Entity(id=1, canonical_name="Helix", entity_type="company"))
    repo.add_entity(Entity(id=2, canonical_name="Revenue", entity_type="metric"))
    repo.vocab = {"revenue": "revenue"}


def test_multi_entity_question_resolves_all_subjects():
    repo = FakeRepository()
    _two_entity_world(repo)
    eng = _engine(repo)
    eng.ask("What was Helix Revenue?")
    assert set(eng.last_trace["subject_ids"]) == {1, 2}


def test_route_both_runs_retrieval_leg():
    repo = FakeRepository()
    _two_entity_world(repo)
    repo.semantic = [(Chunk(id=7, document_id=1, ordinal=0, text="Helix grew."), 0.9)]
    eng = _engine(repo)
    eng.ask("What was Helix revenue?")  # metric question → route=both (planner)
    assert eng.last_trace["route"] == "both"
    assert eng.last_trace["retrieved_chunk_ids"] == [7]


def test_structured_only_route_skips_retrieval_leg():
    repo = FakeRepository()
    repo.add_entity(Entity(id=1, canonical_name="Maria", entity_type="person"))
    repo.semantic = [(Chunk(id=7, document_id=1, ordinal=0, text="x"), 0.9)]
    eng = _engine(repo)
    eng.ask("Who does Maria report to?")  # pure hierarchy → route=structured
    assert eng.last_trace["route"] == "structured"
    assert eng.last_trace["retrieved_chunk_ids"] == [], "structured-only must not retrieve"


def test_contradictions_always_surfaced_even_when_uncited():
    repo = FakeRepository()
    rid = repo.add_entity(Entity(id=1, canonical_name="Revenue", entity_type="metric"))
    repo.vocab = {"revenue": "revenue"}
    for cid, val in ((10, "SGD 14.2M"), (11, "SGD 13.9M")):
        repo.add_claim_row(
            Claim(id=cid, subject_entity_id=rid, predicate="revenue", object_value=val,
                  as_of=date(2026, 3, 31)),
            Citation(source_uri=f"data/{cid}.pdf", as_of=date(2026, 3, 31)),
        )
    repo.contradictions = [
        Contradiction(id=1, subject_entity_id=rid, predicate="revenue",
                      claim_a_id=10, claim_b_id=11, kind="value_conflict")
    ]
    # synthesizer cites nothing — the conflict must still surface in the bundle
    bundle = _engine(repo, FakeSynthesizer({"sentences": []})).ask("What was Revenue?")
    assert [c.id for c in bundle.contradictions] == [1]


def test_synthesis_failure_degrades_without_leaking():
    class _RaisingSynth(FakeSynthesizer):
        def synthesize(self, prompt: str, *, schema: dict) -> dict:
            raise RuntimeError("model boundary blew up")

    repo = FakeRepository()
    rid = repo.add_entity(Entity(id=1, canonical_name="Revenue", entity_type="metric"))
    repo.vocab = {"revenue": "revenue"}
    repo.contradictions = [
        Contradiction(id=1, subject_entity_id=rid, predicate="revenue",
                      claim_a_id=None, claim_b_id=None, kind="value_conflict")
    ]
    bundle = _engine(repo, _RaisingSynth()).ask("What was Revenue?")
    # degraded, not crashed: contradictions still present-and-surfaced, no uncited claims
    assert [c.id for c in bundle.contradictions] == [1]
    assert bundle.citations == []


def test_get_org_chart_returns_subtree():
    repo = FakeRepository()
    repo.org_tree = OrgNode(
        entity_id=1, name="CEO",
        children=[OrgNode(entity_id=2, name="VP", children=[], dotted_reports=[])],
        dotted_reports=[],
    )
    chart = _engine(repo).get_org_chart()
    assert chart["name"] == "CEO"
    assert [c["name"] for c in chart["children"]] == ["VP"]
