"""The engine seam for the exposure layer (MCP / FastAPI / CLI).

The adapters are **thin** pass-throughs over the frozen ``QueryEngine`` Protocol
(``helixpay.contracts``). They depend only on that four-method surface — ``ask``,
``get_entity``, ``get_org_chart``, ``find_contradictions`` — so swapping the mock for
Agent 3's real engine requires **no adapter change**.

Eight MCP tools beyond the frozen four are *optional* surfaces the Protocol does not carry:
the SP_022 retrieval primitives (``get_sources``, ``search``, ``fetch``, ``list_entities``)
and the SP_023 graph/temporal reads (``get_timeline``, ``get_relationships``, ``list_metrics``,
``get_claims_by_predicate``). We model them as an **optional extension** (``ExposureEngine``)
rather than forking the frozen type: the four core tools call the guaranteed Protocol methods
directly, while the eight optional tools dispatch through a guarded helper that degrades to a
structured "unavailable" payload if the injected engine does not implement them.

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
    """The frozen ``QueryEngine`` plus the eight optional surfaces the MCP tool list names —
    the SP_022 retrieval primitives (``get_sources``, ``search``, ``fetch``, ``list_entities``)
    and the SP_023 graph/temporal reads (``get_timeline``, ``get_relationships``,
    ``list_metrics``, ``get_claims_by_predicate``). An engine that implements only
    ``QueryEngine`` is still a valid injection target — the optional tools degrade gracefully
    to an "unavailable" payload (see ``server.py``)."""

    def get_sources(self) -> list[dict]:
        """The documents/sources backing the ontology, each with its ``as_of``."""
        ...

    def search(self, query: str, k: int = 10) -> list[dict]:
        """Raw retrieval over chunks (hybrid semantic+lexical), no synthesis."""
        ...

    def fetch(self, id: str) -> dict:
        """The full text + provenance of a single chunk by id (from ``search``)."""
        ...

    def list_entities(self, entity_type: Optional[str] = None) -> list[dict]:
        """Enumerate ontology entities, optionally filtered to one ``entity_type``."""
        ...

    def get_timeline(self, entity: str, predicate: str) -> dict:
        """The chronological claim history (supersession chain + coexisting values) for an
        entity's predicate, each cited and ``as_of``-stamped."""
        ...

    def get_relationships(self, entity: str, link_type: Optional[str] = None) -> dict:
        """An entity's links in both directions (owns/member_of/dotted_line_to/mentions/
        reports_to), optionally filtered to one ``link_type``."""
        ...

    def list_metrics(self) -> list[dict]:
        """The queryable metric vocabulary (canonical key + display name + aliases)."""
        ...

    def get_claims_by_predicate(self, predicate: str) -> dict:
        """Every claim whose canonicalized predicate matches, across all subjects."""
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
             "as_of": "2025-04-15", "title": "Q1 Board Deck", "author": None},
            {"source_uri": "data/dashboards/metrics.html", "source_type": "html",
             "as_of": "2025-05-02", "title": "Metrics Dashboard", "author": None},
        ]

    def search(self, query: str, k: int = 10) -> list[dict]:
        # Same key shape as HelixQueryEngine.search (id/title/url/snippet/score/
        # source_as_of/document_id) so the mock never masks a production shape drift.
        return [
            {"id": "11", "title": "data/financials/q1_board_deck.pdf",
             "url": "data/financials/q1_board_deck.pdf", "document_id": 1, "score": 0.91,
             "source_as_of": "2025-04-15",
             "snippet": f"... Q1 revenue: $4.2M ... (matched: {query})"},
            {"id": "22", "title": "data/dashboards/metrics.html",
             "url": "data/dashboards/metrics.html", "document_id": 2, "score": 0.78,
             "source_as_of": "2025-05-02",
             "snippet": f"... Q1 revenue: $3.9M ... (matched: {query})"},
        ][:k]

    def fetch(self, id: str) -> dict:
        body = {  # id -> (source_uri, text, source_as_of, document_id)
            "11": ("data/financials/q1_board_deck.pdf", "Q1 revenue: $4.2M", "2025-04-15", 1),
            "22": ("data/dashboards/metrics.html", "Q1 revenue: $3.9M", "2025-05-02", 2),
        }
        if id not in body:
            return {"id": id, "title": "", "text": "", "url": "",
                    "metadata": {"source_as_of": None, "document_id": None,
                                 "ordinal": None, "found": False}}
        uri, text, as_of, doc_id = body[id]
        return {"id": id, "title": uri, "text": text, "url": uri,
                "metadata": {"source_as_of": as_of, "document_id": doc_id,
                             "ordinal": 0, "found": True}}

    def list_entities(self, entity_type: Optional[str] = None) -> list[dict]:
        rows = [
            {"id": 5, "canonical_name": "HelixPay", "entity_type": "other", "seeded": True},
            {"id": 6, "canonical_name": "HelixPay Brasil", "entity_type": "other", "seeded": True},
            {"id": 1, "canonical_name": "Maria Santos", "entity_type": "person", "seeded": True},
        ]
        return [r for r in rows if entity_type is None or r["entity_type"] == entity_type]

    # --- optional graph/temporal surfaces (ExposureEngine extension, SP_023) - #
    # Same key shapes as HelixQueryEngine's, so the mock never masks a production shape drift.
    def _canonical(self, predicate: str) -> str:
        """Canonicalize against the canned vocab (so the mock honours its ``predicate``
        argument rather than hardcoding 'revenue' — review H2)."""
        p = predicate.strip().lower()
        for m in self.list_metrics():
            if p == m["canonical_key"].lower() or p in [a.lower() for a in m["aliases"]]:
                return m["canonical_key"]
        return predicate

    def get_timeline(self, entity: str, predicate: str) -> dict:
        # Two coexisting conflicting Q1-revenue values — the planted contradiction, visible as
        # a temporal history (neither collapsed away). Only the 'revenue' predicate has canned
        # history; any other canonical predicate yields an empty (but resolved) timeline.
        target = self._canonical(predicate)
        if target != "revenue":
            return {"entity": "HelixPay", "entity_id": 5, "predicate": target,
                    "resolved": True, "timeline": []}
        return {
            "entity": "HelixPay",
            "entity_id": 5,
            "predicate": "revenue",
            "resolved": True,
            "timeline": [
                {"claim_id": 101, "predicate": "revenue", "value": "$4.2M",
                 "as_of": "2025-03-31", "valid_from": None, "valid_to": None,
                 "superseded_by": None, "confidence": 0.7,
                 "source_uri": "data/financials/q1_board_deck.pdf",
                 "source_as_of": "2025-04-15", "snippet": "Q1 revenue: $4.2M"},
                {"claim_id": 102, "predicate": "revenue", "value": "$3.9M",
                 "as_of": "2025-03-31", "valid_from": None, "valid_to": None,
                 "superseded_by": None, "confidence": 0.6,
                 "source_uri": "data/dashboards/metrics.html",
                 "source_as_of": "2025-05-02", "snippet": "Q1 revenue: $3.9M"},
            ],
        }

    def get_relationships(self, entity: str, link_type: Optional[str] = None) -> dict:
        rels = [
            {"link_id": 1, "link_type": "reports_to", "direction": "outgoing",
             "from_entity_id": 1, "from_name": "Maria Santos",
             "to_entity_id": 9, "to_name": "Tan Wei",
             "as_of": "2025-03-01", "valid_to": None,
             "source_uri": "data/org-chart.md", "source_as_of": "2025-03-01",
             "snippet": "Maria Santos reports to Tan Wei"},
            {"link_id": 2, "link_type": "owns", "direction": "incoming",
             "from_entity_id": 9, "from_name": "Tan Wei",
             "to_entity_id": 1, "to_name": "Maria Santos",
             "as_of": None, "valid_to": None,
             "source_uri": None, "source_as_of": None, "snippet": None},
        ]
        if link_type is not None:
            rels = [r for r in rels if r["link_type"] == link_type]
        return {"entity": "Maria Santos", "entity_id": 1, "resolved": True,
                "relationships": rels}

    def list_metrics(self) -> list[dict]:
        return [
            {"canonical_key": "revenue", "display_name": "Revenue",
             "aliases": ["arr", "annual recurring revenue"]},
            {"canonical_key": "runway", "display_name": "Runway (months)", "aliases": []},
        ]

    def get_claims_by_predicate(self, predicate: str) -> dict:
        target = self._canonical(predicate)  # honour the input (review H2)
        if target != "revenue":
            return {"predicate": target, "count": 0, "claims": []}
        claims = [
            {"claim_id": 101, "subject_entity_id": 5, "subject_name": "HelixPay",
             "value": "$4.2M", "as_of": "2025-03-31", "valid_to": None,
             "superseded_by": None, "confidence": 0.7,
             "source_uri": "data/financials/q1_board_deck.pdf",
             "source_as_of": "2025-04-15"},
            {"claim_id": 102, "subject_entity_id": 5, "subject_name": "HelixPay",
             "value": "$3.9M", "as_of": "2025-03-31", "valid_to": None,
             "superseded_by": None, "confidence": 0.6,
             "source_uri": "data/dashboards/metrics.html",
             "source_as_of": "2025-05-02"},
        ]
        return {"predicate": target, "count": len(claims), "claims": claims}


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
