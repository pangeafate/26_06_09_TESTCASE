"""The LLM seam: structured output with a one-shot validate-and-repair-or-drop loop."""

from __future__ import annotations

import logging

from helixpay.ingest.extract.llm import GenerationResult, StructuredResult, call_structured
from helixpay.ingest.extract.schemas import ExtractionOut

_GOOD = '{"claims": [{"subject": "HelixPay", "predicate": "ARR", "object_value": "SGD 14.2M"}], "relations": []}'
_FENCED = "Here you go:\n```json\n" + _GOOD + "\n```\n"
_BAD = "sorry, I cannot produce JSON"


# ─────────────────────────────────────────────────────────────────────────────
# Stub implementations
# ─────────────────────────────────────────────────────────────────────────────

class StubLLM:
    """Returns scripted responses in order; records each (system, user) call.

    Implements only the LLMClient protocol (generate → str).
    Existing tests rely on this class; do not remove generate().
    """

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def generate(self, *, system: str, user: str, max_tokens: int) -> str:
        self.calls.append((system, user))
        return self._responses.pop(0)


class StubLLMWithMeta:
    """A stub that implements generate_with_meta → GenerationResult.

    Used to verify the optional richer seam (stop_reason propagation).
    """

    def __init__(self, responses: list[GenerationResult]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def generate_with_meta(self, *, system: str, user: str, max_tokens: int) -> GenerationResult:
        self.calls.append((system, user))
        return self._responses.pop(0)


# ─────────────────────────────────────────────────────────────────────────────
# Existing tests — adapted to read .value (semantics preserved)
# ─────────────────────────────────────────────────────────────────────────────

def test_valid_json_parses_in_one_call():
    llm = StubLLM([_GOOD])
    out = call_structured(llm, prompt_name="extract_claims", system="s", user="u", schema=ExtractionOut)
    assert out.value is not None
    assert isinstance(out.value, ExtractionOut)
    assert out.value.claims[0].object_value == "SGD 14.2M"
    assert len(llm.calls) == 1


def test_fenced_json_is_tolerated():
    llm = StubLLM([_FENCED])
    out = call_structured(llm, prompt_name="extract_claims", system="s", user="u", schema=ExtractionOut)
    assert out.value is not None
    assert isinstance(out.value, ExtractionOut)
    assert len(llm.calls) == 1


def test_bad_then_good_triggers_one_repair(caplog):
    llm = StubLLM([_BAD, _GOOD])
    with caplog.at_level(logging.INFO, logger="helixpay.ingest.extract.llm"):
        out = call_structured(llm, prompt_name="extract_claims", system="s", user="u", schema=ExtractionOut)
    assert out.value is not None
    assert isinstance(out.value, ExtractionOut)
    assert len(llm.calls) == 2  # original + one repair
    # the repair turn must feed the failure back, not just re-ask blindly
    assert "json" in llm.calls[1][1].lower()
    assert any("repair" in r.message.lower() for r in caplog.records)


def test_bad_twice_drops_and_logs(caplog):
    llm = StubLLM([_BAD, _BAD])
    with caplog.at_level(logging.WARNING, logger="helixpay.ingest.extract.llm"):
        out = call_structured(llm, prompt_name="extract_claims", system="s", user="u", schema=ExtractionOut)
    assert out.value is None
    assert len(llm.calls) == 2  # original + one repair, then give up
    assert any("drop" in r.message.lower() for r in caplog.records)


def test_repair_disabled_drops_immediately():
    llm = StubLLM([_BAD])
    out = call_structured(
        llm, prompt_name="extract_claims", system="s", user="u", schema=ExtractionOut, repair=False
    )
    assert out.value is None
    assert len(llm.calls) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Back-compat: plain generate-only stub yields .truncated == False
# ─────────────────────────────────────────────────────────────────────────────

def test_generate_only_stub_truncated_is_false():
    """Clients implementing only generate() (→ str) must never mark the result truncated."""
    llm = StubLLM([_GOOD])
    out = call_structured(llm, prompt_name="extract_claims", system="s", user="u", schema=ExtractionOut)
    assert out.truncated is False


# ─────────────────────────────────────────────────────────────────────────────
# Truncation detection via generate_with_meta
# ─────────────────────────────────────────────────────────────────────────────

def test_max_tokens_stop_reason_sets_truncated_true():
    """A client that surfaces stop_reason='max_tokens' must produce truncated=True."""
    truncated_json = '{"claims": [], "relations": []}'
    llm = StubLLMWithMeta([
        GenerationResult(text=truncated_json, stop_reason="max_tokens"),
    ])
    out = call_structured(llm, prompt_name="extract_claims", system="s", user="u", schema=ExtractionOut)
    assert out.value is not None
    assert out.truncated is True


def test_end_turn_stop_reason_truncated_is_false():
    """stop_reason='end_turn' is the normal completion — truncated must be False."""
    llm = StubLLMWithMeta([
        GenerationResult(text=_GOOD, stop_reason="end_turn"),
    ])
    out = call_structured(llm, prompt_name="extract_claims", system="s", user="u", schema=ExtractionOut)
    assert out.value is not None
    assert out.truncated is False


def test_none_stop_reason_truncated_is_false():
    """stop_reason=None (unknown) — truncated must be False."""
    llm = StubLLMWithMeta([
        GenerationResult(text=_GOOD, stop_reason=None),
    ])
    out = call_structured(llm, prompt_name="extract_claims", system="s", user="u", schema=ExtractionOut)
    assert out.truncated is False


def test_truncated_flag_propagates_from_repair_turn():
    """If the repair turn is what causes a truncation, truncated must still be True."""
    bad_text = "not json at all"
    truncated_good_json = '{"claims": [], "relations": []}'
    llm = StubLLMWithMeta([
        GenerationResult(text=bad_text, stop_reason="end_turn"),
        GenerationResult(text=truncated_good_json, stop_reason="max_tokens"),
    ])
    out = call_structured(llm, prompt_name="extract_claims", system="s", user="u", schema=ExtractionOut)
    assert out.value is not None
    assert out.truncated is True


def test_truncated_flag_true_when_both_turns_truncated():
    """Both turns truncated → value None but truncated=True."""
    llm = StubLLMWithMeta([
        GenerationResult(text=_BAD, stop_reason="max_tokens"),
        GenerationResult(text=_BAD, stop_reason="max_tokens"),
    ])
    out = call_structured(llm, prompt_name="extract_claims", system="s", user="u", schema=ExtractionOut)
    assert out.value is None
    assert out.truncated is True


# ─────────────────────────────────────────────────────────────────────────────
# GenerationResult dataclass
# ─────────────────────────────────────────────────────────────────────────────

def test_generation_result_is_frozen():
    gr = GenerationResult(text="hello", stop_reason="end_turn")
    assert gr.text == "hello"
    assert gr.stop_reason == "end_turn"


def test_generation_result_stop_reason_defaults_to_none():
    gr = GenerationResult(text="hello")
    assert gr.stop_reason is None


# ─────────────────────────────────────────────────────────────────────────────
# StructuredResult dataclass
# ─────────────────────────────────────────────────────────────────────────────

def test_structured_result_is_generic():
    sr: StructuredResult[ExtractionOut] = StructuredResult(value=ExtractionOut())
    assert sr.value is not None
    assert sr.truncated is False
