"""Named prompts load from disk and render — no inline prompt strings in code.

Also the prompt-hygiene guard (SP_027): no ground-truth value OR graded subject may appear as a
few-shot example in any prompt (DEV_RULES §12). The extractor must EARN each graded fact by
extracting it, never be shown it — leaked examples inflate recall for the wrong reason.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from eval.run import DEFAULT_GOLDEN, load_golden
from helixpay.ingest.extract.prompts import (
    PromptNotFoundError,
    available_prompts,
    load_prompt,
    render,
)
from helixpay.ingest.normalize import normalize_value

_PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"  # test/unit/ingest/ → repo root

# The three corpus-identity entities the prompt legitimately MUST name: the task is *about*
# HelixPay, and the region map (SEA/Brasil ⇒ HelixPay SEA/Brasil) is load-bearing for the image
# pass. These are task definition, not a graded fact to be discovered. Everything else — graded
# initiatives, repos, people, figures — must be fictional in examples.
_STRUCTURAL_ALLOW = {"helixpay", "helixpay sea", "helixpay brasil"}


def _golden_leak_tokens() -> set[str]:
    """Each bar-fact's value AND subject (both are graded oracle fields), minus the structural
    allowlist and pure-numeric tokens shorter than 3 chars (which collide with incidental ints)."""
    g = load_golden(DEFAULT_GOLDEN)
    toks: set[str] = set()
    for f in g.bar_facts:
        for raw in (f.value, f.subject):
            s = (raw or "").strip()
            if not s or s.casefold() in _STRUCTURAL_ALLOW:
                continue
            if s.isdigit() and len(s) < 2:  # skip only single-digit ints; 2-digit graded
                continue                     # values (NPS "47", commit counts) ARE checked
            toks.add(s)
    return toks


def _present(token: str, blob_casefold: str) -> bool:
    """Word-boundary, casefold match — so a numeric like '412' does not match inside '2741'.
    Checks the raw token AND its normalized text form (so a currency/unit-reformatted leak is
    still caught); each candidate is checked independently so a short normalized form never
    suppresses the raw token."""
    candidates = {token, normalize_value(token)[0]}
    for needle in candidates:
        n = needle.strip().casefold()
        if len(n) < 2:  # a sub-2-char needle word-matches far too much to be meaningful
            continue
        if re.search(rf"(?<!\w){re.escape(n)}(?!\w)", blob_casefold):
            return True
    return False


def test_golden_values_and_subjects_do_not_leak_into_prompts():
    # DEV_RULES §12 leakage guard (SP_027). Code-resident few-shots are out of scope — only
    # prompts/*.md are model-facing, and no Python string literal feeds golden text to the model.
    blob = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore") for p in sorted(_PROMPTS_DIR.glob("*.md"))
    ).casefold()
    leaked = sorted({t for t in _golden_leak_tokens() if _present(t, blob)})
    assert not leaked, f"golden facts leaked into prompts/ (DEV_RULES §12): {leaked}"


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
