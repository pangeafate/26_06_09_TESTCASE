"""Unit tests for the shared loader substrate (SP_002).

Pure functions on inline fixtures — no I/O, no network. These pin the
idempotency hash, token estimate, the boundary-aware chunker (tables / messages
are atomic and never split), document-date extraction, and table rendering.
"""

from __future__ import annotations

from datetime import date

from helixpay.contracts import Chunk
from helixpay.ingest.loaders.base import (
    Segment,
    chunk_segments,
    compute_content_hash,
    estimate_tokens,
    extract_iso_date,
    normalize_text,
    render_table,
    segment_markdown,
    to_chunks,
)


# --- normalization + content hash -------------------------------------------
def test_content_hash_is_stable_across_reads():
    assert compute_content_hash("hello world") == compute_content_hash("hello world")


def test_content_hash_ignores_line_endings_and_trailing_space():
    assert compute_content_hash("a\r\nb  \n") == compute_content_hash("a\nb\n")
    assert compute_content_hash("a\nb") == compute_content_hash("a\nb\n\n")


def test_raw_text_normalization_reproduces_the_hashed_bytes():
    raw = "x\r\ny   \nz"
    norm = normalize_text(raw)
    # re-hashing the stored normalized text reproduces the document hash
    assert compute_content_hash(norm) == compute_content_hash(raw)


# --- token estimate ----------------------------------------------------------
def test_estimate_tokens_empty_is_zero():
    assert estimate_tokens("") == 0


def test_estimate_tokens_monotonic():
    short = estimate_tokens("a" * 40)
    long = estimate_tokens("a" * 4000)
    assert long > short


# --- chunker -----------------------------------------------------------------
def test_chunker_never_splits_a_table_segment():
    big_table = "| col |\n" + "\n".join(f"| row {i} |" for i in range(400))  # > max
    segs = [Segment("intro prose", splittable=True), Segment(big_table, splittable=False)]
    chunks = chunk_segments(segs)
    # the entire table appears verbatim in exactly one chunk
    holders = [c for c in chunks if "| row 399 |" in c]
    assert len(holders) == 1
    assert "| row 0 |" in holders[0] and "| row 200 |" in holders[0]


def test_chunker_keeps_each_message_whole():
    msgs = [Segment(f"**msg {i}** body of message {i}", splittable=False) for i in range(6)]
    chunks = chunk_segments(msgs, max_tokens=20, target_tokens=15)
    joined = "\n---\n".join(chunks)
    for i in range(6):
        # each message body is intact (never split across a chunk boundary)
        assert f"body of message {i}" in joined
    for c in chunks:
        # a message never appears half in one chunk and half in another
        for i in range(6):
            head = f"**msg {i}**"
            if head in c:
                assert f"body of message {i}" in c


def test_chunker_respects_max_unless_single_atomic_segment():
    prose = " ".join(f"sentence number {i}." for i in range(400))  # splittable, > max
    chunks = chunk_segments([Segment(prose, splittable=True)], max_tokens=200)
    assert all(estimate_tokens(c) <= 200 for c in chunks)
    # a single atomic oversize segment is allowed to exceed max
    atomic = "x" * 2000
    big = chunk_segments([Segment(atomic, splittable=False)], max_tokens=200)
    assert len(big) == 1 and estimate_tokens(big[0]) > 200


def test_chunker_packs_small_segments_together():
    segs = [Segment(f"part {i}", splittable=True) for i in range(10)]
    chunks = chunk_segments(segs, max_tokens=100, target_tokens=80)
    assert len(chunks) < 10  # several small parts share a chunk
    assert all(estimate_tokens(c) <= 100 for c in chunks)


def test_chunker_drops_empty_segments():
    assert chunk_segments([Segment("", splittable=True), Segment("  ", splittable=True)]) == []


# --- date extraction ---------------------------------------------------------
def test_extract_date_iso_substring_ignores_time():
    assert extract_iso_date("- **Completed:** 2026-04-10 10:14") == date(2026, 4, 10)


def test_extract_date_labeled_issue_wins_over_earlier_plain_date():
    text = "Reporting period: 1 January 2026 - 31 March 2026. Issued: 15 April 2026."
    assert extract_iso_date(text) == date(2026, 4, 15)


def test_extract_date_month_name_with_comma():
    assert extract_iso_date("# All-Hands — April 15, 2026") == date(2026, 4, 15)


def test_extract_date_rfc2822_header():
    assert extract_iso_date("Date: Tue, 22 Apr 2026 18:42 +08:00") == date(2026, 4, 22)


def test_extract_date_filename_fallback():
    assert extract_iso_date("no date in body", fallback_path="x/all-hands-2026-04-15.md") == date(
        2026, 4, 15
    )


def test_extract_date_none_when_absent():
    assert extract_iso_date("there is no date here") is None


# --- markdown segmenter ------------------------------------------------------
def test_segment_markdown_keeps_table_atomic_and_attaches_heading():
    md = "# Title\n\nintro paragraph\n\n| a | b |\n| 1 | 2 |\n\ntail paragraph"
    segs = segment_markdown(md)
    tables = [s for s in segs if not s.splittable]
    assert len(tables) == 1
    assert "| a | b |" in tables[0].text and "| 1 | 2 |" in tables[0].text
    # the H1 attaches to the first prose block
    assert any(s.splittable and "Title" in s.text and "intro paragraph" in s.text for s in segs)


def test_segment_markdown_attaches_whole_line_bold_speaker_label():
    md = "**0:00 — Wei Chen**\n\nHey everyone thanks for joining."
    segs = segment_markdown(md)
    assert any("Wei Chen" in s.text and "thanks for joining" in s.text for s in segs)


def test_segment_markdown_consecutive_headings_are_not_dropped():
    # regression: "# H1" then "## H2" with no body between must keep BOTH (the
    # interview files are "# Interview: Name\n\n## Meta\n..." — the name must survive)
    md = "# Interview: Maria Silva\n\n## Meta\n\nRole: Head of Sales Brasil"
    segs = segment_markdown(md)
    joined = "\n".join(s.text for s in segs)
    assert "Interview: Maria Silva" in joined
    assert "Meta" in joined and "Head of Sales Brasil" in joined


# --- render_table + to_chunks ------------------------------------------------
def test_render_table_carries_figures():
    out = render_table([["Metric", "Q1 2026"], ["Revenue", "14.2"], ["EBITDA", "(2.1)"]])
    assert "Revenue" in out and "14.2" in out and "|" in out


def test_render_table_tolerates_none_cells():
    out = render_table([["a", None], [None, "b"]])
    assert "a" in out and "b" in out  # no crash on None cells


def test_to_chunks_assigns_ordinals_and_handles_empty():
    assert to_chunks([]) == []
    chunks = to_chunks(["first", "second"])
    assert all(isinstance(c, Chunk) for c in chunks)
    assert [c.ordinal for c in chunks] == [0, 1]
    assert chunks[0].document_id is None  # assigned at persist time by the pipeline
