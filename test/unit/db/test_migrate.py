"""Statement-splitting for the schema migration — `migrate._statements` (pure, no DB).

The CLAUDE.md gotchas flag this seam as historically fragile: migrate applies the schema
statement-by-statement, so comment-stripping + split-on-``;`` must be exactly right (a
botched split silently drops DDL). `_statements` is module-private, but it *is* the unit
of that fragility and the only DB-free entry point — testing it directly is an intentional
exception to the no-private-method rule, justified by the gotcha.
"""

from __future__ import annotations

from helixpay.db.migrate import _statements


def test_splits_on_semicolons():
    assert _statements("CREATE TABLE a (id int); CREATE TABLE b (id int);") == [
        "CREATE TABLE a (id int)",
        "CREATE TABLE b (id int)",
    ]


def test_drops_empty_trailing_statement():
    # a trailing ';' must not yield an empty final statement
    assert _statements("SELECT 1;") == ["SELECT 1"]


def test_final_statement_without_semicolon_is_kept():
    assert _statements("CREATE EXTENSION vector") == ["CREATE EXTENSION vector"]


def test_strips_full_line_comments():
    sql = "-- create the extension first\nCREATE EXTENSION vector;"
    assert _statements(sql) == ["CREATE EXTENSION vector"]


def test_strips_inline_trailing_comment():
    sql = "CREATE TABLE a (id int);  -- the claims table\n"
    assert _statements(sql) == ["CREATE TABLE a (id int)"]


def test_preserves_multiline_statement_body():
    sql = "CREATE TABLE a (\n  id int,\n  name text\n);"
    stmts = _statements(sql)
    assert len(stmts) == 1
    assert stmts[0].startswith("CREATE TABLE a (")
    assert "name text" in stmts[0]


def test_comment_only_script_yields_no_statements():
    assert _statements("-- just a comment\n-- another\n") == []


def test_blank_and_whitespace_only_segments_are_dropped():
    assert _statements("\n\n  ;  \nSELECT 1;\n\n") == ["SELECT 1"]
