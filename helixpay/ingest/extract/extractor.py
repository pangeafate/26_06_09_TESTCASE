"""Per-chunk extraction: render the named prompt, call the LLM under the structured-output
repair loop, then validate each candidate item against the strict contract schemas and drop
the ones that don't fit (the rest survive). Hypothetical/counterfactual values are dropped
here so they never become competing facts (Stage-3 H1).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from pydantic import ValidationError

from helixpay.contracts import Chunk
from helixpay.ingest.extract.llm import LLMClient, call_structured
from helixpay.ingest.extract.prompts import render
from helixpay.ingest.extract.schemas import ClaimOut, ExtractionOut, RawExtraction, RelationOut

log = logging.getLogger("helixpay.ingest.extract.extractor")

_PROMPT_NAME = "extract_claims"
_SYSTEM = (
    "You are a precise information-extraction engine for an ontology over a B2B payments "
    "company's documents. Follow the instructions exactly and reply with only the requested "
    "JSON. Never invent facts not present in the provided span."
)


@dataclass(frozen=True)
class ChunkContext:
    """Per-chunk extraction context derived from the owning document."""

    source_type: str
    source_uri: str
    as_of: Optional[str] = None
    roster_hint: str = ""


class ChunkExtractor:
    """Turns one ``Chunk`` into validated candidate claims + relations."""

    def __init__(
        self,
        client: LLMClient,
        *,
        prompt_name: str = _PROMPT_NAME,
        system: str = _SYSTEM,
        repair: bool = True,
    ) -> None:
        self.client = client
        self.prompt_name = prompt_name
        self.system = system
        self.repair = repair

    def extract(self, chunk: Chunk, ctx: ChunkContext) -> ExtractionOut:
        user = render(
            self.prompt_name,
            source_type=ctx.source_type,
            source_uri=ctx.source_uri,
            as_of=ctx.as_of or "unknown",
            roster_hint=ctx.roster_hint or "(none provided)",
            chunk_text=chunk.text,
        )
        raw = call_structured(
            self.client,
            prompt_name=self.prompt_name,
            system=self.system,
            user=user,
            schema=RawExtraction,
            repair=self.repair,
        )
        if raw is None:
            # call_structured already logged the drop; an undecodable chunk yields nothing.
            return ExtractionOut()

        claims = self._validate_items(raw.claims, ClaimOut, ctx.source_uri, "claim")
        relations = self._validate_items(raw.relations, RelationOut, ctx.source_uri, "relation")

        kept_claims = [c for c in claims if not c.hypothetical]
        dropped_hypo = len(claims) - len(kept_claims)
        if dropped_hypo:
            log.info(
                "dropped hypothetical claims",
                extra={"source_uri": ctx.source_uri, "ordinal": chunk.ordinal, "count": dropped_hypo},
            )
        log.info(
            "chunk extracted",
            extra={
                "source_uri": ctx.source_uri,
                "ordinal": chunk.ordinal,
                "claims": len(kept_claims),
                "relations": len(relations),
            },
        )
        return ExtractionOut(claims=kept_claims, relations=relations)

    @staticmethod
    def _validate_items(items, schema, source_uri: str, kind: str):
        out = []
        for raw_item in items:
            try:
                out.append(schema.model_validate(raw_item))
            except ValidationError as exc:
                log.warning(
                    "drop invalid %s item",
                    kind,
                    extra={"source_uri": source_uri, "errors": exc.error_count(), "kind": kind},
                )
        return out


__all__ = ["ChunkExtractor", "ChunkContext"]
