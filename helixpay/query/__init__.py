"""HelixPay query brain — the ``QueryEngine`` implementation (spec §5, Agent 3).

Public surface: the concrete engine and a default-construction factory, exposed
lazily (PEP 562) so importing a leaf module (``helixpay.query.retrieval`` etc.)
does not drag in the engine or its optional SDK deps. The injected seams
(``Embedder``/``Synthesizer``) live in ``helixpay.query.clients`` and are
imported from there only by application startup and tests (review L1 — keep
Agent 4's import surface to the engine, not the seams).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from helixpay.query.engine import HelixQueryEngine, build_default_engine

__all__ = ["HelixQueryEngine", "build_default_engine"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from helixpay.query import engine

        return getattr(engine, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
