"""Named prompts load from disk and render — no inline prompt strings in code."""

from __future__ import annotations

import pytest

from helixpay.ingest.extract.prompts import (
    PromptNotFoundError,
    available_prompts,
    load_prompt,
    render,
)


def test_extract_prompt_exists_and_is_named():
    assert "extract_claims" in available_prompts()
    text = load_prompt("extract_claims")
    assert text.strip()
    assert "JSON" in text  # the structured-output instruction


def test_render_substitutes_chunk_variables():
    out = render(
        "extract_claims",
        source_type="md",
        source_uri="data/x.md",
        as_of="2026-03-31",
        roster_hint="Daniel Tan (person)",
        chunk_text="ZZ_UNIQUE_BODY_ZZ",
    )
    assert "ZZ_UNIQUE_BODY_ZZ" in out
    assert "data/x.md" in out
    assert "{{chunk_text}}" not in out  # placeholder consumed


def test_unknown_prompt_raises_clear_error():
    with pytest.raises(PromptNotFoundError):
        load_prompt("does_not_exist")


def test_prompt_resolution_is_cwd_independent(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # not the repo root
    assert load_prompt("extract_claims").strip()  # still found (package-anchored)
