"""External-model seams: query embedding + answer synthesis.

Two narrow Protocols so the engine never hard-depends on a vendor SDK and the
unit suite can inject fakes (CLAUDE.md §14 — isolate the high-noise external
tool boundary):

* ``Embedder.embed_query(text) -> list[float]`` (1024-d, ``voyage-3``).
* ``Synthesizer.synthesize(prompt, *, schema) -> dict`` (``claude-opus-4-8``,
  structured output validated against ``schema``).

The concrete impls read keys **only inside their methods** and ``import
anthropic``/``voyageai`` lazily, so importing ``helixpay.query`` needs neither
the keys nor the SDKs (review code-C1/L3). Secrets come from ``helixpay.config``
(env only); never logged.
"""

from __future__ import annotations

import json
from typing import Optional, Protocol, runtime_checkable

from helixpay.config import EMBEDDING_DIM, EMBEDDING_MODEL, SYNTHESIS_MODEL, load_config


@runtime_checkable
class Embedder(Protocol):
    def embed_query(self, text: str) -> list[float]: ...


@runtime_checkable
class Synthesizer(Protocol):
    def synthesize(self, prompt: str, *, schema: dict) -> dict: ...


class VoyageEmbedder:
    """Voyage query embeddings. Lazy client + lazy key (no import-time cost)."""

    def __init__(self, api_key: Optional[str] = None, model: str = EMBEDDING_MODEL) -> None:
        self._api_key = api_key
        self._model = model
        self._client = None

    def _ensure(self):  # pragma: no cover - exercised only with a real key
        if self._client is None:
            import importlib

            voyageai = importlib.import_module("voyageai")  # lazy: not a hard dep of import
            key = self._api_key or load_config().voyage_api_key
            self._client = voyageai.Client(api_key=key)
        return self._client

    def embed_query(self, text: str) -> list[float]:  # pragma: no cover - needs key
        client = self._ensure()
        result = client.embed([text], model=self._model, input_type="query")
        vec = list(result.embeddings[0])
        if len(vec) != EMBEDDING_DIM:
            raise ValueError(f"embedding dim {len(vec)} != expected {EMBEDDING_DIM}")
        return vec


class AnthropicSynthesizer:
    """Opus synthesis via a forced structured-output tool call."""

    def __init__(self, api_key: Optional[str] = None, model: str = SYNTHESIS_MODEL) -> None:
        self._api_key = api_key
        self._model = model
        self._client = None

    def _ensure(self):  # pragma: no cover - exercised only with a real key
        if self._client is None:
            import importlib

            anthropic = importlib.import_module("anthropic")  # lazy: not a hard dep of import
            key = self._api_key or load_config().anthropic_api_key
            self._client = anthropic.Anthropic(api_key=key)
        return self._client

    def synthesize(self, prompt: str, *, schema: dict) -> dict:  # pragma: no cover - needs key
        client = self._ensure()
        tool = {"name": "emit_answer", "description": "Return the grounded answer.", "input_schema": schema}
        msg = client.messages.create(
            model=self._model,
            max_tokens=1500,
            tools=[tool],
            tool_choice={"type": "tool", "name": "emit_answer"},
            messages=[{"role": "user", "content": prompt}],
        )
        for block in msg.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "emit_answer":
                data = block.input
                if isinstance(data, dict):
                    return data
                try:
                    parsed = json.loads(data)
                except (TypeError, ValueError):
                    return {"sentences": []}
                return parsed if isinstance(parsed, dict) else {"sentences": []}
        return {"sentences": []}  # model emitted no tool call → safe empty


__all__ = ["Embedder", "Synthesizer", "VoyageEmbedder", "AnthropicSynthesizer"]
