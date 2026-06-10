"""Two-level eval harness (HELIXPAY_BUILD_SPEC.md §8) — the author-independent grader.

Level 1 — extraction check: after ingest, assert every golden fact exists as a
claim/link in the Repository with the right ``source_uri`` + ``as_of``; report
recall + golden-set precision with a per-fact FOUND/MISMATCH/MISSING verdict.

Level 2 — answer check: run each deep question through ``QueryEngine.ask()`` and
evaluate its ``checks`` against the returned ``AnswerBundle``; report per-question
pass/fail + latency, and whether >=1 answer surfaced a real contradiction.

The harness codes ONLY against ``helixpay.contracts`` (the frozen Protocols). The
concrete ``Repository`` and ``QueryEngine`` are resolved lazily at run time, so this
module imports no build slice and stays an honest oracle. Wire into ``make test`` /
``make demo`` as ``python -m eval.run``.

Exit codes:
    0  /goal met: recall >= bar, all gating answer checks pass, >=1 contradiction
    1  /goal NOT met (a blocker is printed)
    2  could not run (no engine/repo available, bad YAML)
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Optional, Protocol

import yaml  # type: ignore[import-untyped]

from helixpay.contracts import AnswerBundle, Claim, Link, QueryEngine, Repository

# SP_013 — DECLARED, by-design coupling (pre-impl review H1): the matcher's numeric
# value-equality reuses the SHARED normalizer (helixpay.ingest.normalize.values_equal)
# so predicted-vs-gold equivalence cannot drift from contradiction detection. Its own
# docstring names "the eval matcher (predicted-vs-gold equivalence — SP_013)" as an
# intended consumer, so it is shared substrate, not a build slice. The oracle keeps an
# INDEPENDENT equality assertion (eval-owned golden pairs in test_rigor.py) so a
# normalizer regression is still caught by the grader's own tests — see eval/README.md.
from helixpay.ingest.normalize import normalize_value as _shared_normalize, values_equal

from eval.models import (
    GATING_CHECKS,
    AnswerResult,
    CheckResult,
    CollisionVerdict,
    ContradictionClass,
    ContradictionVerdict,
    EntityCollision,
    ExtractionReport,
    FactVerdict,
    GoalVerdict,
    GoldenContradiction,
    GoldenFact,
    GoldenSet,
    PredicateSynonym,
    Question,
    Verdict,
    wilson_interval,
)

log = logging.getLogger("helixpay.eval")

_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GOLDEN = _ROOT / "test" / "golden" / "facts.yaml"
DEFAULT_QUESTIONS = _ROOT / "eval" / "questions.yaml"
DEFAULT_RECALL_BAR = 0.80  # stated in eval/README.md; the /goal recall floor.


# --------------------------------------------------------------------------- #
# Loading                                                                     #
# --------------------------------------------------------------------------- #
def _assert_unique_ids(ids: list[str], what: str) -> None:
    seen: set[str] = set()
    dups: set[str] = set()
    for i in ids:
        (dups if i in seen else seen).add(i)
    if dups:
        raise ValueError(f"duplicate {what} id(s): {sorted(dups)}")


def load_golden(path: Path = DEFAULT_GOLDEN) -> GoldenSet:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    facts = [GoldenFact.model_validate(f) for f in raw.get("facts", [])]
    cons = [GoldenContradiction.model_validate(c) for c in raw.get("contradictions", [])]
    syns = [PredicateSynonym.model_validate(s) for s in raw.get("predicate_synonyms", [])]
    cols = [EntityCollision.model_validate(c) for c in raw.get("entity_collisions", [])]
    _assert_unique_ids([f.id for f in facts], "golden fact")  # a dup id would mask a fact
    _assert_unique_ids([s.id for s in syns], "predicate synonym")
    _assert_unique_ids([c.id for c in cols], "entity collision")
    # A contradiction's claim_a/claim_b must reference REAL golden fact ids — a dangling
    # ref is a silently-broken oracle (the contradiction points at nothing). (Review MEDIUM)
    fact_ids = {f.id for f in facts}
    for c in cons:
        for side in (c.claim_a, c.claim_b):
            if side is not None and side not in fact_ids:
                raise ValueError(f"contradiction '{c.id}' references unknown fact id '{side}'")
    return GoldenSet(
        facts=facts,
        contradictions=cons,
        predicate_synonyms=syns,
        entity_collisions=cols,
    )


def load_questions(path: Path = DEFAULT_QUESTIONS) -> list[Question]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    questions = [Question.model_validate(q) for q in raw.get("questions", [])]
    _assert_unique_ids([q.id for q in questions], "question")
    return questions


# --------------------------------------------------------------------------- #
# The match function (SP_013 — research P0 #4: specify it, don't leave it implicit)
#
#   A golden fact MATCHES a claim/link iff ALL of:
#     subject     resolved ``entity_id`` equal (Repository.resolve_entity with the
#                 fact's source_uri as context — _check_claim_fact / _check_link_fact)
#     predicate   canonical_predicate(fact) == canonical_predicate(claim)
#     value       _values_match: numeric equality via the SHARED normalizer
#                 (helixpay.ingest.normalize.values_equal — currency/magnitude/word-
#                 number aware), with a documented substring fallback for free TEXT
#                 (dates/labels the numeric path can't compare, e.g. "end of Q3 2026")
#     source_uri  _uri_matches: same basename, or golden is a substring of the claim's
#     as_of       _as_of_matches: EXACT, within ±AS_OF_TOLERANCE_DAYS, or carried by the
#                 claim's source citation (a dashboard exported 04-21 may stamp either
#                 the export date or the Q1 period end) — documented in eval/README.md
# --------------------------------------------------------------------------- #
AS_OF_TOLERANCE_DAYS = 0  # exact by default (research §B: EM is the honest metric)


def normalize_value(s: Optional[str]) -> str:
    """Lowercase, strip currency/symbols/punctuation and collapse whitespace so
    ``"SGD 14.2M"`` matches ``"14.2m"`` and ``"$14.2 million"``. Used for the TEXT
    substring fallback + URI matching; numeric value-equality goes through the shared
    ``values_equal`` (see ``_values_match``)."""
    if s is None:
        return ""
    out = s.lower()
    for token in ("sgd", "brl", "r$", "$", "≈", "~", "approximately", "about"):
        out = out.replace(token, " ")
    out = out.replace("million", "m").replace(",", "")
    out = "".join(ch if ch.isalnum() or ch in ". " else " " for ch in out)
    out = " ".join(out.split())
    # collapse "14.2 m"/"22.0 k" → "14.2m" so spaced magnitudes match compact ones
    return re.sub(r"(\d(?:\.\d+)?)\s+(m|k|b)\b", r"\1\2", out)


def _values_match(golden: str, claimed: Optional[str]) -> bool:
    """Two-tier (pre-impl review C1): the SHARED ``values_equal`` first — numerically
    close when both sides are pure numbers (so "SGD 14.2M" == "$14.2 million" and
    "−2.1M" == "-2.1M"), else canonical-text equal. Then a documented substring fallback
    on the local text normalization, so free-text dates/labels the numeric path can't
    compare ("end of Q3 2026" inside a sentence) still match."""
    if claimed is None:
        return False
    if values_equal(golden, claimed):
        return True
    # Post-impl review H1: when BOTH sides are pure numbers, ``values_equal`` already gave
    # the definitive answer (False) — do NOT fall through to substring, or "41" would match
    # "241" and "412" would match "4120", silently inflating numeric recall. (One numeric +
    # one text side still uses the fallback, so "−SGD 2.1M" vs the parseable "-2.1M" — which
    # the shared parser can't read as a number because of the currency between sign and
    # digits — still matches on text.)
    if _shared_normalize(golden)[1] is not None and _shared_normalize(claimed)[1] is not None:
        return False
    g, c = normalize_value(golden), normalize_value(claimed)
    if not g or not c:
        return False
    return g in c or c in g


def _uri_matches(golden_uri: str, claimed_uri: Optional[str]) -> bool:
    if not claimed_uri:
        return False
    return Path(golden_uri).name.lower() == Path(claimed_uri).name.lower() or (
        golden_uri.lower() in claimed_uri.lower()
    )


def _as_of_matches(
    golden_as_of: Optional[date],
    claim_as_of: Optional[date],
    source_as_ofs: list[Optional[date]],
) -> bool:
    """EXACT (or within ±AS_OF_TOLERANCE_DAYS) against the claim's own ``as_of`` OR any
    of its source-citation dates. A golden fact with no ``as_of`` does not constrain."""
    if golden_as_of is None:
        return True
    candidates = [claim_as_of, *source_as_ofs]
    tol = timedelta(days=AS_OF_TOLERANCE_DAYS)
    return any(d is not None and abs(d - golden_as_of) <= tol for d in candidates)


# --------------------------------------------------------------------------- #
# Level 1 — extraction check                                                  #
# --------------------------------------------------------------------------- #
def _check_claim_fact(repo: Repository, fact: GoldenFact) -> FactVerdict:
    pred = repo.canonical_predicate(fact.predicate)  # the macro-recall grouping key
    entity = repo.resolve_entity(fact.subject, context={"source_uri": fact.source_uri})
    if entity is None or entity.id is None:
        return FactVerdict(fact.id, Verdict.missing, f"subject '{fact.subject}' unresolved", predicate=pred)
    claims: list[Claim] = repo.get_claims(entity.id, pred)
    if not claims:  # fall back to all claims, filter by canonicalized predicate
        claims = [c for c in repo.get_claims(entity.id) if repo.canonical_predicate(c.predicate) == pred]
    if not claims:
        return FactVerdict(fact.id, Verdict.missing, f"no claim on ({fact.subject}, {pred})", predicate=pred)

    best = Verdict.missing
    detail = "claim(s) exist but value/source/as_of differ"
    for c in claims:
        if not _values_match(fact.value, c.object_value):
            best = _best_verdict(best, Verdict.mismatch)
            continue
        sources = repo.get_sources([c.id]) if c.id is not None else []
        src_ok = any(_uri_matches(fact.source_uri, s.source_uri) for s in sources)
        if not src_ok:
            best = _best_verdict(best, Verdict.mismatch)
            detail = "right value, wrong/absent source"
            continue
        if _as_of_matches(fact.as_of, c.as_of, [s.as_of for s in sources]):
            return FactVerdict(fact.id, Verdict.found, "", predicate=pred)
        best = _best_verdict(best, Verdict.mismatch)
        detail = f"right value+source, as_of {c.as_of} != {fact.as_of}"
    return FactVerdict(fact.id, best, detail, predicate=pred)


def _check_link_fact(repo: Repository, fact: GoldenFact) -> FactVerdict:
    link_type = fact.link_type or fact.predicate
    from_name, to_name = fact.from_ or fact.subject, fact.to or fact.value
    fe = repo.resolve_entity(from_name, context={"source_uri": fact.source_uri})
    te = repo.resolve_entity(to_name, context={"source_uri": fact.source_uri})
    if fe is None or te is None or fe.id is None or te.id is None:
        unresolved = from_name if (fe is None or fe.id is None) else to_name
        return FactVerdict(fact.id, Verdict.missing, f"endpoint '{unresolved}' unresolved", predicate=link_type)
    links: list[Link] = repo.get_links(link_type)
    for link in links:
        if link.from_entity_id == fe.id and link.to_entity_id == te.id:
            return FactVerdict(fact.id, Verdict.found, "", predicate=link_type)
    for link in links:  # reversed direction → a real but mis-directed extraction
        if link.from_entity_id == te.id and link.to_entity_id == fe.id:
            return FactVerdict(fact.id, Verdict.mismatch, f"{link_type} present but reversed", predicate=link_type)
    return FactVerdict(fact.id, Verdict.missing, f"no {link_type} {from_name}->{to_name}", predicate=link_type)


def _best_verdict(a: Verdict, b: Verdict) -> Verdict:
    """Return the more-favorable verdict (FOUND > MISMATCH > MISSING) — used to keep the
    best outcome across the several claims that may sit on one (subject, predicate)."""
    order = {Verdict.missing: 0, Verdict.mismatch: 1, Verdict.found: 2}
    return a if order[a] >= order[b] else b


def check_extraction(repo: Repository, golden: GoldenSet) -> ExtractionReport:
    """Assert every recall-bar golden fact exists in the Repository."""
    report = ExtractionReport()
    for fact in golden.bar_facts:
        if fact.kind.value == "link":
            report.verdicts.append(_check_link_fact(repo, fact))
        else:
            report.verdicts.append(_check_claim_fact(repo, fact))
    return report


# --------------------------------------------------------------------------- #
# Level 2 — answer check                                                      #
# --------------------------------------------------------------------------- #
def _distinct_sources(bundle: AnswerBundle) -> set[str]:
    return {c.source_uri for c in bundle.citations if c.source_uri}


def evaluate_check(name: str, bundle: AnswerBundle) -> bool:
    """Evaluate one answer check against the bundle. Rules are intentionally concrete
    (operate on citations / contradictions / as_of_coverage) so a check cannot be a
    silent free pass — see eval/README.md for the rationale of each."""
    cites_as_of = [c for c in bundle.citations if c.as_of is not None]
    distinct = _distinct_sources(bundle)
    if name == "cites_source":
        return any(c.source_uri for c in bundle.citations)
    if name == "states_as_of":
        return len(cites_as_of) > 0
    if name == "resolves_hierarchy":
        return any("org-chart" in (c.source_uri or "").lower() for c in bundle.citations)
    if name == "uses_freshest_as_of":
        # Freshness must at least be visible: an as_of is carried, and when several
        # dates coexist the coverage map records them (so staleness can be reasoned).
        if not cites_as_of:
            return False
        distinct_dates = {c.as_of for c in cites_as_of}
        return len(distinct_dates) <= 1 or bool(bundle.as_of_coverage)
    if name == "surfaces_contradiction":
        return len(bundle.contradictions) > 0
    if name == "attributes_each_side":
        return len(bundle.contradictions) > 0 and len(distinct) >= 2
    if name in ("cross_document_synthesis", "cites_multiple_sources"):
        return len(distinct) >= 2
    if name == "entity_resolution":
        return len(bundle.citations) >= 1
    if name == "alias_handling":  # soft — reported only
        return len(bundle.citations) >= 1
    if name == "no_false_contradiction":
        return len(bundle.contradictions) == 0
    raise ValueError(f"unknown check: {name}")


def check_answers(
    engine: QueryEngine,
    questions: list[Question],
    bundles_out: Optional[dict[str, AnswerBundle]] = None,
) -> list[AnswerResult]:
    """Grade each question's checks against its ``ask()`` bundle. If ``bundles_out`` is
    given it is populated ``{question_id: bundle}`` so the caller can score contradictions
    off the SAME ask() (no second LLM call)."""
    results: list[AnswerResult] = []
    for q in questions:
        started = time.monotonic()
        try:
            bundle = engine.ask(q.q)
        except Exception as exc:  # an engine error is a per-question failure, not a crash
            results.append(AnswerResult(q.id, error=f"{type(exc).__name__}: {exc}"))
            log.warning("ask() failed for %s: %s", q.id, exc)
            continue
        latency = time.monotonic() - started
        if bundles_out is not None:
            bundles_out[q.id] = bundle
        checks = [
            CheckResult(name=name, passed=evaluate_check(name, bundle), gating=name in GATING_CHECKS)
            for name in q.checks
        ]
        results.append(
            AnswerResult(
                question_id=q.id,
                checks=checks,
                latency_s=latency,
                surfaced_contradiction=len(bundle.contradictions) > 0,
            )
        )
    return results


# --------------------------------------------------------------------------- #
# WikiContradict 3-class scoring (research P1 #5) — Correct/Partial/Incorrect  #
# --------------------------------------------------------------------------- #
def _canon_pred(p: Optional[str]) -> str:
    return (p or "").strip().lower()


def score_contradiction(
    golden: GoldenContradiction,
    bundle: AnswerBundle,
    subject_entity_id: Optional[int] = None,
) -> ContradictionVerdict:
    """Score how an answer handled a planted contradiction (research P1 #5):

    * CORRECT   — a contradiction on the right SUBJECT+predicate is surfaced AND it
                  references BOTH claim ids (neither side silently dropped).
    * PARTIAL   — surfaced on the right subject+predicate but only one side carries a
                  claim id (or both ids are the same → not two sides).
    * INCORRECT — no matching contradiction is surfaced → silent merge.

    The both-id assertion is the pre-impl-review C2 resolution: ``Contradiction`` already
    carries ``claim_a_id``/``claim_b_id`` (ints), so "both ids present" = both non-null
    AND distinct — no golden-slug→DB-id mapping and no contract change.

    ``subject_entity_id`` (post-impl review): when the caller has resolved the golden
    subject, a surfaced contradiction must ALSO be on that entity — otherwise a spurious
    conflict on the WRONG subject but right predicate would over-credit. When ``None``
    (no resolver / unresolved subject) the match falls back to predicate-only.

    Review H1 — the subject and both-id axes are kept SEPARATE. CORRECT requires a
    *subject-confirmed* row (subject equal, or no resolved golden subject to check
    against) carrying both distinct ids. A row that omits ``subject_entity_id`` cannot
    be confirmed against a resolved golden subject, so even with both ids it caps at
    PARTIAL — an unannotated row must not earn full credit by default."""
    want = _canon_pred(golden.predicate)
    pred_matches = [c for c in bundle.contradictions if _canon_pred(c.predicate) == want]

    def _has_both(rows: list) -> bool:
        return any(
            c.claim_a_id is not None and c.claim_b_id is not None and c.claim_a_id != c.claim_b_id
            for c in rows
        )

    if subject_entity_id is None:
        # No resolved golden subject to check against → predicate-only grading.
        if not pred_matches:
            return ContradictionVerdict(
                golden.id, ContradictionClass.incorrect, False,
                "no contradiction surfaced on the predicate (silent merge)",
            )
        if _has_both(pred_matches):
            return ContradictionVerdict(golden.id, ContradictionClass.correct, True, "both claim ids present")
        return ContradictionVerdict(
            golden.id, ContradictionClass.partial, False,
            "surfaced but only one side carries a distinct claim id",
        )

    # Subject resolved → split the rows by whether they confirm the subject.
    confirmed = [c for c in pred_matches if c.subject_entity_id == subject_entity_id]
    unannotated = [c for c in pred_matches if c.subject_entity_id is None]
    # rows with a DIFFERENT subject_entity_id are the wrong entity → ignored entirely.
    if not confirmed and not unannotated:
        return ContradictionVerdict(
            golden.id, ContradictionClass.incorrect, False,
            "no contradiction surfaced on the subject+predicate (silent merge / wrong subject)",
        )
    if _has_both(confirmed):  # only a SUBJECT-CONFIRMED both-id row earns CORRECT
        return ContradictionVerdict(golden.id, ContradictionClass.correct, True, "both claim ids present on the resolved subject")
    if confirmed:
        return ContradictionVerdict(
            golden.id, ContradictionClass.partial, False,
            "surfaced on the subject but only one side carries a distinct claim id",
        )
    return ContradictionVerdict(  # unannotated only — can't confirm subject (H1)
        golden.id, ContradictionClass.partial, False,
        "surfaced on the predicate but the row omits a subject — cannot confirm it is the right entity",
    )


def score_contradictions(
    golden: GoldenSet,
    questions: list[Question],
    bundles: dict[str, AnswerBundle],
    repo: Optional[Repository] = None,
) -> list[ContradictionVerdict]:
    """Score every planted contradiction that a question references (``contradiction_ref``),
    using that question's already-collected bundle. When ``repo`` is given, the golden
    subject is resolved so the verdict is subject-aware (post-impl review).

    Review H2 — a question whose ``ask()`` RAISED has no bundle in ``bundles``; that
    contradiction is scored INCORRECT (the engine surfaced nothing), never silently
    skipped, so a throwing model cannot earn a cleaner report than a wrong-answering one."""
    verdicts: list[ContradictionVerdict] = []
    by_id = {c.id: c for c in golden.contradictions}
    fact_by_id = {f.id: f for f in golden.facts}
    for q in questions:
        ref = q.contradiction_ref
        if not (ref and ref in by_id):
            continue
        gc = by_id[ref]
        if q.id not in bundles:  # ask() errored (or wasn't answerable) → nothing surfaced
            verdicts.append(ContradictionVerdict(
                gc.id, ContradictionClass.incorrect, False,
                f"ask() produced no answer for '{q.id}' — contradiction not surfaced",
            ))
            continue
        subject_eid: Optional[int] = None
        if repo is not None:
            # context from one side's source helps disambiguate a colliding subject name
            side = fact_by_id.get(gc.claim_a or "") or fact_by_id.get(gc.claim_b or "")
            ctx = {"source_uri": side.source_uri} if side else None
            ent = repo.resolve_entity(gc.subject, context=ctx)
            subject_eid = ent.id if ent is not None else None
        verdicts.append(score_contradiction(gc, bundles[q.id], subject_entity_id=subject_eid))
    return verdicts


# --------------------------------------------------------------------------- #
# Name-collision entity_id assertion (research P1 #7)                          #
# --------------------------------------------------------------------------- #
def check_entity_collisions(
    repo: Repository, collisions: list[EntityCollision]
) -> list[CollisionVerdict]:
    """Each colliding name, resolved with its paired context, must resolve to a DISTINCT,
    non-null ``entity_id`` — that is how the two Marias / two Tans stay separate."""
    verdicts: list[CollisionVerdict] = []
    for col in collisions:
        if len(col.contexts) != len(col.names):
            verdicts.append(CollisionVerdict(
                col.id, False,
                f"malformed probe: {len(col.contexts)} contexts != {len(col.names)} names",
            ))
            continue
        ids: list[Optional[int]] = []
        for name, ctx in zip(col.names, col.contexts):
            ent = repo.resolve_entity(name, context=ctx)
            ids.append(ent.id if ent is not None else None)
        if any(i is None for i in ids):
            unresolved = [n for n, i in zip(col.names, ids) if i is None]
            verdicts.append(CollisionVerdict(col.id, False, f"unresolved: {unresolved}"))
        elif len(set(ids)) != len(ids):
            verdicts.append(CollisionVerdict(col.id, False, f"collapsed to shared entity_id(s): {ids}"))
        else:
            verdicts.append(CollisionVerdict(col.id, True, ""))
    return verdicts


# --------------------------------------------------------------------------- #
# As-of Correctness (research P1 #6) — freshness, kept DISTINCT from contradiction
# --------------------------------------------------------------------------- #
def _is_freshness_question(q: Question) -> bool:
    """A prefer-fresh-and-say-so question: it asserts ``uses_freshest_as_of`` and is NOT
    a surface-both contradiction question (so freshness is scored apart from conflict)."""
    return "uses_freshest_as_of" in q.checks and "surfaces_contradiction" not in q.checks


def as_of_correctness(
    questions: list[Question], answers: list[AnswerResult]
) -> tuple[int, int]:
    """``(passed, total)`` over the freshness questions only — the As-of Correctness
    metric (research P1 #6), reported separately from the contradiction verdict."""
    by_id = {a.question_id: a for a in answers}
    passed = total = 0
    for q in questions:
        if not _is_freshness_question(q):
            continue
        total += 1
        a = by_id.get(q.id)
        if a and not a.error and any(c.name == "uses_freshest_as_of" and c.passed for c in a.checks):
            passed += 1
    return passed, total


# --------------------------------------------------------------------------- #
# /goal verdict                                                               #
# --------------------------------------------------------------------------- #
def goal_verdict(
    extraction: ExtractionReport,
    answers: list[AnswerResult],
    recall_bar: float = DEFAULT_RECALL_BAR,
) -> GoalVerdict:
    recall_ok = extraction.recall >= recall_bar
    answers_ok = all(a.gating_passed for a in answers) if answers else False
    # A "real" surfaced contradiction = a question that BOTH asks for one and surfaces
    # one (so a stray contradiction on a no_false_contradiction question doesn't count).
    contradiction_ok = any(
        a.surfaced_contradiction
        and any(c.name == "surfaces_contradiction" and c.passed for c in a.checks)
        for a in answers
    )
    return GoalVerdict(
        recall=extraction.recall,
        recall_bar=recall_bar,
        recall_ok=recall_ok,
        answers_ok=answers_ok,
        contradiction_ok=contradiction_ok,
    )


# --------------------------------------------------------------------------- #
# Engine resolution (lazy — keeps the oracle author-independent)              #
# --------------------------------------------------------------------------- #
class _EngineFactory(Protocol):
    def __call__(self, repo: Repository) -> QueryEngine: ...


def build_engine(repo: Repository) -> QueryEngine:
    """Resolve the concrete ``QueryEngine`` at RUN time (integration), not import time.

    Tries the conventional Agent-3 entrypoint ``helixpay.query.build_engine(repo)`` /
    ``helixpay.query.QueryEngine(repo)``. Raises a clear error if absent so the harness
    fails with exit 2 ("could not run") rather than a confusing ImportError. This late
    binding is what lets Agent 6 author the harness without reading Agent 3's code.
    """
    import importlib

    try:
        mod = importlib.import_module("helixpay.query")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "helixpay.query not importable — run the eval after Agent 3 (query) lands, "
            "or inject an engine via run(engine=...)."
        ) from exc
    for attr in ("build_engine", "make_engine", "QueryEngine", "Engine"):
        factory = getattr(mod, attr, None)
        if callable(factory):
            return factory(repo)
    raise RuntimeError("helixpay.query exposes no engine factory (build_engine/QueryEngine).")


def _build_repo() -> Repository:
    from helixpay.db.repository import PostgresRepository

    return PostgresRepository.from_url()


@dataclass
class EvalResult:
    """Everything the harness computes in one run (so the rich report is one object)."""

    extraction: ExtractionReport
    answers: list[AnswerResult]
    verdict: GoalVerdict
    contradiction_verdicts: list[ContradictionVerdict] = field(default_factory=list)
    collisions: list[CollisionVerdict] = field(default_factory=list)
    as_of_passed: int = 0
    as_of_total: int = 0


# --------------------------------------------------------------------------- #
# Reporting                                                                    #
# --------------------------------------------------------------------------- #
def render_report(result: EvalResult) -> str:
    extraction, answers, verdict = result.extraction, result.answers, result.verdict
    lo, hi = extraction.recall_ci
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("HelixPay eval — two-level autotest (Agent 6, author-independent)")
    lines.append("=" * 72)
    lines.append("")
    lines.append("LEVEL 1 — extraction check (golden recall over the raw data)")
    lines.append(
        f"  recall={extraction.recall:.0%} ({extraction.found}/{extraction.total})  "
        f"95% Wilson CI [{lo:.0%}, {hi:.0%}]  "
        f"golden-precision={extraction.precision:.0%}  "
        f"[found={extraction.found} mismatch={extraction.mismatch} missing={extraction.missing}]"
    )
    lines.append(
        f"  macro recall (per-predicate mean)={extraction.macro_recall:.0%}  "
        f"(n={extraction.total}; CI assumes i.i.d. — facts are clustered by source, "
        "so the true SE is wider)"
    )
    # per-predicate breakdown, worst recall first — where a micro score hides a miss
    per = extraction.per_predicate_recall
    for pred, (found, total, rec) in sorted(per.items(), key=lambda kv: kv[1][2]):
        flag = "  ⚠" if rec < 1.0 else ""
        lines.append(f"      · {pred}: {found}/{total} = {rec:.0%}{flag}")
    for v in extraction.verdicts:
        mark = {"FOUND": "✓", "MISMATCH": "≠", "MISSING": "✗"}[v.verdict.value]
        suffix = f"  — {v.detail}" if v.detail else ""
        lines.append(f"    {mark} {v.fact_id}{suffix}")
    lines.append("")
    lines.append("LEVEL 2 — answer check (deep questions through ask())")
    for a in answers:
        if a.error:
            lines.append(f"    ✗ {a.question_id}  ERROR: {a.error}")
            continue
        status = "PASS" if a.gating_passed else "FAIL"
        chk = " ".join(f"{c.name}{'✓' if c.passed else '✗'}" for c in a.checks)
        lines.append(f"    [{status}] {a.question_id}  ({a.latency_s*1000:.0f} ms)  {chk}")
    lines.append("")
    if result.contradiction_verdicts:
        lines.append("CONTRADICTION SCORING (WikiContradict 3-class; both-claim-id checked)")
        for cv in result.contradiction_verdicts:
            mark = {"CORRECT": "✓", "PARTIAL": "~", "INCORRECT": "✗"}[cv.verdict.value]
            ids = "both-ids✓" if cv.both_ids_present else "both-ids✗"
            lines.append(f"    {mark} {cv.contradiction_id}  [{cv.verdict.value}] {ids}  — {cv.detail}")
        lines.append("")
    if result.collisions:
        lines.append("ENTITY COLLISIONS (name traps must resolve to distinct entity_ids)")
        for col in result.collisions:
            lines.append(f"    {'✓' if col.passed else '✗'} {col.collision_id}"
                         + (f"  — {col.detail}" if col.detail else ""))
        lines.append("")
    if result.as_of_total:
        lines.append(
            f"AS-OF CORRECTNESS (freshness, distinct from contradiction): "
            f"{result.as_of_passed}/{result.as_of_total}"
        )
        lines.append("")
    lines.append("/goal verdict")
    lines.append(
        f"  recall {extraction.recall:.0%} >= bar {verdict.recall_bar:.0%}: "
        f"{'OK' if verdict.recall_ok else 'MISS'}"
    )
    lines.append(f"  all answer gating checks pass: {'OK' if verdict.answers_ok else 'MISS'}")
    lines.append(f"  >=1 real contradiction surfaced: {'OK' if verdict.contradiction_ok else 'MISS'}")
    lines.append(f"  ==> {'GREEN — /goal met' if verdict.passed else 'RED — /goal NOT met'}")
    lines.append("=" * 72)
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Entry point                                                                  #
# --------------------------------------------------------------------------- #
def run(
    repo: Optional[Repository] = None,
    engine: Optional[QueryEngine] = None,
    golden_path: Path = DEFAULT_GOLDEN,
    questions_path: Path = DEFAULT_QUESTIONS,
    recall_bar: float = DEFAULT_RECALL_BAR,
) -> EvalResult:
    """Run both levels + the SP_013 rigor scores (3-class contradiction, entity
    collisions, As-of Correctness). ``repo``/``engine`` may be injected (tests /
    integration); otherwise they are built from the environment lazily."""
    golden = load_golden(golden_path)
    questions = load_questions(questions_path)
    if repo is None:
        repo = _build_repo()
    if engine is None:
        engine = build_engine(repo)
    extraction = check_extraction(repo, golden)
    bundles: dict[str, AnswerBundle] = {}
    answers = check_answers(engine, questions, bundles_out=bundles)
    verdict = goal_verdict(extraction, answers, recall_bar)
    contradiction_verdicts = score_contradictions(golden, questions, bundles, repo=repo)
    collisions = check_entity_collisions(repo, golden.entity_collisions)
    as_of_passed, as_of_total = as_of_correctness(questions, answers)
    return EvalResult(
        extraction=extraction,
        answers=answers,
        verdict=verdict,
        contradiction_verdicts=contradiction_verdicts,
        collisions=collisions,
        as_of_passed=as_of_passed,
        as_of_total=as_of_total,
    )


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="HelixPay two-level eval harness (SPEC §8).")
    parser.add_argument("--golden", default=str(DEFAULT_GOLDEN))
    parser.add_argument("--questions", default=str(DEFAULT_QUESTIONS))
    parser.add_argument("--recall-bar", type=float, default=DEFAULT_RECALL_BAR)
    args = parser.parse_args(argv)

    if not os.environ.get("DATABASE_URL"):
        log.error("DATABASE_URL unset — the eval needs a migrated+ingested DB. (exit 2)")
        return 2
    try:
        result = run(
            golden_path=Path(args.golden),
            questions_path=Path(args.questions),
            recall_bar=args.recall_bar,
        )
    except RuntimeError as exc:
        log.error("could not run eval: %s", exc)
        return 2
    print(render_report(result))
    return 0 if result.verdict.passed else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
