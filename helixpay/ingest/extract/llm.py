"""The LLM seam for extraction: an injectable ``LLMClient`` and the structured-output
``call_structured`` loop (CLAUDE.md §7: named prompt + structured-output schema +
validate-and-repair-or-drop; no free-form trust).

The real Anthropic client (``claude-sonnet-4-6``) is built lazily, so the unit suite runs
with neither the ``anthropic`` package installed nor ``ANTHROPIC_API_KEY`` set — tests
inject a stub ``LLMClient``. Every call logs its prompt name and validate/repair outcome
(spec §8 observability) without logging secrets or raw chunk bodies.

SP_014 changes:
- Raised ``_MAX_TOKENS`` 4096 → 8192 (covers dense chunks without truncation).
- Added ``GenerationResult`` dataclass carrying ``text`` and ``stop_reason``.
- Added optional ``generate_with_meta`` duck-typing seam on clients; ``AnthropicClient``
  implements it. The original ``LLMClient`` Protocol (``generate → str``) is unchanged
  so existing test stubs keep working.
- ``call_structured`` now returns ``StructuredResult[T]`` with ``.value`` and
  ``.truncated`` instead of bare ``Optional[T]``. ``.truncated`` is True when any LLM
  call in the attempt had ``stop_reason == "max_tokens"``.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Generic, Optional, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, ValidationError

from helixpay.config import EXTRACTION_MODEL, load_config

log = logging.getLogger("helixpay.ingest.extract.llm")

T = TypeVar("T", bound=BaseModel)

_MAX_TOKENS = 16384  # SP_014: 4096→8192; SP_026: 8192→16384 — the sales-pipeline dashboard
# emits one claim per deal attribute (~12 deals × 5–6 attrs ≈ 65 claims), whose JSON
# overran 8192 → stop_reason=max_tokens → undecodable → the whole extraction was dropped
# (0 claims). claude-sonnet-4-6 supports far larger output; we only pay for tokens actually
# generated, so the higher ceiling costs nothing on the common (small) chunk.
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


# ─────────────────────────────────────────────────────────────────────────────
# Public data types
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class GenerationResult:
    """One LLM generation turn: the text output and the stop reason if available."""

    text: str
    stop_reason: Optional[str] = None


@dataclass(frozen=True)
class StructuredResult(Generic[T]):
    """The outcome of ``call_structured``.

    ``value``     The validated schema instance, or ``None`` if the model output was
                  undecodable even after one repair attempt.
    ``truncated`` True if any generation call in this attempt had
                  ``stop_reason == "max_tokens"``.  Callers (e.g. ``ChunkExtractor``)
                  use this to count/log the event — the actual response handling
                  (count, surface, optionally recover) lives in the extractor.
    """

    value: Optional[T]
    truncated: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# Client protocols
# ─────────────────────────────────────────────────────────────────────────────

@runtime_checkable
class LLMClient(Protocol):
    """The slice of an LLM we depend on. Returns the model's text for one turn.

    This interface is UNCHANGED from pre-SP_014; existing test stubs that implement
    only ``generate(...)`` continue to work.
    """

    def generate(self, *, system: str, user: str, max_tokens: int) -> str: ...


class AnthropicClient:
    """Real ``LLMClient`` over the Anthropic Messages API (lazy import)."""

    def __init__(self, client: object | None = None, *, model: str = EXTRACTION_MODEL) -> None:
        self._client = client
        self.model = model

    @property
    def client(self) -> object:
        if self._client is None:
            import importlib  # noqa: PLC0415

            anthropic = importlib.import_module("anthropic")  # lazy (External-Tool-Isolation)
            self._client = anthropic.Anthropic(api_key=load_config().anthropic_api_key)
        return self._client

    def generate(self, *, system: str, user: str, max_tokens: int) -> str:
        result = self.generate_with_meta(system=system, user=user, max_tokens=max_tokens)
        return result.text

    def generate_with_meta(self, *, system: str, user: str, max_tokens: int) -> GenerationResult:
        """Extended seam that surfaces the stop_reason alongside the text."""
        resp = self.client.messages.create(  # type: ignore[attr-defined]
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        parts = [block.text for block in resp.content if getattr(block, "type", None) == "text"]
        return GenerationResult(
            text="".join(parts),
            stop_reason=getattr(resp, "stop_reason", None),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _extract_json_object(text: str) -> str:
    """Pull a JSON object out of a model response that may be fenced or prose-wrapped."""
    fenced = _FENCE_RE.search(text)
    if fenced:
        return fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text.strip()


def _try_parse(text: str, schema: type[T]) -> tuple[Optional[T], Optional[str]]:
    """Return (model, None) on success, (None, error_message) on failure."""
    try:
        payload = json.loads(_extract_json_object(text))
    except (json.JSONDecodeError, ValueError) as exc:
        return None, f"not valid JSON: {exc}"
    try:
        return schema.model_validate(payload), None
    except ValidationError as exc:
        return None, f"schema validation failed: {exc.error_count()} error(s)"


def _repair_user(original_user: str, bad_output: str, error: str) -> str:
    """Build the repair turn: echo the failure back so the model corrects it."""
    snippet = bad_output if len(bad_output) <= 1500 else bad_output[:1500] + "…"
    return (
        f"{original_user}\n\n---\nYour previous reply did not parse as the required JSON "
        f"({error}). Reply again with the corrected response: a SINGLE valid JSON object "
        f"matching the schema exactly, no prose, no code fences.\nPrevious reply was:\n{snippet}"
    )


def _generate(client: LLMClient, *, system: str, user: str, max_tokens: int) -> GenerationResult:
    """Unified generation helper: use generate_with_meta if available, else wrap generate.

    This is the single dispatch point so all callers get a GenerationResult regardless
    of which client is injected.  The parameter type is ``LLMClient`` (the Protocol)
    so that mypy knows ``.generate`` is valid; duck-typed clients with
    ``generate_with_meta`` are detected at runtime via ``hasattr``.
    """
    if hasattr(client, "generate_with_meta"):
        # cast to Any to satisfy mypy — the hasattr guard ensures the method exists
        import typing  # noqa: PLC0415
        meta_client = typing.cast(typing.Any, client)
        return meta_client.generate_with_meta(system=system, user=user, max_tokens=max_tokens)
    # Fall back to the LLMClient protocol (generate → str)
    text = client.generate(system=system, user=user, max_tokens=max_tokens)
    return GenerationResult(text=text, stop_reason=None)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def call_structured(
    client: LLMClient,
    *,
    prompt_name: str,
    system: str,
    user: str,
    schema: type[T],
    repair: bool = True,
    max_tokens: int = _MAX_TOKENS,
) -> StructuredResult[T]:
    """Call the LLM and validate its output against ``schema``. On failure, make exactly
    one repair attempt that feeds the validation error back; if that still fails, drop the
    result (returns ``StructuredResult(value=None)``) and log it.  Never returns
    unvalidated output.

    Returns a ``StructuredResult[T]`` whose ``.truncated`` flag is True if any generation
    call in this attempt had ``stop_reason == "max_tokens"``.
    """
    any_truncated = False

    result = _generate(client, system=system, user=user, max_tokens=max_tokens)
    if result.stop_reason == "max_tokens":
        any_truncated = True
    raw = result.text

    parsed, error = _try_parse(raw, schema)
    if parsed is not None:
        log.info("llm structured-output ok", extra={"prompt": prompt_name, "outcome": "ok"})
        return StructuredResult(value=parsed, truncated=any_truncated)

    if not repair:
        log.warning(
            "llm structured-output dropped (no repair)",
            extra={"prompt": prompt_name, "outcome": "drop", "error": error},
        )
        return StructuredResult(value=None, truncated=any_truncated)

    log.info("llm structured-output repair", extra={"prompt": prompt_name, "outcome": "repair", "error": error})
    repair_result = _generate(
        client, system=system, user=_repair_user(user, raw, error or ""), max_tokens=max_tokens
    )
    if repair_result.stop_reason == "max_tokens":
        any_truncated = True
    repaired_raw = repair_result.text

    parsed, error2 = _try_parse(repaired_raw, schema)
    if parsed is not None:
        log.info("llm structured-output ok after repair", extra={"prompt": prompt_name, "outcome": "repaired"})
        return StructuredResult(value=parsed, truncated=any_truncated)

    log.warning(
        "llm structured-output dropped after repair",
        extra={"prompt": prompt_name, "outcome": "drop", "error": error2},
    )
    return StructuredResult(value=None, truncated=any_truncated)


__all__ = [
    "LLMClient",
    "AnthropicClient",
    "GenerationResult",
    "StructuredResult",
    "call_structured",
]
