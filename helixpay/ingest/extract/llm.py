"""The LLM seam for extraction: an injectable ``LLMClient`` and the structured-output
``call_structured`` loop (CLAUDE.md §7: named prompt + structured-output schema +
validate-and-repair-or-drop; no free-form trust).

The real Anthropic client (``claude-sonnet-4-6``) is built lazily, so the unit suite runs
with neither the ``anthropic`` package installed nor ``ANTHROPIC_API_KEY`` set — tests
inject a stub ``LLMClient``. Every call logs its prompt name and validate/repair outcome
(spec §8 observability) without logging secrets or raw chunk bodies.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, ValidationError

from helixpay.config import EXTRACTION_MODEL, load_config

log = logging.getLogger("helixpay.ingest.extract.llm")

T = TypeVar("T", bound=BaseModel)

_MAX_TOKENS = 4096
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


@runtime_checkable
class LLMClient(Protocol):
    """The slice of an LLM we depend on. Returns the model's text for one turn."""

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
        resp = self.client.messages.create(  # type: ignore[attr-defined]
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        parts = [block.text for block in resp.content if getattr(block, "type", None) == "text"]
        return "".join(parts)


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


def call_structured(
    client: LLMClient,
    *,
    prompt_name: str,
    system: str,
    user: str,
    schema: type[T],
    repair: bool = True,
    max_tokens: int = _MAX_TOKENS,
) -> Optional[T]:
    """Call the LLM and validate its output against ``schema``. On failure, make exactly
    one repair attempt that feeds the validation error back; if that still fails, drop the
    result (returns ``None``) and log it. Never returns unvalidated output.
    """
    raw = client.generate(system=system, user=user, max_tokens=max_tokens)
    parsed, error = _try_parse(raw, schema)
    if parsed is not None:
        log.info("llm structured-output ok", extra={"prompt": prompt_name, "outcome": "ok"})
        return parsed

    if not repair:
        log.warning(
            "llm structured-output dropped (no repair)",
            extra={"prompt": prompt_name, "outcome": "drop", "error": error},
        )
        return None

    log.info("llm structured-output repair", extra={"prompt": prompt_name, "outcome": "repair", "error": error})
    repaired_raw = client.generate(system=system, user=_repair_user(user, raw, error or ""), max_tokens=max_tokens)
    parsed, error2 = _try_parse(repaired_raw, schema)
    if parsed is not None:
        log.info("llm structured-output ok after repair", extra={"prompt": prompt_name, "outcome": "repaired"})
        return parsed

    log.warning(
        "llm structured-output dropped after repair",
        extra={"prompt": prompt_name, "outcome": "drop", "error": error2},
    )
    return None


__all__ = ["LLMClient", "AnthropicClient", "call_structured"]
