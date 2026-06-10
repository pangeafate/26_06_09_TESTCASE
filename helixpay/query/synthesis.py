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

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from helixpay.contracts import Chunk, Citation, Claim, Contradiction, Link
from helixpay.query.citations import (
    FALLBACK_ANSWER,
    collect_ref_ids,
    resolve_cited_sentences,
)
from helixpay.query.consensus import ConsensusGroup

if TYPE_CHECKING:
    from helixpay.contracts import Repository

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
        cval = g.consensus_value if g.consensus_value is not None else "(no stated value)"
        line = f"- {g.predicate}: {cval} — {g.corroborating_count} source(s) agree"
        if g.freshest_as_of is not None:
            line += f", freshest {g.freshest_as_of.isoformat()}"
        if cons:
            line += f" [{cons}]"
        for d in g.dissent:
            dm = ", ".join(cmap[i] for i in d.claim_ids if i in cmap)
            dval = d.value if d.value is not None else "(no stated value)"
            line += f"; dissent: {dval}" + (f" [{dm}]" if dm else "")
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
        if not (a and b):
            # Require BOTH sides to resolve to a grounding marker. A one-sided line
            # ("X conflict: [C1] vs") would have the model narrate a conflict it can only
            # half-attribute — worse than silence. The conflict still rides on
            # AnswerBundle.contradictions (surfaced, never hidden); we just don't prompt
            # the model to narrate one it cannot attribute on both sides.
            continue
        pred = f" on {c.predicate}" if c.predicate else ""
        note = f" — {c.note}" if c.note else ""
        lines.append(f"- {label} conflict{pred}: [{a}] vs [{b}]{note}".rstrip())
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


def enforce_citations(
    output: dict, facts: dict[str, GroundingFact], repo: "Repository"
) -> tuple[str, list[Citation], list[int], float]:
    """Keep only sentences whose markers resolve to a real ``Citation``; resolve them.

    Thin I/O shell over :mod:`helixpay.query.citations` (SP_018): bucket the cited
    ref-ids, batch-resolve each bucket through the ``Repository``, apply the
    verbatim-evidence override, then delegate the pure keep/dedup/confidence logic.

    Returns ``(answer, citations, cited_claim_ids, confidence)``. ``cited_claim_ids`` is
    **claim-only** (the engine trace + confidence read it); chunk/link citations are
    merged into ``citations`` only. When nothing survives, returns the safe fallback with
    no fabricated citations. Robust to malformed/adversarial structured output: an
    unresolved marker can never become a ``Citation``.
    """
    raw_sentences = output.get("sentences") if isinstance(output, dict) else None

    # 1. bucket the distinct refs the sentences cite, then resolve each through the repo.
    claim_ids, chunk_ids, link_ids = collect_ref_ids(raw_sentences, facts)
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

    # 2. verbatim-span override: quote the claim's evidence instead of the chunk prefix.
    #    (kept here — it needs the resolved Citation objects from the repo reads above.)
    evidence_by_claim = {
        f.ref_id: f.evidence
        for f in facts.values()
        if f.kind == "claim" and f.ref_id is not None and f.evidence
    }
    for cid, ev in evidence_by_claim.items():
        if cid in claim_cites:
            claim_cites[cid] = claim_cites[cid].model_copy(update={"snippet": ev})

    # 3. pure keep/dedup + confidence over the already-resolved cite maps.
    raw_conf = output.get("confidence") if isinstance(output, dict) else None
    return resolve_cited_sentences(
        raw_sentences, facts, claim_cites, chunk_cites, link_cites, raw_conf
    )


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
