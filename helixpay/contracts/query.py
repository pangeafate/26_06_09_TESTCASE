"""QueryEngine contract (spec §4) — the reasoning surface.

Agent 3 implements this over the ``Repository``; Agent 4 (exposure) builds the
library/CLI/HTTP/MCP adapters against this Protocol (mocking it until Agent 3
lands). ``ask`` returns a grounded ``AnswerBundle`` in which every claim is cited
and contradictions are surfaced, never hidden.
"""

from __future__ import annotations

from datetime import date
from typing import Optional, Protocol, runtime_checkable

from .models import AnswerBundle, Contradiction, EntityDetail, OrgNode


@runtime_checkable
class QueryEngine(Protocol):
    def ask(self, question: str) -> AnswerBundle:
        """Answer a deep question grounded strictly in retrieved material, with
        every claim cited and any contradiction surfaced."""
        ...

    def get_entity(self, name: str) -> EntityDetail:
        """Entity plus its aliases and claims."""
        ...

    def get_org_chart(self, as_of: Optional[date] = None) -> OrgNode:
        """The org hierarchy as of a date (freshest if omitted)."""
        ...

    def find_contradictions(self, topic: Optional[str] = None) -> list[Contradiction]:
        ...


__all__ = ["QueryEngine"]
