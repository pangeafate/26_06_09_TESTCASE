"""Grounding assembly + the no-uncited-claims guard for ``ask()``.

The synthesis step is the one place free-form LLM text enters the system, so it
is fenced on both sides:

* **In** — a grounding context of numbered facts. Governed claims are ``[C#]``
  (citeable); retrieved chunks are ``[S#]`` (context only). The model is told to
  use only these and to cite the marker behind every factual sentence.
* **Out** — the model returns structured output (``SYNTH_SCHEMA``: per-sentence
  text + cites), and ``enforce_citations`` drops any factual sentence that is not
  backed by a **claim** marker. This is the mechanism that guarantees
  "``ask()`` output has zero uncited claims" (CLAUDE.md §7).

Citation policy (review arch-H3): only **claim-backed** sentences are kept,
because only claims have a Protocol path to provenance (``get_sources`` →
``source_uri`` + ``as_of``). Chunk excerpts steer synthesis but cannot, through
the frozen Protocol, become a spec ``Citation`` — so a sentence cited only to a
chunk is dropped rather than emitted uncited. (Friction: a
``get_chunk_sources`` read would let chunk-grounded narrative be cited too.)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from helixpay.contracts import Chunk, Citation, Claim

if TYPE_CHECKING:
    from helixpay.contracts import Repository

FALLBACK_ANSWER = "I could not find sufficient cited evidence to answer that."

_PROMPT_PATH = Path(__file__).parent / "prompts" / "ask_synthesis.md"

# Structured-output schema the synthesizer must satisfy (validated at the seam).
SYNTH_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "sentences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "cites": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["text", "cites"],
            },
        },
        "confidence": {"type": "number"},
    },
    "required": ["sentences"],
}


@dataclass(frozen=True)
class GroundingFact:
    marker: str
    kind: str  # "claim" | "chunk"
    ref_id: Optional[int]
    text: str


def _claim_line(c: Claim) -> str:
    base = f"{c.predicate}: {c.object_value}"
    if c.as_of is not None:
        base += f" (as of {c.as_of.isoformat()})"
    return base


def build_grounding(
    claims: list[Claim], chunks: list[Chunk]
) -> tuple[str, dict[str, GroundingFact]]:
    """Number the facts (claims ``[C#]``, chunks ``[S#]``) and return the text
    block plus a marker→fact index for citation enforcement."""
    facts: dict[str, GroundingFact] = {}
    lines: list[str] = []
    for i, claim in enumerate(claims, start=1):
        marker = f"C{i}"
        text = _claim_line(claim)
        facts[marker] = GroundingFact(marker, "claim", claim.id, text)
        lines.append(f"[{marker}] (claim) {text}")
    for j, chunk in enumerate(chunks, start=1):
        marker = f"S{j}"
        facts[marker] = GroundingFact(marker, "chunk", chunk.id, chunk.text)
        lines.append(f"[{marker}] (source excerpt) {chunk.text}")
    return "\n".join(lines), facts


def load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


_PLACEHOLDER_RE = re.compile(r"\{question\}|\{grounding\}")


def render_prompt(question: str, grounding: str) -> str:
    """Fill the template in a single pass so content injected by one substitution
    is never re-expanded by the next (review code-H2). Literal JSON braces in the
    template are left untouched — only the two exact placeholders match."""
    mapping = {"{question}": question, "{grounding}": grounding}
    return _PLACEHOLDER_RE.sub(lambda m: mapping[m.group(0)], load_prompt())


def enforce_citations(
    output: dict, facts: dict[str, GroundingFact], repo: "Repository"
) -> tuple[str, list[Citation], list[int], float]:
    """Keep only claim-backed sentences; resolve their markers to ``Citation``s.

    Returns ``(answer, citations, cited_claim_ids, confidence)``. When nothing
    survives, returns the safe fallback with no fabricated citations.
    """
    # Defend against malformed / adversarial structured output: never crash, never
    # fabricate a citation (review security-MEDIUM). Unknown/non-claim/non-string
    # markers cannot become a Citation — only real claim markers survive.
    kept: list[str] = []
    cited_ids: list[int] = []
    seen: set[int] = set()
    raw_sentences = output.get("sentences") if isinstance(output, dict) else None
    if not isinstance(raw_sentences, list):
        raw_sentences = []
    for sentence in raw_sentences:
        if not isinstance(sentence, dict):
            continue
        text_val = sentence.get("text")
        text = text_val.strip() if isinstance(text_val, str) else ""
        cites = sentence.get("cites")
        cites = cites if isinstance(cites, list) else []
        claim_markers = [
            m for m in cites if isinstance(m, str) and m in facts and facts[m].kind == "claim"
        ]
        if not text or not claim_markers:
            continue
        kept.append(text)
        for marker in claim_markers:
            rid = facts[marker].ref_id
            if rid is not None and rid not in seen:
                seen.add(rid)
                cited_ids.append(rid)

    if not kept:
        return FALLBACK_ANSWER, [], [], 0.0

    answer = " ".join(kept)
    citations = repo.get_sources(cited_ids)
    raw_conf = output.get("confidence") if isinstance(output, dict) else None
    try:
        confidence = float(raw_conf)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        confidence = min(0.9, 0.3 + 0.15 * len(citations))
    return answer, citations, cited_ids, confidence


__all__ = [
    "FALLBACK_ANSWER",
    "SYNTH_SCHEMA",
    "GroundingFact",
    "build_grounding",
    "load_prompt",
    "render_prompt",
    "enforce_citations",
]
