"""Per-chunk extraction: render the named prompt, call the LLM under the structured-output
repair loop, then coerce + validate each candidate item against the strict contract schemas
and drop the ones that don't fit (the rest survive).

Two research-validated quality steps wrap the base extraction:

* **Gleaning** (recall) — an optional fixed number of follow-up passes that feed the
  already-extracted items back to the model ("these were found; what's missing?") and merge
  the new ones (deduped). Off by default (``glean_passes=0``); production ingest sets 1.
  Guarded by a token budget; a gleaning pass that fails or finds nothing stops the loop and
  never discards the first pass.
* **Evidence grounding** (precision/faithfulness) — each kept claim is graded against its
  cited evidence span; an ungrounded claim (no evidence, or a value not restorable from it)
  is **flagged via a confidence penalty**, never dropped (dropping would cost recall on the
  dashboard facts whose value/label/as-of live in separate spans).

Hypothetical/counterfactual values are dropped so they never become competing facts.

SP_014 changes:
- ``ChunkExtractor.__init__`` gains an optional ``ledger: LossLedger`` parameter (default:
  fresh LossLedger per instance).
- ``_run_pass`` now returns ``tuple[Optional[ExtractionOut], bool]`` = (out, truncated)
  and calls ``coerce_item`` on each raw item before strict validation (replaces the old
  ``_validate_items`` which did not coerce).
- ``extract`` records all loss counters via the ledger.
- Hypothetical drops are counted via ``ledger.record_drop(..., "hypothetical")``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional, Type

from pydantic import ValidationError

from helixpay.contracts import Chunk
from helixpay.ingest.extract.coerce import coerce_item
from helixpay.ingest.extract.grounding import GRADE_UNGROUNDED, grade
from helixpay.ingest.extract.ledger import LossLedger
from helixpay.ingest.extract.llm import LLMClient, call_structured
from helixpay.ingest.extract.prompts import render
from helixpay.ingest.extract.schemas import ClaimOut, ExtractionOut, RawExtraction, RelationOut

log = logging.getLogger("helixpay.ingest.extract.extractor")

_PROMPT_NAME = "extract_claims"
_GLEAN_PROMPT = "glean_claims"
_SYSTEM = (
    "You are a precise information-extraction engine for an ontology over a B2B payments "
    "company's documents. Follow the instructions exactly and reply with only the requested "
    "JSON. Never invent facts not present in the provided span."
)
_DEFAULT_GLEAN_TOKEN_BUDGET = 20_000
_UNGROUNDED_PENALTY = 0.5
_MIN_CONFIDENCE = 0.1


@dataclass(frozen=True)
class ChunkContext:
    """Per-chunk extraction context derived from the owning document."""

    source_type: str
    source_uri: str
    as_of: Optional[str] = None
    roster_hint: str = ""


class ChunkExtractor:
    """Turns one ``Chunk`` into validated, grounded candidate claims + relations."""

    def __init__(
        self,
        client: LLMClient,
        *,
        prompt_name: str = _PROMPT_NAME,
        system: str = _SYSTEM,
        repair: bool = True,
        glean_passes: int = 0,
        glean_token_budget: int = _DEFAULT_GLEAN_TOKEN_BUDGET,
        ledger: Optional[LossLedger] = None,
    ) -> None:
        if glean_passes < 0:
            raise ValueError("glean_passes must be >= 0")
        self.client = client
        self.prompt_name = prompt_name
        self.system = system
        self.repair = repair
        self.glean_passes = glean_passes
        self.glean_token_budget = glean_token_budget
        self.ledger: LossLedger = ledger if ledger is not None else LossLedger()

    def extract(self, chunk: Chunk, ctx: ChunkContext) -> ExtractionOut:
        self.ledger.record_chunk(ctx.source_uri)

        base, truncated = self._run_pass(self.prompt_name, chunk, ctx, already=None)
        if base is None:
            self.ledger.record_empty(ctx.source_uri)
            log.warning(
                "extraction empty (undecodable after repair)",
                extra={
                    "source_uri": ctx.source_uri,
                    "ordinal": chunk.ordinal,
                    "truncated": truncated,
                },
            )
            return ExtractionOut()
        claims, relations = list(base.claims), list(base.relations)

        self._glean(chunk, ctx, claims, relations)

        kept = []
        for c in claims:
            if c.hypothetical:
                self.ledger.record_drop(ctx.source_uri, "hypothetical")
            else:
                kept.append(c)
        dropped_hypo = len(claims) - len(kept)
        if dropped_hypo:
            log.info(
                "dropped hypothetical claims",
                extra={"source_uri": ctx.source_uri, "ordinal": chunk.ordinal, "count": dropped_hypo},
            )
        grounded = [self._apply_grounding(c, chunk.text, ctx) for c in kept]
        log.info(
            "chunk extracted",
            extra={
                "source_uri": ctx.source_uri,
                "ordinal": chunk.ordinal,
                "claims": len(grounded),
                "relations": len(relations),
                "glean_passes": self.glean_passes,
            },
        )
        return ExtractionOut(claims=grounded, relations=relations)

    # ------------------------------------------------------------------ #
    # gleaning
    # ------------------------------------------------------------------ #
    def _glean(self, chunk: Chunk, ctx: ChunkContext, claims: list[ClaimOut], relations: list[RelationOut]) -> None:
        if self.glean_passes <= 0:
            return
        seen = {self._claim_key(c) for c in claims}
        seen_rel = {self._rel_key(r) for r in relations}
        for _ in range(self.glean_passes):
            already = self._dump_already(claims, relations)
            if self._estimate_tokens(chunk.text + already) > self.glean_token_budget:
                log.info("glean skipped: over token budget", extra={"source_uri": ctx.source_uri, "ordinal": chunk.ordinal})
                return
            extra_out, _ = self._run_pass(_GLEAN_PROMPT, chunk, ctx, already=already)
            if extra_out is None:
                return  # bad gleaning pass — keep what we have, never discard the base pass
            added = False
            for c in extra_out.claims:
                ckey = self._claim_key(c)
                if ckey not in seen:
                    seen.add(ckey)
                    claims.append(c)
                    added = True
            for r in extra_out.relations:
                rkey = self._rel_key(r)
                if rkey not in seen_rel:
                    seen_rel.add(rkey)
                    relations.append(r)
                    added = True
            if not added:
                return  # early stop: a pass that found nothing new means we're done

    def _run_pass(
        self, prompt_name: str, chunk: Chunk, ctx: ChunkContext, *, already: Optional[str]
    ) -> tuple[Optional[ExtractionOut], bool]:
        """Render + call + coerce + per-item validate one pass.

        Returns ``(ExtractionOut, truncated)`` where truncated reflects whether the LLM
        call hit max_tokens.  Returns ``(None, truncated)`` if the model output was
        undecodable even after repair.
        """
        kwargs = dict(
            source_type=ctx.source_type,
            source_uri=ctx.source_uri,
            as_of=ctx.as_of or "unknown",
            roster_hint=ctx.roster_hint or "(none provided)",
            chunk_text=chunk.text,
        )
        if already is not None:
            kwargs["already_extracted"] = already
        user = render(prompt_name, **kwargs)
        res = call_structured(
            self.client, prompt_name=prompt_name, system=self.system, user=user,
            schema=RawExtraction, repair=self.repair,
        )
        if res.truncated:
            self.ledger.record_truncated(ctx.source_uri)
        if res.value is None:
            return None, res.truncated
        claims = self._coerce_and_validate(res.value.claims, ClaimOut, "claim", ctx)
        relations = self._coerce_and_validate(res.value.relations, RelationOut, "relation", ctx)
        return ExtractionOut(claims=claims, relations=relations), res.truncated

    def _coerce_and_validate(
        self,
        raw_items: list[dict],  # noqa: unparameterised dict is fine here
        schema: Any,
        kind: str,
        ctx: ChunkContext,
    ) -> list[Any]:
        """Coerce then strictly validate each raw item; drop and count failures.

        Replaces the old ``_validate_items`` with a coerce-before-validate step that
        normalises the model's natural emissions (quarter as_of, link verb synonyms, entity
        noun synonyms) before the strict Pydantic check.
        """
        out = []
        for raw_item in raw_items:
            self.ledger.record_emitted(ctx.source_uri)
            coerced = coerce_item(raw_item, kind=kind)
            if coerced.item is None:
                # Dropped by coercion (unmappable_enum or unparseable_as_of)
                for ck in coerced.coercions:
                    self.ledger.record_coerced(ctx.source_uri, ck)
                self.ledger.record_drop(ctx.source_uri, coerced.drop_reason or "unmappable_enum")
                log.warning(
                    "drop invalid %s item (coerce)",
                    kind,
                    extra={"source_uri": ctx.source_uri, "reason": coerced.drop_reason, "kind": kind},
                )
                continue
            # Record any successful coercions before strict validation
            for ck in coerced.coercions:
                self.ledger.record_coerced(ctx.source_uri, ck)
            try:
                out.append(schema.model_validate(coerced.item))
            except ValidationError as exc:
                self.ledger.record_drop(ctx.source_uri, "validation_error")
                log.warning(
                    "drop invalid %s item",
                    kind,
                    extra={"source_uri": ctx.source_uri, "errors": exc.error_count(), "kind": kind},
                )
        return out

    @staticmethod
    def _claim_key(c: ClaimOut) -> tuple[str, str, str, str]:
        # include as_of so the same value at a different date is NOT collapsed (temporal
        # distinctness — the ontology never collapses conflicting/temporally-distinct facts)
        return (
            c.subject.strip().lower(),
            c.predicate.strip().lower(),
            (c.object_value or "").strip().lower(),
            (c.as_of or "").strip(),
        )

    @staticmethod
    def _rel_key(r: RelationOut) -> tuple[str, str, str]:
        return (r.from_entity.strip().lower(), r.to_entity.strip().lower(), r.link_type)

    @staticmethod
    def _dump_already(claims: list[ClaimOut], relations: list[RelationOut]) -> str:
        return json.dumps(
            {
                "claims": [{"subject": c.subject, "predicate": c.predicate, "object_value": c.object_value} for c in claims],
                "relations": [{"from_entity": r.from_entity, "to_entity": r.to_entity, "link_type": r.link_type} for r in relations],
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return len(text) // 4  # cheap heuristic; avoids a tokenizer dep in the unit path

    # ------------------------------------------------------------------ #
    # grounding
    # ------------------------------------------------------------------ #
    def _apply_grounding(self, claim: ClaimOut, chunk_text: str, ctx: ChunkContext) -> ClaimOut:
        if grade(claim, chunk_text) != GRADE_UNGROUNDED:
            return claim
        penalized = max(_MIN_CONFIDENCE, claim.confidence * _UNGROUNDED_PENALTY)
        log.info(
            "ungrounded claim penalized",
            extra={"source_uri": ctx.source_uri, "subject": claim.subject, "predicate": claim.predicate},
        )
        return claim.model_copy(update={"confidence": penalized})


__all__ = ["ChunkExtractor", "ChunkContext"]
