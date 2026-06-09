"""MarkdownConnector — inline fixtures written to tmp_path then loaded.

Covers the general markdown case (H1 + table), a heading-less transcript
(speaker turns), and a heading-less email-shaped .md (board-update), since both
top-level shapes occur in the real data/.
"""

from __future__ import annotations

from datetime import date

from helixpay.contracts import SourceType
from helixpay.ingest.loaders.markdown import MarkdownConnector


def _write(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return str(p)


def test_markdown_general_doc(tmp_path):
    body = (
        "# HelixPay Overview\n\n"
        "We are a B2B payments company.\n\n"
        "| Product | Revenue |\n| Core | most |\n| POS | smaller |\n\n"
        "More prose here.\n"
    )
    path = _write(tmp_path, "overview-2026-04-22.md", body)
    doc, chunks = MarkdownConnector().load(path)
    assert doc.source_type == SourceType.md.value
    assert doc.title == "HelixPay Overview"
    assert doc.as_of == date(2026, 4, 22)  # from filename
    assert doc.content_hash and chunks
    assert all(c.document_id is None for c in chunks)
    # the product table is intact in some chunk
    assert any("| Product | Revenue |" in c.text and "| POS | smaller |" in c.text for c in chunks)


def test_markdown_headingless_transcript_preserves_turns(tmp_path):
    body = (
        "# All-Hands — April 15, 2026\n\n"
        "*Source: Zoom recording.*\n\n"
        "**0:00 — Wei Chen**\n\nThanks for joining, Q1 numbers next.\n\n"
        "**0:42 — Lim Boon Hock**\n\nRevenue closed at SGD 14.2 million.\n"
    )
    path = _write(tmp_path, "all-hands-2026-04-15.md", body)
    doc, chunks = MarkdownConnector().load(path)
    assert doc.as_of == date(2026, 4, 15)
    text = "\n".join(c.text for c in chunks)
    assert "Wei Chen" in text and "Lim Boon Hock" in text
    assert "14.2 million" in text


def test_markdown_headingless_email_shaped(tmp_path):
    body = (
        "From: Wei Chen <wei@helixpay.io>\n"
        "To: Board <board@helixpay.io>\n"
        "Date: Tue, 22 Apr 2026 18:42 +08:00\n"
        "Subject: April board update\n\n"
        "Q1 closed under plan. Confluence reset.\n"
    )
    path = _write(tmp_path, "board-update-2026-04-22.md", body)
    doc, chunks = MarkdownConnector().load(path)
    assert doc.title is None  # no H1
    assert doc.as_of == date(2026, 4, 22)  # from the Date: header
    assert len(chunks) >= 1 and "Confluence reset" in "\n".join(c.text for c in chunks)


def test_markdown_discovery_is_directory_scoped(tmp_path):
    # top-level + interviews are claimed; chat/email/code .md are NOT
    (tmp_path / "overview.md").write_text("# o", encoding="utf-8")
    (tmp_path / "interviews" / "sales").mkdir(parents=True)
    (tmp_path / "interviews" / "sales" / "x.md").write_text("# x", encoding="utf-8")
    (tmp_path / "chat").mkdir()
    (tmp_path / "chat" / "c.md").write_text("# c", encoding="utf-8")
    found = set(MarkdownConnector().discover(str(tmp_path)))
    assert str(tmp_path / "overview.md") in found
    assert str(tmp_path / "interviews" / "sales" / "x.md") in found
    assert str(tmp_path / "chat" / "c.md") not in found
