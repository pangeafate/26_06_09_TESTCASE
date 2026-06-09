"""HelixPay Ontology package.

A temporal, provenance-carrying ontology built over a messy multi-format company
snapshot, exposed as a library (and thin CLI/HTTP/MCP adapters) so an AI agent can
answer deep, cross-cutting questions with source attribution.

Layering (dependencies flow inward):
    capabilities (ingest, query, mcp, api)  ->  shared logic (contracts)  ->  models
    infrastructure (db) stands alone behind the Repository seam.

Cross-module types live ONLY in ``helixpay.contracts`` and are never redefined
elsewhere. All raw SQL is confined to ``helixpay.db``.
"""

__version__ = "0.1.0"
