"""Per-item coerce → strict-validate → record-loss step (SP_018 RDD/SRP split).

This is the body lifted out of ``ChunkExtractor._coerce_and_validate``: it normalises the
model's natural emissions (quarter ``as_of``, link-verb synonyms, entity-noun synonyms)
via :func:`coerce_item` before the strict Pydantic check, drops items that fail either
gate, and records every emission / coercion / drop in the ``LossLedger``.

Takes ``source_uri`` (a plain ``str``) rather than the extractor's ``ChunkContext`` so it
has no dependency back on ``extractor`` — the ledger is the only side-effecting collaborator,
and it is an in-memory accumulator, not DB/network I/O.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from helixpay.ingest.extract.coerce import coerce_item
from helixpay.ingest.extract.ledger import LossLedger

log = logging.getLogger("helixpay.ingest.extract.validate")


def validate_items(
    raw_items: list[dict],  # noqa: unparameterised dict is fine here
    schema: Any,
    kind: str,
    source_uri: str,
    ledger: LossLedger,
) -> list[Any]:
    """Coerce then strictly validate each raw item; drop and count failures."""
    out = []
    for raw_item in raw_items:
        ledger.record_emitted(source_uri)
        coerced = coerce_item(raw_item, kind=kind)
        if coerced.item is None:
            # Dropped by coercion (unmappable_enum or unparseable_as_of)
            for ck in coerced.coercions:
                ledger.record_coerced(source_uri, ck)
            ledger.record_drop(source_uri, coerced.drop_reason or "unmappable_enum")
            log.warning(
                "drop invalid %s item (coerce)",
                kind,
                extra={"source_uri": source_uri, "reason": coerced.drop_reason, "kind": kind},
            )
            continue
        # Record any successful coercions before strict validation
        for ck in coerced.coercions:
            ledger.record_coerced(source_uri, ck)
        try:
            out.append(schema.model_validate(coerced.item))
        except ValidationError as exc:
            ledger.record_drop(source_uri, "validation_error")
            log.warning(
                "drop invalid %s item",
                kind,
                extra={"source_uri": source_uri, "errors": exc.error_count(), "kind": kind},
            )
    return out


__all__ = ["validate_items"]
