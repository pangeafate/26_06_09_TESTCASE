"""The shared ASGI app — one uvicorn target serves REST **and** the MCP server.

Frozen gate entrypoint (Agent 5 wires this): ``helixpay.api.app:app``. It serves the
REST surface plus the streamable-HTTP MCP server mounted at ``/mcp`` on a single port
(``127.0.0.1:8000`` behind the proxy).

The adapters are thin: each route is a pass-through to the active ``QueryEngine``
(``helixpay.api.engine``). ``GET /health`` is dependency-free — it never touches the
engine or ``load_config()``, so it is safe as a compose healthcheck without LLM keys.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from helixpay.contracts import AnswerBundle, Contradiction
from helixpay.api._dates import parse_as_of
from helixpay.api.engine import get_engine
from helixpay.mcp.server import build_mcp


class AskRequest(BaseModel):
    question: str


def create_app() -> FastAPI:
    """Build a fresh ASGI app with its own MCP server mounted at ``/mcp``.

    A factory (not a module singleton) because the streamable-HTTP session manager is
    **single-use** — its ``run()`` lifecycle may be entered only once per instance. Each
    app therefore owns a fresh ``build_mcp()``; production enters its lifespan once at
    startup, and each test gets an independent instance.

    Routes are thin pass-throughs to the active ``QueryEngine`` (``get_engine``), so the
    mock↔real swap is a ``set_engine`` call, never an adapter change.
    """
    mcp = build_mcp()
    mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # The streamable-HTTP session manager must run for the lifetime of the app.
        async with mcp.session_manager.run():
            yield

    app = FastAPI(
        title="HelixPay Ontology API",
        summary="Thin REST + MCP surface over the QueryEngine. Cited, time-aware, "
        "contradiction-surfacing answers.",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Mount the streamable-HTTP MCP server. Endpoint: POST /mcp/ (the agent-facing surface).
    app.mount("/mcp", mcp_app)

    @app.get("/health")
    def health() -> dict:
        """Liveness — green without any secret/LLM key, so compose can probe it."""
        return {"status": "ok"}

    @app.post("/ask", response_model=AnswerBundle)
    def ask(body: AskRequest) -> AnswerBundle:
        """Answer grounded strictly in retrieved material; ``contradictions`` is always
        present (possibly empty), never hidden."""
        return get_engine().ask(body.question)

    @app.get("/entity/{name}")
    def get_entity(name: str) -> dict:
        """Entity plus its aliases, claims and links."""
        return dict(get_engine().get_entity(name))

    @app.get("/org-chart")
    def org_chart(as_of: Optional[str] = None) -> dict:
        """Org hierarchy as of an ISO date (freshest if omitted). A malformed ``as_of``
        is a client error (422), not an opaque 500."""
        try:
            parsed = parse_as_of(as_of)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return dict(get_engine().get_org_chart(parsed))

    @app.get("/contradictions", response_model=list[Contradiction])
    def contradictions(topic: Optional[str] = None) -> list[Contradiction]:
        """First-class contradiction rows, optionally filtered to a topic."""
        return get_engine().find_contradictions(topic)

    return app


# The frozen gate entrypoint Agent 5 runs: `uvicorn helixpay.api.app:app`.
app = create_app()


__all__ = ["app", "create_app"]
