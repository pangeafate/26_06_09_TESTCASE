"""Pure citation-resolution core for ``ask()`` (no Repository, no LLM).

This is the deterministic half of the no-uncited-claims guard, split out of
``synthesis.enforce_citations`` (SP_018, GL-RDD SRP). ``synthesis`` keeps the I/O —
the three Repository reads that turn ref-ids into ``Citation`` rows and the
verbatim-evidence ``model_copy`` override — and hands the resolved cite maps here.

Two steps:

* :func:`collect_ref_ids` — scan the model's per-sentence markers and bucket the
  distinct claim / chunk / link ref-ids they point at (first-seen order, deduped). The
  caller batch-resolves each bucket through the Repository.
* :func:`resolve_cited_sentences` — keep a sentence iff >=1 of its markers resolves to a
  real ``Citation`` in the supplied maps; merge + dedup citations; return the
  ``claim-only`` cited-claim ids (the engine trace + confidence read these) and the
  clamped confidence. Robust to malformed/adversarial structured output: an unresolved
  marker can never become a ``Citation``.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Optional

from helixpay.contracts import Citation

if TYPE_CHECKING:  # avoid a runtime import cycle: synthesis -> citations
    from helixpay.query.synthesis import GroundingFact

FALLBACK_ANSWER = "I could not find sufficient cited evidence to answer that."


def _valid_markers(
    sentence: object, facts: "dict[str, GroundingFact]"
) -> list[str]:
    """The in-index markers a sentence cites (defends against malformed output)."""
    if not isinstance(sentence, dict):
        return []
    cites = sentence.get("cites")
    cites = cites if isinstance(cites, list) else []
    return [m for m in cites if isinstance(m, str) and m in facts]


def collect_ref_ids(
    raw_sentences: object, facts: "dict[str, GroundingFact]"
) -> tuple[list[int], list[int], list[int]]:
    """Bucket the distinct claim/chunk/link ref-ids the sentences cite.

    Returns ``(claim_ids, chunk_ids, link_ids)`` in first-seen order, deduped. Markers
    not in ``facts`` and facts with a ``None`` ``ref_id`` are ignored.
    """
    sentences = raw_sentences if isinstance(raw_sentences, list) else []
    claim_ids: list[int] = []
    chunk_ids: list[int] = []
    link_ids: list[int] = []
    buckets = {"claim": claim_ids, "chunk": chunk_ids, "link": link_ids}
    for sentence in sentences:
        for m in _valid_markers(sentence, facts):
            f = facts[m]
            if f.ref_id is None:
                continue
            bucket = buckets.get(f.kind)
            if bucket is not None and f.ref_id not in bucket:
                bucket.append(f.ref_id)
    return claim_ids, chunk_ids, link_ids


def resolve_cited_sentences(
    raw_sentences: object,
    facts: "dict[str, GroundingFact]",
    claim_cites: dict[int, Citation],
    chunk_cites: dict[int, Citation],
    link_cites: dict[int, Citation],
    raw_confidence: object,
) -> tuple[str, list[Citation], list[int], float]:
    """Keep sentences whose markers resolve; merge + dedup citations; compute confidence.

    ``claim_cites``/``chunk_cites``/``link_cites`` map ref-id -> resolved ``Citation`` and
    are produced by the caller's Repository reads (with the verbatim-evidence override
    already applied to ``claim_cites``). Returns ``(answer, citations, cited_claim_ids,
    confidence)``; ``cited_claim_ids`` is **claim-only**. When nothing survives, returns the
    safe fallback with no fabricated citations.
    """
    sentences = raw_sentences if isinstance(raw_sentences, list) else []

    kept: list[str] = []
    citations: list[Citation] = []
    cited_claim_ids: list[int] = []
    seen_claim: set[int] = set()
    seen_cite: set[tuple] = set()
    for sentence in sentences:
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
    confidence = _resolve_confidence(raw_confidence, len(citations))
    return answer, citations, cited_claim_ids, confidence


def _resolve_confidence(raw_conf: object, citation_count: int) -> float:
    """Clamp the model's confidence into 0..1; fall back to a count-based estimate."""
    try:
        confidence = float(raw_conf)  # type: ignore[arg-type]
        if not math.isfinite(confidence):  # reject NaN/inf the model may emit
            raise ValueError("non-finite confidence")
        return max(0.0, min(1.0, confidence))  # clamp to the documented 0..1 range
    except (TypeError, ValueError):
        return min(0.9, 0.3 + 0.15 * citation_count)


__all__ = ["FALLBACK_ANSWER", "collect_ref_ids", "resolve_cited_sentences"]
