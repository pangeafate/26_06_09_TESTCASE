"""The LLM seam: structured output with a one-shot validate-and-repair-or-drop loop."""

from __future__ import annotations

import logging

from helixpay.ingest.extract.llm import call_structured
from helixpay.ingest.extract.schemas import ExtractionOut

_GOOD = '{"claims": [{"subject": "HelixPay", "predicate": "ARR", "object_value": "SGD 14.2M"}], "relations": []}'
_FENCED = "Here you go:\n```json\n" + _GOOD + "\n```\n"
_BAD = "sorry, I cannot produce JSON"


class StubLLM:
    """Returns scripted responses in order; records each (system, user) call."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def generate(self, *, system: str, user: str, max_tokens: int) -> str:
        self.calls.append((system, user))
        return self._responses.pop(0)


def test_valid_json_parses_in_one_call():
    llm = StubLLM([_GOOD])
    out = call_structured(llm, prompt_name="extract_claims", system="s", user="u", schema=ExtractionOut)
    assert isinstance(out, ExtractionOut)
    assert out.claims[0].object_value == "SGD 14.2M"
    assert len(llm.calls) == 1


def test_fenced_json_is_tolerated():
    llm = StubLLM([_FENCED])
    out = call_structured(llm, prompt_name="extract_claims", system="s", user="u", schema=ExtractionOut)
    assert isinstance(out, ExtractionOut)
    assert len(llm.calls) == 1


def test_bad_then_good_triggers_one_repair(caplog):
    llm = StubLLM([_BAD, _GOOD])
    with caplog.at_level(logging.INFO, logger="helixpay.ingest.extract.llm"):
        out = call_structured(llm, prompt_name="extract_claims", system="s", user="u", schema=ExtractionOut)
    assert isinstance(out, ExtractionOut)
    assert len(llm.calls) == 2  # original + one repair
    # the repair turn must feed the failure back, not just re-ask blindly
    assert "json" in llm.calls[1][1].lower()
    assert any("repair" in r.message.lower() for r in caplog.records)


def test_bad_twice_drops_and_logs(caplog):
    llm = StubLLM([_BAD, _BAD])
    with caplog.at_level(logging.WARNING, logger="helixpay.ingest.extract.llm"):
        out = call_structured(llm, prompt_name="extract_claims", system="s", user="u", schema=ExtractionOut)
    assert out is None
    assert len(llm.calls) == 2  # original + one repair, then give up
    assert any("drop" in r.message.lower() for r in caplog.records)


def test_repair_disabled_drops_immediately():
    llm = StubLLM([_BAD])
    out = call_structured(
        llm, prompt_name="extract_claims", system="s", user="u", schema=ExtractionOut, repair=False
    )
    assert out is None
    assert len(llm.calls) == 1
