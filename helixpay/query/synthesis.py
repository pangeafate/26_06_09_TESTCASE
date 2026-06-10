"""Grounding assembly + the no-uncited-claims guard for ``ask()``.

The synthesis step is the one place free-form LLM text enters the system, so it
is fenced on both sides:

* **In** — a grounding context of numbered facts. Governed claims are ``[C#]``
  (citeable); retrieved chunks are ``[S#]`` (context only). The model is told to
  use only these and to cite the marker behind every factual sentence.
* **Out** — the model returns structured output (``SYNTH_SCHEMA``: per-sentence
  text + cites), and ``enforce_citations`` drops any factual sentence whose markers
  do not resolve to a real ``Citation``. This is the mechanism that guarantees
  "``ask()`` output has zero uncited claims" (CLAUDE.md §7).

Citation policy (SP_012, closing the chunk-citation hole): a sentence is kept iff at
least one of its markers resolves — through the Repository — to a real ``Citation``.
Since SP_009 there are three provenance paths, so all three marker kinds are citeable:
``[C#]`` claims (``get_sources``), ``[S#]`` retrieved chunks (``get_chunk_sources``),
and ``[L#]`` relationships (``get_link_sources``). A marker that resolves to nothing
still cannot fabricate a citation — the sentence is dropped. ``cited_claim_ids`` stays
**claim-only** (the trace + confidence depend on it); chunk/link citations are merged
into the returned ``citations`` list only. Where a cited claim carries a verbatim
``evidence`` span (SP_009), the citation snippet is overridden to quote the fact itself
(FRONT/LongCite pattern) instead of the chunk prefix.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from helixpay.contracts import Chunk, Citation, Claim, Contradiction, Link
from helixpay.query.consensus import ConsensusGroup

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
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["sentences"],
}


@dataclass(frozen=True)
class GroundingFact:
    marker: str
    kind: str  # "claim" | "chunk" | "link"
    ref_id: Optional[int]
    text: str
    evidence: Optional[str] = None  # claims only: the verbatim span (SP_009)


def _claim_line(c: Claim) -> str:
    base = f"{c.predicate}: {c.object_value}"
    if c.as_of is not None:
        base += f" (as of {c.as_of.isoformat()})"
    return base


def _link_line(link: Link, name_map: dict[int, str]) -> str:
    """Render a relationship for grounding. The Repository offers no id→name lookup
    (``resolve_entity`` is name→entity), so unknown ids fall back to ``#id`` — the same
    stance ``graph.py`` takes for org nodes."""
    frm = name_map.get(link.from_entity_id, f"#{link.from_entity_id}")
    to = name_map.get(link.to_entity_id, f"#{link.to_entity_id}")
    base = f"{link.link_type}: {frm} → {to}"
    if link.as_of is not None:
        base += f" (as of {link.as_of.isoformat()})"
    return base


def build_grounding(
    claims: list[Claim],
    chunks: list[Chunk],
    links: Optional[list[Link]] = None,
    *,
    name_map: Optional[dict[int, str]] = None,
) -> tuple[str, dict[str, GroundingFact]]:
    """Number the facts (claims ``[C#]``, chunks ``[S#]``, relationships ``[L#]``) and
    return the text block plus a marker→fact index for citation enforcement. ``links``
    and ``name_map`` are keyword-defaulted so existing ``build_grounding(claims, chunks)``
    calls are unchanged."""
    names = name_map or {}
    facts: dict[str, GroundingFact] = {}
    lines: list[str] = []
    for i, claim in enumerate(claims, start=1):
        marker = f"C{i}"
        text = _claim_line(claim)
        facts[marker] = GroundingFact(
            marker, "claim", claim.id, text, evidence=claim.evidence
        )
        lines.append(f"[{marker}] (claim) {text}")
    for j, chunk in enumerate(chunks, start=1):
        marker = f"S{j}"
        facts[marker] = GroundingFact(marker, "chunk", chunk.id, chunk.text)
        lines.append(f"[{marker}] (source excerpt) {chunk.text}")
    for k, link in enumerate(links or [], start=1):
        marker = f"L{k}"
        text = _link_line(link, names)
        facts[marker] = GroundingFact(marker, "link", link.id, text)
        lines.append(f"[{marker}] (relationship) {text}")
    return "\n".join(lines), facts


def _claim_markers(facts: dict[str, GroundingFact]) -> dict[int, str]:
    return {
        f.ref_id: m
        for m, f in facts.items()
        if f.kind == "claim" and f.ref_id is not None
    }


def _link_markers(facts: dict[str, GroundingFact]) -> dict[int, str]:
    return {
        f.ref_id: m
        for m, f in facts.items()
        if f.kind == "link" and f.ref_id is not None
    }


def render_consensus(
    groups: list[ConsensusGroup], facts: dict[str, GroundingFact]
) -> str:
    """Render the consensus/dissent rollup as a grounding block that cites the existing
    ``[C#]`` claim markers. Returns ``""`` when there is nothing to roll up. Dissent
    values stay present and individually citeable — never collapsed."""
    if not groups:
        return ""
    cmap = _claim_markers(facts)
    lines = [
        "",
        "Consensus (governed claims grouped by value — state the consensus once and "
        "cite the listed markers; report dissent explicitly, never silently resolve):",
    ]
    for g in groups:
        cons = ", ".join(cmap[i] for i in g.member_ids if i in cmap)
        line = f"- {g.predicate}: {g.consensus_value} — {g.corroborating_count} source(s) agree"
        if g.freshest_as_of is not None:
            line += f", freshest {g.freshest_as_of.isoformat()}"
        if cons:
            line += f" [{cons}]"
        for d in g.dissent:
            dm = ", ".join(cmap[i] for i in d.claim_ids if i in cmap)
            line += f"; dissent: {d.value}" + (f" [{dm}]" if dm else "")
        lines.append(line)
    return "\n".join(lines)


def render_contradictions(
    typed: list[tuple[Contradiction, str]], facts: dict[str, GroundingFact]
) -> str:
    """Render typed contradictions as a grounding block, attributing each side to its
    marker (``[C#]`` for claim conflicts, ``[L#]`` for relationship conflicts). Returns
    ``""`` when there are none."""
    if not typed:
        return ""
    cmap = _claim_markers(facts)
    lmap = _link_markers(facts)
    lines = [
        "",
        "Contradictions (surface each and attribute every side to its marker; "
        "never pick one silently):",
    ]
    for c, label in typed:
        a = (cmap.get(c.claim_a_id) if c.claim_a_id is not None else None) or (
            lmap.get(c.link_a_id) if c.link_a_id is not None else None
        )
        b = (cmap.get(c.claim_b_id) if c.claim_b_id is not None else None) or (
            lmap.get(c.link_b_id) if c.link_b_id is not None else None
        )
        refs = " vs ".join(f"[{m}]" for m in (a, b) if m)
        if not refs:
            # Neither side is present as a grounding marker — emitting "<type> conflict:"
            # with nothing to cite would invite an uncited assertion. The conflict still
            # rides on AnswerBundle.contradictions (surfaced, not hidden); we just don't
            # ask the model to narrate one it cannot attribute.
            continue
        pred = f" on {c.predicate}" if c.predicate else ""
        note = f" — {c.note}" if c.note else ""
        lines.append(f"- {label} conflict{pred}: {refs}{note}".rstrip())
    if len(lines) <= 2:  # only the header rows — nothing attributable
        return ""
    return "\n".join(lines)


def load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


_PLACEHOLDER_RE = re.compile(r"\{question\}|\{grounding\}")


def render_prompt(question: str, grounding: str) -> str:
    """Fill the template in a single pass so content injected by one substitution
    is never re-expanded by the next (review code-H2). Literal JSON braces in the
    template are left untouched — only the two exact placeholders match."""
    mapping = {"{question}": question, "{grounding}": grounding}
    return _PLACEHOLDER_RE.sub(lambda m: mapping[m.group(0)], load_prompt())


def _valid_markers(sentence: object, facts: dict[str, GroundingFact]) -> list[str]:
    """The in-index markers a sentence cites (defends against malformed output)."""
    if not isinstance(sentence, dict):
        return []
    cites = sentence.get("cites")
    cites = cites if isinstance(cites, list) else []
    return [m for m in cites if isinstance(m, str) and m in facts]


def enforce_citations(
    output: dict, facts: dict[str, GroundingFact], repo: "Repository"
) -> tuple[str, list[Citation], list[int], float]:
    """Keep only sentences whose markers resolve to a real ``Citation``; resolve them.

    Returns ``(answer, citations, cited_claim_ids, confidence)``. ``cited_claim_ids`` is
    **claim-only** (the engine trace + confidence read it); chunk/link citations are
    merged into ``citations`` only. When nothing survives, returns the safe fallback with
    no fabricated citations. Robust to malformed/adversarial structured output: an
    unresolved marker can never become a ``Citation``.
    """
    raw_sentences = output.get("sentences") if isinstance(output, dict) else None
    if not isinstance(raw_sentences, list):
        raw_sentences = []

    # 1. collect every distinct ref a sentence points at, by kind, and resolve up-front.
    claim_ids: list[int] = []
    chunk_ids: list[int] = []
    link_ids: list[int] = []
    for sentence in raw_sentences:
        for m in _valid_markers(sentence, facts):
            f = facts[m]
            if f.ref_id is None:
                continue
            bucket = {"claim": claim_ids, "chunk": chunk_ids, "link": link_ids}.get(
                f.kind
            )
            if bucket is not None and f.ref_id not in bucket:
                bucket.append(f.ref_id)

    claim_cites = {
        c.claim_id: c for c in repo.get_sources(claim_ids) if c.claim_id is not None
    }
    chunk_cites = {
        c.chunk_id: c
        for c in repo.get_chunk_sources(chunk_ids)
        if c.chunk_id is not None
    }
    link_cites = {
        c.link_id: c for c in repo.get_link_sources(link_ids) if c.link_id is not None
    }

    # Verbatim-span override: quote the claim's evidence instead of the chunk prefix.
    evidence_by_claim = {
        f.ref_id: f.evidence
        for f in facts.values()
        if f.kind == "claim" and f.ref_id is not None and f.evidence
    }
    for cid, ev in evidence_by_claim.items():
        if cid in claim_cites:
            claim_cites[cid] = claim_cites[cid].model_copy(update={"snippet": ev})

    # 2. keep a sentence iff >=1 of its markers resolved; collect its citations.
    kept: list[str] = []
    citations: list[Citation] = []
    cited_claim_ids: list[int] = []
    seen_claim: set[int] = set()
    seen_cite: set[tuple] = set()
    for sentence in raw_sentences:
        text_val = sentence.get("text") if isinstance(sentence, dict) else None
        text = text_val.strip() if isinstance(text_val, str) else ""
        sent_cites: list[Citation] = []
        sent_claim_ids: list[int] = []
        for m in _valid_markers(sentence, facts):
            f = facts[m]
            if f.kind == "claim" and f.ref_id in claim_cites:
                sent_cites.append(claim_cites[f.ref_id])
                sent_claim_ids.append(f.ref_id)
            elif f.kind == "chunk" and f.ref_id in chunk_cites:
                sent_cites.append(chunk_cites[f.ref_id])
            elif f.kind == "link" and f.ref_id in link_cites:
                sent_cites.append(link_cites[f.ref_id])
        if not text or not sent_cites:
            continue
        kept.append(text)
        for cid in sent_claim_ids:
            if cid not in seen_claim:
                seen_claim.add(cid)
                cited_claim_ids.append(cid)
        for cit in sent_cites:
            key = (cit.claim_id, cit.chunk_id, cit.link_id, cit.source_uri)
            if key not in seen_cite:
                seen_cite.add(key)
                citations.append(cit)

    if not kept:
        return FALLBACK_ANSWER, [], [], 0.0

    answer = " ".join(kept)
    raw_conf = output.get("confidence") if isinstance(output, dict) else None
    try:
        confidence = float(raw_conf)  # type: ignore[arg-type]
        if not math.isfinite(confidence):  # reject NaN/inf the model may emit
            raise ValueError("non-finite confidence")
        confidence = max(
            0.0, min(1.0, confidence)
        )  # clamp to the documented 0..1 range
    except (TypeError, ValueError):
        confidence = min(0.9, 0.3 + 0.15 * len(citations))
    return answer, citations, cited_claim_ids, confidence


__all__ = [
    "FALLBACK_ANSWER",
    "SYNTH_SCHEMA",
    "GroundingFact",
    "build_grounding",
    "render_consensus",
    "render_contradictions",
    "load_prompt",
    "render_prompt",
    "enforce_citations",
]
