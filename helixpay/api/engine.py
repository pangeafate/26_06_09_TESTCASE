"""The engine seam for the exposure layer (MCP / FastAPI / CLI).

The adapters are **thin** pass-throughs over the frozen ``QueryEngine`` Protocol
(``helixpay.contracts``). They depend only on that four-method surface — ``ask``,
``get_entity``, ``get_org_chart``, ``find_contradictions`` — so swapping the mock for
Agent 3's real engine requires **no adapter change**.

Two MCP tools named by the spec (``get_sources``, ``search``) are *retrieval* surfaces
that the frozen Protocol does not carry. We model them as an **optional extension**
(``ExposureEngine``) rather than forking the frozen type: the four core tools call the
guaranteed Protocol methods directly, while the two retrieval tools dispatch through a
guarded helper that degrades to a structured "unavailable" payload if the injected engine
does not implement them.

Dependency injection: ``get_engine()`` returns the active engine (defaulting to the
in-memory ``MockQueryEngine`` so the surfaces work before Agent 3 lands); production /
tests call ``set_engine(...)`` to swap it. The default is deliberately the mock — wiring
the real engine is a single ``set_engine`` call at startup, not an adapter change.
"""

from __future__ import annotations

from datetime import date
from typing import Optional, Protocol, runtime_checkable

from helixpay.contracts import (
    AnswerBundle,
    Citation,
    Contradiction,
    EntityDetail,
    OrgNode,
    QueryEngine,
)


@runtime_checkable
class ExposureEngine(QueryEngine, Protocol):
    """The frozen ``QueryEngine`` plus the two optional retrieval surfaces the MCP
    tool list names. An engine that implements only ``QueryEngine`` is still a valid
    injection target — the retrieval tools degrade gracefully (see ``server.py``)."""

    def get_sources(self) -> list[dict]:
        """The documents/sources backing the ontology, each with its ``as_of``."""
        ...

    def search(self, query: str, k: int = 10) -> list[dict]:
        """Raw retrieval over chunks (hybrid semantic+lexical), no synthesis."""
        ...


# --------------------------------------------------------------------------- #
# In-memory mock — the default engine until Agent 3's real one is wired in.    #
# Deterministic canned data so the surfaces are demonstrable and testable.     #
# --------------------------------------------------------------------------- #
class MockQueryEngine:
    """A deterministic, dependency-free ``ExposureEngine`` for dev + tests.

    It carries a planted contradiction so the "contradictions are surfaced, never
    hidden" invariant is observable end-to-end through every surface.
    """

    def ask(self, question: str) -> AnswerBundle:
        return AnswerBundle(
            answer=(
                f"[mock] HelixPay's reported Q1 revenue figures disagree across sources "
                f"(re: {question.strip()})."
            ),
            citations=[
                Citation(
                    source_uri="data/financials/q1_board_deck.pdf",
                    as_of=date(2025, 4, 15),
                    snippet="Q1 revenue: $4.2M",
                    claim_id=101,
                    chunk_id=11,
                ),
                Citation(
                    source_uri="data/dashboards/metrics.html",
                    as_of=date(2025, 5, 2),
                    snippet="Q1 revenue: $3.9M",
                    claim_id=102,
                    chunk_id=22,
                ),
            ],
            contradictions=self.find_contradictions("revenue"),
            as_of_coverage={"revenue": "2025-04-15..2025-05-02"},
            confidence=0.62,
        )

    def get_entity(self, name: str) -> EntityDetail:
        detail: EntityDetail = {
            "entity": {"id": 1, "canonical_name": name, "entity_type": "person"},
            "aliases": [name, f"{name} (alt)"],
            "claims": [
                {
                    "id": 201,
                    "predicate": "title",
                    "object_value": "VP Engineering",
                    "as_of": "2025-03-01",
                }
            ],
            "links": [{"link_type": "reports_to", "to_entity_id": 9, "as_of": "2025-03-01"}],
        }
        return detail

    def get_org_chart(self, as_of: Optional[date] = None) -> OrgNode:
        node: OrgNode = {
            "entity_id": 9,
            "name": "Tan Wei",
            "role": "CEO",
            "as_of": (as_of.isoformat() if as_of else "2025-05-01"),
            "reports_to": None,
            "children": [
                {
                    "entity_id": 1,
                    "name": "Maria Santos",
                    "role": "VP Engineering",
                    "as_of": "2025-03-01",
                    "reports_to": 9,
                    "children": [],
                    "dotted_reports": [],
                }
            ],
            "dotted_reports": [],
        }
        return node

    def find_contradictions(self, topic: Optional[str] = None) -> list[Contradiction]:
        return [
            Contradiction(
                id=1,
                subject_entity_id=5,
                predicate="annual recurring revenue",
                claim_a_id=101,
                claim_b_id=102,
                kind="value_conflict",
                note=(
                    "Q1 revenue reported as $4.2M (board deck, 2025-04-15) vs $3.9M "
                    "(metrics dashboard, 2025-05-02)."
                ),
            )
        ]

    # --- optional retrieval surfaces (ExposureEngine extension) ------------- #
    def get_sources(self) -> list[dict]:
        return [
            {"source_uri": "data/financials/q1_board_deck.pdf", "source_type": "pdf",
             "as_of": "2025-04-15", "title": "Q1 Board Deck"},
            {"source_uri": "data/dashboards/metrics.html", "source_type": "html",
             "as_of": "2025-05-02", "title": "Metrics Dashboard"},
        ]

    def search(self, query: str, k: int = 10) -> list[dict]:
        return [
            {"chunk_id": 11, "document_id": 1, "score": 0.91,
             "text": f"... Q1 revenue: $4.2M ... (matched: {query})"},
            {"chunk_id": 22, "document_id": 2, "score": 0.78,
             "text": f"... Q1 revenue: $3.9M ... (matched: {query})"},
        ][:k]


# --------------------------------------------------------------------------- #
# Provider — the single swap seam.                                            #
# --------------------------------------------------------------------------- #
_engine: QueryEngine = MockQueryEngine()


def get_engine() -> QueryEngine:
    """Return the active engine. Adapters call this at request time (never at import
    time) so a ``set_engine`` swap takes effect without rebuilding the surfaces."""
    return _engine


def set_engine(engine: QueryEngine) -> None:
    """Swap the active engine. Production wires Agent 3's real ``QueryEngine`` here at
    startup; tests inject a ``MockQueryEngine``. This is the only change needed to go
    from mock to real — the adapters are untouched."""
    global _engine
    _engine = engine


__all__ = ["ExposureEngine", "MockQueryEngine", "get_engine", "set_engine"]
