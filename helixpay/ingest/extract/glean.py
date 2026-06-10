"""Pure gleaning utilities for the chunk extractor (SP_018 RDD/SRP split).

Gleaning re-asks the model "these were found; what's missing?" and merges the new
items. The dedup keys and the merge step are pure data transforms with no LLM, ledger,
or I/O — lifted out of ``ChunkExtractor`` so the extractor keeps only orchestration.

Must not import ``extractor`` (would cycle): depends only on the extraction schemas.
"""

from __future__ import annotations

import json

from helixpay.ingest.extract.schemas import ClaimOut, ExtractionOut, RelationOut


def claim_key(c: ClaimOut) -> tuple[str, str, str, str]:
    # include as_of so the same value at a different date is NOT collapsed (temporal
    # distinctness — the ontology never collapses conflicting/temporally-distinct facts)
    return (
        c.subject.strip().lower(),
        c.predicate.strip().lower(),
        (c.object_value or "").strip().lower(),
        (c.as_of or "").strip(),
    )


def rel_key(r: RelationOut) -> tuple[str, str, str]:
    # link_type is not lowered: by the time a relation is keyed it has passed RelationOut
    # validation, so link_type is already one of the canonical lowercase LinkType values.
    return (r.from_entity.strip().lower(), r.to_entity.strip().lower(), r.link_type)


def dump_already(claims: list[ClaimOut], relations: list[RelationOut]) -> str:
    return json.dumps(
        {
            "claims": [
                {"subject": c.subject, "predicate": c.predicate, "object_value": c.object_value}
                for c in claims
            ],
            "relations": [
                {"from_entity": r.from_entity, "to_entity": r.to_entity, "link_type": r.link_type}
                for r in relations
            ],
        },
        ensure_ascii=False,
    )


def estimate_tokens(text: str) -> int:
    return len(text) // 4  # cheap heuristic; avoids a tokenizer dep in the unit path


def merge_new(
    claims: list[ClaimOut],
    relations: list[RelationOut],
    extra: ExtractionOut,
    seen: set[tuple[str, str, str, str]],
    seen_rel: set[tuple[str, str, str]],
) -> bool:
    """Merge ``extra``'s not-yet-seen items into ``claims``/``relations`` **in place**.

    New claims are appended first (in ``extra.claims`` order), then new relations (in
    ``extra.relations`` order); ``seen``/``seen_rel`` are mutated in place so they carry
    across gleaning passes. Returns whether anything new was added (claim OR relation).
    """
    added = False
    for c in extra.claims:
        ckey = claim_key(c)
        if ckey not in seen:
            seen.add(ckey)
            claims.append(c)
            added = True
    for r in extra.relations:
        rkey = rel_key(r)
        if rkey not in seen_rel:
            seen_rel.add(rkey)
            relations.append(r)
            added = True
    return added


__all__ = ["claim_key", "rel_key", "dump_already", "estimate_tokens", "merge_new"]
