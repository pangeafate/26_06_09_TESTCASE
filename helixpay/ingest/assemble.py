"""Pure claim/link assembly + supersession decision (SP_018 RDD/SRP split).

The domain rules lifted out of ``pipeline._ingest_document`` / ``_maybe_supersede`` so they
are unit-testable without a Repository or DB:

* :func:`build_claim` / :func:`build_link` — map a resolved extraction item (subject/entity
  ids + canonical predicate already supplied by the caller) onto a contract ``Claim`` /
  ``Link``. ``build_link`` returns ``None`` for a self-loop (the caller logs it).
* :func:`should_supersede` — the same-source temporal supersession predicate. The pipeline
  keeps the I/O (``get_claims`` / ``get_sources`` / ``supersede_claim``) and feeds the
  resolved ``prior_uri`` in.

``doc_as_of`` is the document's ``as_of`` **date** (``Document.as_of``), the fallback when an
item carries no date of its own — NOT the isoformat string used for the extraction prompt.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from helixpay.contracts import Claim, Link
from helixpay.ingest.contradict import values_conflict
from helixpay.ingest.extract.schemas import ClaimOut, RelationOut


def build_claim(
    claim_out: ClaimOut,
    *,
    subject_id: int,
    predicate: str,
    chunk_id: int,
    document_id: int,
    doc_as_of: Optional[date],
    evidence: Optional[str] = None,
    char_start: Optional[int] = None,
    char_end: Optional[int] = None,
) -> Claim:
    """Assemble a value-claim from a resolved extraction item.

    Provenance v2 (SP_011): ``evidence`` is the model's verbatim grounding span and
    ``char_start``/``char_end`` are its located offsets into the source chunk (``None`` when
    the span is a paraphrase that is not a contiguous substring — the evidence text is still
    stored). The caller computes the offsets (``grounding.locate_span``) and passes them in,
    keeping this helper a pure field-mapper.
    """
    return Claim(
        subject_entity_id=subject_id,
        predicate=predicate,
        object_value=claim_out.object_value,
        as_of=claim_out.as_of_date() or doc_as_of,
        confidence=claim_out.confidence,
        source_chunk_id=chunk_id,
        document_id=document_id,
        evidence=evidence,
        char_start=char_start,
        char_end=char_end,
    )


def build_link(
    rel: RelationOut,
    *,
    from_id: int,
    to_id: int,
    chunk_id: int,
    document_id: Optional[int] = None,
    doc_as_of: Optional[date],
) -> Optional[Link]:
    """Assemble a typed relation, or ``None`` for a self-loop.

    A self-loop (both surface forms collapsing to one entity) would corrupt the org graph
    and risk recursive-CTE cycles — the caller drops it (log-only, no counter).

    Provenance v2 (SP_011): ``document_id`` records the source document of the link so link
    contradictions carry the same provenance as claim contradictions.
    """
    if from_id == to_id:
        return None
    return Link(
        from_entity_id=from_id,
        to_entity_id=to_id,
        link_type=rel.link_type,
        raw_verb=rel.raw_verb,  # SP_025: preserved original verb for fallback `mentions` edges
        as_of=rel.as_of_date() or doc_as_of,
        confidence=rel.confidence,
        source_chunk_id=chunk_id,
        document_id=document_id,
    )


def should_supersede(
    existing: Claim,
    new_claim: Claim,
    *,
    prior_uri: Optional[str],
    source_uri: str,
) -> bool:
    """Whether ``new_claim`` supersedes the ``existing`` same-(subject,predicate) claim.

    Same-source temporal supersession: a newer claim that restates an older one from the
    *same file* with a conflicting value supersedes it (the caller sets ``valid_to`` /
    ``superseded_by``, never deletes). Cross-source disagreement is intentionally left to
    contradiction detection so a real contradiction is never collapsed.
    """
    if new_claim.as_of is None:
        return False  # supersede_claim requires a concrete valid_to date
    if existing.id is None or existing.superseded_by is not None:
        return False
    if existing.as_of is None or existing.as_of >= new_claim.as_of:
        return False  # only a strictly-older value is superseded
    if not values_conflict(existing.object_value, new_claim.object_value):
        return False  # identical value — nothing to supersede
    if prior_uri != source_uri:
        return False  # different source → that's a contradiction, not a supersession
    return True


__all__ = ["build_claim", "build_link", "should_supersede"]
