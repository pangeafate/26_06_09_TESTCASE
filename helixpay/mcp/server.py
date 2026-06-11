"""The HelixPay MCP server — **streamable-HTTP** transport (hard requirement).

stdio is local-only and would break the live-URL story (the consumer is an agent), so
this server is built for streamable-HTTP and mounted into the shared ASGI app at ``/mcp``
(see ``helixpay.api.app``). Every tool is a **thin pass-through** to the active
``QueryEngine`` (``helixpay.api.engine.get_engine``) — no business logic, no DB access.

Tools, typed per object type:
  ask · get_entity · get_org_chart · find_contradictions
  get_sources · search · fetch · list_entities
  get_timeline · get_relationships · list_metrics · get_claims_by_predicate

The four core tools are guaranteed by the frozen ``QueryEngine`` Protocol. The other eight —
the SP_022 retrieval primitives (``get_sources``/``search``/``fetch``/``list_entities``) and
the SP_023 graph/temporal reads (``get_timeline``/``get_relationships``/``list_metrics``/
``get_claims_by_predicate``) — are optional surfaces (``ExposureEngine`` extension); they
dispatch through ``_retrieval`` and degrade to a structured "unavailable" payload if the
injected engine does not implement them.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from helixpay.api._dates import parse_as_of
from helixpay.api.engine import get_engine


def _csv_env(name: str) -> list[str]:
    return [v.strip() for v in os.environ.get(name, "").split(",") if v.strip()]


def _transport_security() -> TransportSecuritySettings:
    """DNS-rebinding protection config. The service binds 127.0.0.1 behind a terminating
    proxy, so protection is off by default. Set ``HELIXPAY_MCP_ALLOWED_HOSTS`` (comma-
    separated) to harden the Host check; ``HELIXPAY_MCP_ALLOWED_ORIGINS`` independently
    restricts the Origin header. We never wildcard the origin — a wildcard would defeat
    much of the rebinding protection it is meant to provide."""
    hosts = _csv_env("HELIXPAY_MCP_ALLOWED_HOSTS")
    if not hosts:
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=_csv_env("HELIXPAY_MCP_ALLOWED_ORIGINS"),
    )


def _retrieval(method: str, *args: Any, **kwargs: Any) -> dict:
    """Guarded dispatch for the optional retrieval surfaces. Keeps the extra tools callable
    against any engine without breaking when the Protocol-only surface is wired. ``results``
    carries whatever the surface returns: a *list* for ``search`` / ``get_sources`` /
    ``list_entities`` (a scan), or a single *record dict* for ``fetch`` (a by-id lookup).
    The degraded ("unavailable") payload always uses ``results: []``."""
    engine = get_engine()
    fn = getattr(engine, method, None)
    if not callable(fn):
        return {
            "available": False,
            "reason": f"the active query engine does not implement '{method}'",
            "results": [],
        }
    return {"available": True, "results": fn(*args, **kwargs)}


def build_mcp(name: str = "helixpay") -> FastMCP:
    """Construct the FastMCP server with all twelve tools registered. Returned so the ASGI
    app can mount ``.streamable_http_app()`` and tests can introspect tools directly."""
    mcp = FastMCP(
        name,
        instructions=(
            "HelixPay ontology query surface. Answers are grounded with cited, "
            "as_of-stamped sources; contradictions are surfaced, never hidden."
        ),
        stateless_http=True,
        streamable_http_path="/",
        transport_security=_transport_security(),
    )

    @mcp.tool()
    def ask(question: str) -> dict:
        """Answer a deep question grounded strictly in retrieved material — every claim
        cited (with as_of) and any contradiction surfaced."""
        return get_engine().ask(question).model_dump(mode="json")

    @mcp.tool()
    def get_entity(name: str) -> dict:
        """Resolve an entity and return it with its aliases, claims and links."""
        return dict(get_engine().get_entity(name))

    @mcp.tool()
    def get_org_chart(as_of: Optional[str] = None) -> dict:
        """The org hierarchy as of an ISO date (freshest if omitted). A malformed
        ``as_of`` raises a clear error (surfaced by the SDK as a tool error)."""
        return dict(get_engine().get_org_chart(parse_as_of(as_of)))

    @mcp.tool()
    def find_contradictions(topic: Optional[str] = None) -> list[dict]:
        """List first-class contradictions, optionally filtered to a topic."""
        return [c.model_dump(mode="json") for c in get_engine().find_contradictions(topic)]

    @mcp.tool()
    def get_sources() -> dict:
        """List the documents/sources backing the ontology, each with its as_of."""
        return _retrieval("get_sources")

    @mcp.tool()
    def search(query: str, k: int = 10) -> dict:
        """Raw hybrid retrieval over chunks (no synthesis). Each hit carries id/title/url/
        snippet/score and the source document's ``source_as_of``. Pair an id with ``fetch``
        for the full text."""
        return _retrieval("search", query, k=k)

    @mcp.tool()
    def fetch(id: str) -> dict:
        """Fetch the full text + provenance of a single chunk by id (an id from ``search``).
        An unknown/malformed id returns a ``found: false`` record, never an error."""
        return _retrieval("fetch", id)

    @mcp.tool()
    def list_entities(entity_type: Optional[str] = None) -> dict:
        """Enumerate ontology entities, optionally by type (person/team/customer/product/
        metric/other). Use for corpus-wide 'what X are covered' questions — e.g.
        ``entity_type='other'`` lists regions/org-units (HelixPay Brasil, SEA, …)."""
        return _retrieval("list_entities", entity_type)

    @mcp.tool()
    def get_timeline(entity: str, predicate: str) -> dict:
        """The chronological history of a fact: every claim for ``entity``'s ``predicate`` in
        time order, with the supersession chain (``superseded_by``/``valid_to``) and any
        coexisting conflicting values, each cited + ``as_of``-stamped. The ontology versions
        facts (never overwrites) — this surfaces that. An ambiguous/unknown entity →
        ``resolved: false``."""
        return _retrieval("get_timeline", entity, predicate)

    @mcp.tool()
    def get_relationships(entity: str, link_type: Optional[str] = None) -> dict:
        """An entity's relationships in BOTH directions, beyond the org chart: outgoing +
        incoming ``owns``/``member_of``/``dotted_line_to``/``mentions``/``reports_to``
        (optionally filtered to one ``link_type``). Answers 'who owns X', 'who is on team Z',
        'who is connected to W'. Each edge carries resolved endpoint names + provenance."""
        return _retrieval("get_relationships", entity, link_type)

    @mcp.tool()
    def list_metrics() -> dict:
        """List the queryable metric vocabulary (canonical key + display name + aliases) — so
        you can discover which predicates to ask about (e.g. for ``get_claims_by_predicate``
        or ``get_timeline``)."""
        return _retrieval("list_metrics")

    @mcp.tool()
    def get_claims_by_predicate(predicate: str) -> dict:
        """Every claim for one ``predicate`` across ALL subjects — for 'compare revenue across
        regions/quarters'. Canonicalizes the predicate (so 'ARR'/'annual recurring revenue'
        land together) and surfaces conflicting/superseded values without collapsing them."""
        return _retrieval("get_claims_by_predicate", predicate)

    return mcp


__all__ = ["build_mcp"]
