"""Planted known-answer checks (pure, evaluated over data fetched once).

These settle empirically — against the actual rows — questions that static reading of
the pipeline argues about. The three traps are the ones the corpus was seeded to test
(``eval/questions.yaml``):

* ``confluence_ga_surfaces`` — two differing ``ga_target`` claims on Project Confluence
  must be paired by a ``contradictions`` row. A failure pinpoints *which* layer broke:
  the claims not landing on the canonical ``ga_target`` key (vocab gap) vs. the claims
  existing-but-differing yet unpaired (detection gap).
* ``no_false_revenue_contradiction`` — real sources all report SGD 14.2M; a revenue
  contradiction is a false positive (the honest-oracle guard).
* ``two_marias_distinct`` — Maria Santos (CS) and Maria Silva (Sales) must stay separate
  entities (resolution must not collapse the name collision).

Traps are a data-driven list (``ALL_TRAPS``), not hard-coded forks (CLAUDE.md §18), so a
new trap is one function appended here.

CALIBRATION (SP_029): the traps encode known answers for the controlled 9-document
fixture. On the FULL corpus ``no_false_revenue_contradiction`` is INFORMATIONAL, not a
regression: real regional (SGD vs R$) / quarterly / plan-vs-actual revenue values
legitimately contradict, so the trap correctly reports that revenue contradiction rows
exist (the precision of that set is SP_028a/SP_028b's concern, not a pipeline bug). The
trap message says as much. ``confluence_ga_surfaces`` and ``two_marias_distinct`` hold on
both fixture and full corpus.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from helixpay.audit.models import TrapResult
from helixpay.ingest.normalize import values_conflict


@dataclass(frozen=True)
class TrapContext:
    """Everything the trap predicates read — fetched once, passed in (keeps traps pure).

    ``claims`` rows carry a ``canonical_predicate`` key (predicate run through the metric
    vocab) and a ``subject_name`` (the resolved entity's canonical name, or None).
    """

    claims: list[dict[str, Any]]
    contradictions: list[dict[str, Any]]
    entities: list[dict[str, Any]]


def build_vocab_map(vocab_rows: list[dict[str, Any]]) -> dict[str, str]:
    """alias/canonical (casefolded) → canonical_key, mirroring ``canonical_predicate``."""
    out: dict[str, str] = {}
    for row in vocab_rows:
        key = row["canonical_key"]
        out[key.casefold()] = key
        for alias in row.get("aliases") or []:
            out[alias.casefold()] = key
    return out


def canonicalize(predicate: Any, vocab: dict[str, str]) -> Any:
    """Return the canonical key, or the input unchanged when unknown (never raises)."""
    if not predicate:
        return predicate
    return vocab.get(predicate.casefold(), predicate)


def build_trap_context(
    *,
    claim_rows: list[dict[str, Any]],
    contradiction_rows: list[dict[str, Any]],
    entity_rows: list[dict[str, Any]],
    vocab_rows: list[dict[str, Any]],
) -> TrapContext:
    vocab = build_vocab_map(vocab_rows)
    claims: list[dict[str, Any]] = []
    for row in claim_rows:
        c = dict(row)
        c["canonical_predicate"] = canonicalize(row.get("predicate"), vocab)
        claims.append(c)
    return TrapContext(
        claims=claims,
        contradictions=[dict(r) for r in contradiction_rows],
        entities=[dict(r) for r in entity_rows],
    )


def _subject_claims(
    ctx: TrapContext, name_substr: str, canonical_predicate: str
) -> list[dict[str, Any]]:
    needle = name_substr.casefold()
    return [
        c
        for c in ctx.claims
        if c.get("subject_name")
        and needle in c["subject_name"].casefold()
        and c.get("canonical_predicate") == canonical_predicate
        and c.get("superseded_by") is None
    ]


def trap_confluence_ga(ctx: TrapContext) -> TrapResult:
    name = "confluence_ga_surfaces"
    claims = _subject_claims(ctx, "Confluence", "ga_target")
    values = {c["object_value"] for c in claims if c["object_value"] is not None}
    if len(claims) < 2:
        return TrapResult(
            name,
            False,
            f"expected >=2 ga_target claims on Confluence, found {len(claims)} — VOCAB "
            "gap: GA-date predicates not canonicalizing to 'ga_target'?",
        )
    differs = any(values_conflict(a, b) for a in values for b in values if a != b)
    if not differs:
        return TrapResult(
            name,
            False,
            f"{len(claims)} ga_target claims but values agree ({sorted(values)}) — the "
            "planted disagreement didn't land as distinct values",
        )
    claim_ids = {c["id"] for c in claims}
    paired = any(
        row.get("claim_a_id") in claim_ids and row.get("claim_b_id") in claim_ids
        for row in ctx.contradictions
    )
    if paired:
        return TrapResult(
            name,
            True,
            f"a contradiction row pairs two differing ga_target claims (values={sorted(values)})",
        )
    return TrapResult(
        name,
        False,
        f"{len(claims)} differing ga_target claims exist (values={sorted(values)}) but NO "
        "contradiction row pairs them — DETECTION gap (windows_overlap / _TARGET_PREDICATES)",
    )


def trap_no_false_revenue_contradiction(ctx: TrapContext) -> TrapResult:
    name = "no_false_revenue_contradiction"
    claims = _subject_claims(ctx, "HelixPay", "revenue")
    values = sorted(
        {c["object_value"] for c in claims if c["object_value"] is not None}
    )
    revenue_contras = [r for r in ctx.contradictions if r.get("predicate") == "revenue"]
    if revenue_contras:
        return TrapResult(
            name,
            False,
            f"a revenue contradiction row exists (claim values seen={values}) — on real "
            "data all sources report SGD 14.2M, so this is a FALSE POSITIVE (or the gate "
            "fixture was seeded with_fixture=True; audit a real-ingest DB)",
        )
    return TrapResult(
        name,
        True,
        f"no revenue contradiction; {len(claims)} revenue claim(s), values={values}",
    )


def trap_two_marias_distinct(ctx: TrapContext) -> TrapResult:
    name = "two_marias_distinct"
    marias = [
        e
        for e in ctx.entities
        if e.get("entity_type") == "person"
        and (e.get("canonical_name") or "").casefold().startswith("maria ")
    ]
    ids = {e["id"] for e in marias}
    if len(ids) >= 2:
        names = sorted(e["canonical_name"] for e in marias)
        return TrapResult(
            name, True, f"{len(ids)} distinct Maria entities kept separate: {names}"
        )
    return TrapResult(
        name,
        False,
        f"expected >=2 distinct 'Maria *' person entities, found {len(ids)} — the "
        "name-collision roster is missing or was collapsed",
    )


ALL_TRAPS: tuple[Callable[[TrapContext], TrapResult], ...] = (
    trap_confluence_ga,
    trap_no_false_revenue_contradiction,
    trap_two_marias_distinct,
)


def run_traps(ctx: TrapContext) -> list[TrapResult]:
    return [trap(ctx) for trap in ALL_TRAPS]


__all__ = [
    "TrapContext",
    "build_vocab_map",
    "canonicalize",
    "build_trap_context",
    "run_traps",
    "ALL_TRAPS",
    "trap_confluence_ga",
    "trap_no_false_revenue_contradiction",
    "trap_two_marias_distinct",
]
