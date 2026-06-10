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


def test_extract_prompt_does_not_license_metric_as_subject():
    # SP_019 Layer 1: the prompt must no longer permit a metric name as the subject, and the
    # JSON example must not exemplify subject_type "metric". Guards the attribution intent.
    out = render(
        "extract_claims",
        source_type="html", source_uri="data/d.html", as_of="2026-03-31",
        roster_hint="(none)", chunk_text="body",
    )
    assert "metric name like" not in out  # the metric-as-subject license is gone
    assert "primary entity" in out.lower()  # the default-subject rule is present
    # `subject_type: "metric"` may appear ONLY inside a ✗-wrong negative example, never as
    # guidance or in the output template.
    for line in out.splitlines():
        if '"subject_type": "metric"' in line:
            assert "✗" in line or "wrong" in line.lower(), f"metric exemplified as valid: {line!r}"


def test_extract_prompt_guides_milestone_and_ranking_attribution():
    # SP_019 final-mile (gated): the prompt teaches initiative-milestone attribution
    # (ga_target/completion_target on the named initiative, clean human date value) and the
    # contributor-ranking → top_contributor shape. The messy surface forms baked into the old
    # cache must appear ONLY inside ✗-wrong negative examples, never as guidance.
    out = render(
        "extract_claims",
        source_type="pdf", source_uri="data/board-deck-q1-2026.pdf", as_of="2026-05-12",
        roster_hint="(none)", chunk_text="body",
    )
    low = out.lower()
    assert "ga_target" in out and "completion_target" in out
    assert "top_contributor" in out
    assert "named initiative" in low  # the attribute-to-the-initiative rule
    for line in out.splitlines():
        if "ga target date (revised)" in line or "pipedrive decommission date" in line:
            assert "✗" in line or "wrong" in line.lower(), f"messy form shown as valid: {line!r}"


def test_unknown_prompt_raises_clear_error():
    with pytest.raises(PromptNotFoundError):
        load_prompt("does_not_exist")


def test_prompt_resolution_is_cwd_independent(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # not the repo root
    assert load_prompt("extract_claims").strip()  # still found (package-anchored)
