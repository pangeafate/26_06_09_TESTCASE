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
  and coerces each raw item before strict validation.
- ``extract`` records all loss counters via the ledger.
- Hypothetical drops are counted via ``ledger.record_drop(..., "hypothetical")``.

SP_018 (RDD/SRP): the per-item coerce→validate→record-loss step moved to
``extract.validate.validate_items`` and the gleaning dedup/merge helpers to
``extract.glean`` (``claim_key``/``rel_key``/``dump_already``/``estimate_tokens``/
``merge_new``). ``ChunkExtractor`` keeps only orchestration (``extract``/``_glean``/
``_run_pass``) + the thin grounding penalty.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from helixpay.contracts import Chunk
from helixpay.ingest.extract.glean import (
    claim_key,
    dump_already,
    estimate_tokens,
    merge_new,
    rel_key,
)
from helixpay.ingest.extract.grounding import GRADE_UNGROUNDED, grade
from helixpay.ingest.extract.ledger import LossLedger
from helixpay.ingest.extract.llm import LLMClient, call_structured
from helixpay.ingest.extract.prompts import render
from helixpay.ingest.extract.schemas import ClaimOut, ExtractionOut, RawExtraction, RelationOut
from helixpay.ingest.extract.validate import validate_items

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
        seen = {claim_key(c) for c in claims}
        seen_rel = {rel_key(r) for r in relations}
        for _ in range(self.glean_passes):
            already = dump_already(claims, relations)
            if estimate_tokens(chunk.text + already) > self.glean_token_budget:
                log.info("glean skipped: over token budget", extra={"source_uri": ctx.source_uri, "ordinal": chunk.ordinal})
                return
            extra_out, _ = self._run_pass(_GLEAN_PROMPT, chunk, ctx, already=already)
            if extra_out is None:
                return  # bad gleaning pass — keep what we have, never discard the base pass
            if not merge_new(claims, relations, extra_out, seen, seen_rel):
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
        claims = validate_items(res.value.claims, ClaimOut, "claim", ctx.source_uri, self.ledger)
        relations = validate_items(res.value.relations, RelationOut, "relation", ctx.source_uri, self.ledger)
        return ExtractionOut(claims=claims, relations=relations), res.truncated

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
