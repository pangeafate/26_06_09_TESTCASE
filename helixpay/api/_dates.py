"""Shared input parsing for the exposure adapters (REST + MCP).

``as_of`` arrives as a string on the wire; both surfaces parse it identically, so the
logic lives here once. A bad value raises ``ValueError`` with an actionable message —
the REST layer maps that to a 422 and the MCP SDK surfaces it as a tool error, rather
than letting a raw ``ValueError`` become an opaque 500.
"""

from __future__ import annotations

from datetime import date
from typing import Optional


def parse_as_of(value: Optional[str]) -> Optional[date]:
    """Parse an optional ISO date. ``None``/empty → ``None``; invalid → ``ValueError``."""
    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"as_of must be an ISO date (YYYY-MM-DD); got {value!r}"
        ) from exc


__all__ = ["parse_as_of"]
