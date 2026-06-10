"""Temporal resolution — freshest-wins, staleness flagging, as_of coverage.

The ontology never collapses conflicting facts, but a *question* usually wants
the current value. This module orders claims by ``as_of`` (freshest first) and
summarises the date span of the evidence an answer cited so the answer layer can
say "as of <date>" and flag when it is leaning on the dated roster snapshot.

``ROSTER_AS_OF`` mirrors ``helixpay.seed.roster.ORG_CHART_AS_OF`` (the
org-chart export date). We keep a local copy rather than import the seed package
so the query layer stays free of build-time data modules; the value is asserted
equal in tests.
"""

from __future__ import annotations

from datetime import date

from helixpay.contracts import Citation, Claim

# Org-chart roster export date (mirror of seed.roster.ORG_CHART_AS_OF). Evidence
# no newer than this is flagged "stale" — a later document that disagrees should
# win, and the answer should say the roster may be out of date (brief step 3).
ROSTER_AS_OF = date(2026, 4, 15)

_OLDEST = date.min


def order_by_freshness(claims: list[Claim]) -> list[Claim]:
    """Return claims freshest-first. Undated (``as_of is None``) claims sort as
    the oldest (never crash comparing ``None`` to ``date`` — review code-M3).
    Stable tie-break on claim id keeps ordering deterministic."""
    return sorted(
        claims,
        key=lambda c: (c.as_of or _OLDEST, -(c.id or 0)),
        reverse=True,
    )


def freshest_per_predicate(claims: list[Claim]) -> dict[str, Claim]:
    """Map each predicate to its freshest claim (latest ``as_of`` wins)."""
    out: dict[str, Claim] = {}
    for claim in order_by_freshness(claims):
        out.setdefault(claim.predicate, claim)
    return out


def as_of_coverage(
    citations: list[Citation], roster_as_of: date = ROSTER_AS_OF
) -> dict:
    """Summarise the temporal span of cited evidence.

    Returns the pinned shape (review arch-M3/code-M1):
        {"earliest": iso|None, "latest": iso|None,
         "sources": {source_uri: iso}, "stale": bool}
    ``stale`` is True when the freshest cited evidence is no newer than the
    roster snapshot — the signal that the answer may be leaning on dated data.
    """
    dated = [(c.source_uri, c.as_of) for c in citations if c.as_of is not None]
    if not dated:
        return {"earliest": None, "latest": None, "sources": {}, "stale": False}
    earliest = min(d for _, d in dated)
    latest = max(d for _, d in dated)
    source_dates: dict[str, date] = {}
    for uri, d in dated:
        # keep the freshest date seen per source (compare dates, not strings)
        prev = source_dates.get(uri)
        if prev is None or d > prev:
            source_dates[uri] = d
    return {
        "earliest": earliest.isoformat(),
        "latest": latest.isoformat(),
        "sources": {uri: d.isoformat() for uri, d in source_dates.items()},
        # strictly older than the roster snapshot → we have nothing as fresh as
        # the current roster, so flag the answer as possibly stale. Evidence on or
        # after the roster date is treated as current.
        "stale": latest < roster_as_of,
    }


__all__ = ["ROSTER_AS_OF", "order_by_freshness", "freshest_per_predicate", "as_of_coverage"]
