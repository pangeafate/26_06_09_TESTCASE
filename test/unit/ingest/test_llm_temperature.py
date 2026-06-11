"""The additive temperature seam on ``AnthropicClient`` (SP_028b H1).

The LLM adjudication pass needs a deterministic (temperature 0) Opus client. The seam is a
single optional ``temperature`` on ``AnthropicClient.__init__`` that rides on the instance and is
read in ``generate_with_meta``. It is ADDITIVE: when ``None`` (the default) the ``temperature``
kwarg is OMITTED from ``messages.create`` entirely, so every pre-SP_028b caller is byte-for-byte
unchanged. The ``LLMClient`` Protocol and ``call_structured`` are untouched.
"""

from __future__ import annotations

from helixpay.ingest.extract.llm import AnthropicClient


class _Block:
    type = "text"
    text = "ok"


class _Resp:
    content = [_Block()]
    stop_reason = "end_turn"


class _RecordingMessages:
    def __init__(self) -> None:
        self.kwargs: dict | None = None

    def create(self, **kwargs: object) -> _Resp:
        self.kwargs = kwargs
        return _Resp()


class _RecordingAnthropic:
    def __init__(self) -> None:
        self.messages = _RecordingMessages()


def test_default_client_omits_temperature_kwarg() -> None:
    fake = _RecordingAnthropic()
    client = AnthropicClient(client=fake)
    client.generate(system="s", user="u", max_tokens=16)
    assert fake.messages.kwargs is not None
    assert "temperature" not in fake.messages.kwargs  # pre-SP_028b call shape, unchanged


def test_temperature_zero_is_forwarded() -> None:
    fake = _RecordingAnthropic()
    client = AnthropicClient(client=fake, temperature=0)
    client.generate(system="s", user="u", max_tokens=16)
    assert fake.messages.kwargs is not None
    assert fake.messages.kwargs["temperature"] == 0


def test_temperature_attribute_is_stored() -> None:
    assert AnthropicClient(temperature=0).temperature == 0
    assert AnthropicClient().temperature is None
