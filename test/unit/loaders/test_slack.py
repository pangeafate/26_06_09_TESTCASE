"""SlackConnector — message boundaries (speaker + timestamp) are preserved and
never split; multilingual lines pass through verbatim.
"""

from __future__ import annotations

from helixpay.contracts import SourceType
from helixpay.ingest.loaders.slack import SlackConnector

_EXPORT = """# #eng-random — Slack export

*Channel: #eng-random. Export window: 2026-04-08 to 2026-04-21.*

---

**Tue Apr 08 09:14 — sara.w**
who broke the build

**Tue Apr 08 13:30 — luiz.f**
oi galera, qualquer um da equipe SG no escritório hoje?

**Tue Apr 08 14:55 — pedro.a**
tan wei ming and i pushed a fix for the merchant_id index bug
"""


def _write(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return str(p)


def test_slack_preserves_speaker_and_timestamp(tmp_path):
    path = _write(tmp_path, "eng-random-april.md", _EXPORT)
    doc, chunks = SlackConnector().load(path)
    assert doc.source_type == SourceType.slack.value
    text = "\n".join(c.text for c in chunks)
    # speaker handles and timestamps survive
    assert "sara.w" in text and "Tue Apr 08 09:14" in text
    assert "pedro.a" in text and "Tue Apr 08 14:55" in text


def test_slack_keeps_each_turn_whole(tmp_path):
    path = _write(tmp_path, "eng-random-april.md", _EXPORT)
    _, chunks = SlackConnector().load(path)
    for c in chunks:
        # if a speaker header is in a chunk, that speaker's body is too (no mid-turn split)
        if "luiz.f" in c.text:
            assert "qualquer um da equipe SG" in c.text  # Portuguese passes through verbatim


def test_slack_multilingual_verbatim(tmp_path):
    path = _write(tmp_path, "eng-random-april.md", _EXPORT)
    _, chunks = SlackConnector().load(path)
    assert any("escritório" in c.text for c in chunks)


def test_slack_header_detection_is_not_redos_prone(tmp_path):
    # a hostile unclosed bold line with many dash separators must not hang the
    # message-header matcher (ReDoS guard) — completes well under a second
    import time

    evil = "**12:34 " + "word - " * 8000  # opens with **, has a clock, never closes
    body = f"# chan\n\n{evil}\n\n**Tue Apr 08 09:14 — sara.w**\nhi\n"
    path = _write(tmp_path, "hostile.md", body)
    start = time.time()
    _, chunks = SlackConnector().load(path)
    assert time.time() - start < 1.0
    assert any("sara.w" in c.text for c in chunks)  # the real message still parses
