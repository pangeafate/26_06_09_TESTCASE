"""EmailConnector — From/To/Subject parsed onto the Document; as_of from the
FIRST Date: header (the outermost / most-recent message in a forwarded thread).
"""

from __future__ import annotations

from datetime import date

from helixpay.contracts import SourceType
from helixpay.ingest.loaders.email import EmailConnector

_THREAD = """From: Maria Santos <maria.santos@helixpay.io>
To: Lucas Andrade <lucas@acaiexpress.com.br>
Date: Mon, 14 Apr 2026 19:40 -03:00
Subject: Re: Açaí Express — integration timeline

Lucas, thanks for the patience. Here is the updated plan.

> From: Lucas Andrade <lucas@acaiexpress.com.br>
> Date: Mon, 14 Apr 2026 18:12 -03:00
> We need the go-live before May.
"""


def _write(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return str(p)


def test_email_headers_parsed(tmp_path):
    path = _write(tmp_path, "customer-acai-express-thread.md", _THREAD)
    doc, chunks = EmailConnector().load(path)
    assert doc.source_type == SourceType.email.value
    assert doc.title == "Re: Açaí Express — integration timeline"
    assert doc.author and "Maria Santos" in doc.author
    assert chunks


def test_email_as_of_is_first_date_header(tmp_path):
    path = _write(tmp_path, "customer-acai-express-thread.md", _THREAD)
    doc, _ = EmailConnector().load(path)
    assert doc.as_of == date(2026, 4, 14)  # outermost Date wins (both are the 14th)


def test_email_body_preserved(tmp_path):
    path = _write(tmp_path, "customer-acai-express-thread.md", _THREAD)
    _, chunks = EmailConnector().load(path)
    text = "\n".join(c.text for c in chunks)
    assert "updated plan" in text and "go-live before May" in text
