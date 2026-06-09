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
from pathlib import Path
from typing import Optional, Protocol

import yaml  # type: ignore[import-untyped]

from helixpay.contracts import AnswerBundle, Claim, Link, QueryEngine, Repository

from eval.models import (
    GATING_CHECKS,
    AnswerResult,
    CheckResult,
    ExtractionReport,
    FactVerdict,
    GoalVerdict,
    GoldenContradiction,
    GoldenFact,
    GoldenSet,
    Question,
    Verdict,
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
    _assert_unique_ids([f.id for f in facts], "golden fact")  # a dup id would mask a fact
    return GoldenSet(facts=facts, contradictions=cons)


def load_questions(path: Path = DEFAULT_QUESTIONS) -> list[Question]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    questions = [Question.model_validate(q) for q in raw.get("questions", [])]
    _assert_unique_ids([q.id for q in questions], "question")
    return questions


# --------------------------------------------------------------------------- #
# Value / URI normalization (matching tolerance — review M1)                  #
# --------------------------------------------------------------------------- #
def normalize_value(s: Optional[str]) -> str:
    """Lowercase, strip currency/symbols/punctuation and collapse whitespace so
    ``"SGD 14.2M"`` matches ``"14.2m"`` and ``"$14.2 million"``."""
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


# --------------------------------------------------------------------------- #
# Level 1 — extraction check                                                  #
# --------------------------------------------------------------------------- #
def _check_claim_fact(repo: Repository, fact: GoldenFact) -> FactVerdict:
    entity = repo.resolve_entity(fact.subject, context={"source_uri": fact.source_uri})
    if entity is None or entity.id is None:
        return FactVerdict(fact.id, Verdict.missing, f"subject '{fact.subject}' unresolved")
    pred = repo.canonical_predicate(fact.predicate)
    claims: list[Claim] = repo.get_claims(entity.id, pred)
    if not claims:  # fall back to all claims, filter by canonicalized predicate
        claims = [c for c in repo.get_claims(entity.id) if repo.canonical_predicate(c.predicate) == pred]
    if not claims:
        return FactVerdict(fact.id, Verdict.missing, f"no claim on ({fact.subject}, {pred})")

    best = Verdict.missing
    detail = "claim(s) exist but value/source/as_of differ"
    for c in claims:
        if not _values_match(fact.value, c.object_value):
            best = _worst(best, Verdict.mismatch)
            continue
        sources = repo.get_sources([c.id]) if c.id is not None else []
        src_ok = any(_uri_matches(fact.source_uri, s.source_uri) for s in sources)
        if not src_ok:
            best = _worst(best, Verdict.mismatch)
            detail = "right value, wrong/absent source"
            continue
        asof_ok = fact.as_of is None or c.as_of == fact.as_of or any(
            s.as_of == fact.as_of for s in sources
        )
        if asof_ok:
            return FactVerdict(fact.id, Verdict.found, "")
        best = _worst(best, Verdict.mismatch)
        detail = f"right value+source, as_of {c.as_of} != {fact.as_of}"
    return FactVerdict(fact.id, best, detail)


def _check_link_fact(repo: Repository, fact: GoldenFact) -> FactVerdict:
    link_type = fact.link_type or fact.predicate
    from_name, to_name = fact.from_ or fact.subject, fact.to or fact.value
    fe = repo.resolve_entity(from_name, context={"source_uri": fact.source_uri})
    te = repo.resolve_entity(to_name, context={"source_uri": fact.source_uri})
    if fe is None or te is None or fe.id is None or te.id is None:
        unresolved = from_name if fe is None else to_name
        return FactVerdict(fact.id, Verdict.missing, f"endpoint '{unresolved}' unresolved")
    links: list[Link] = repo.get_links(link_type)
    for link in links:
        if link.from_entity_id == fe.id and link.to_entity_id == te.id:
            return FactVerdict(fact.id, Verdict.found, "")
    for link in links:  # reversed direction → a real but mis-directed extraction
        if link.from_entity_id == te.id and link.to_entity_id == fe.id:
            return FactVerdict(fact.id, Verdict.mismatch, f"{link_type} present but reversed")
    return FactVerdict(fact.id, Verdict.missing, f"no {link_type} {from_name}->{to_name}")


def _worst(a: Verdict, b: Verdict) -> Verdict:
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


def check_answers(engine: QueryEngine, questions: list[Question]) -> list[AnswerResult]:
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


# --------------------------------------------------------------------------- #
# Reporting                                                                    #
# --------------------------------------------------------------------------- #
def render_report(
    extraction: ExtractionReport,
    answers: list[AnswerResult],
    verdict: GoalVerdict,
) -> str:
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("HelixPay eval — two-level autotest (Agent 6, author-independent)")
    lines.append("=" * 72)
    lines.append("")
    lines.append("LEVEL 1 — extraction check (golden recall over the raw data)")
    lines.append(
        f"  recall={extraction.recall:.0%} ({extraction.found}/{extraction.total})  "
        f"golden-precision={extraction.precision:.0%}  "
        f"[found={extraction.found} mismatch={extraction.mismatch} missing={extraction.missing}]"
    )
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
) -> tuple[ExtractionReport, list[AnswerResult], GoalVerdict]:
    """Run both levels. ``repo``/``engine`` may be injected (tests / integration);
    otherwise they are built from the environment lazily."""
    golden = load_golden(golden_path)
    questions = load_questions(questions_path)
    if repo is None:
        repo = _build_repo()
    if engine is None:
        engine = build_engine(repo)
    extraction = check_extraction(repo, golden)
    answers = check_answers(engine, questions)
    verdict = goal_verdict(extraction, answers, recall_bar)
    return extraction, answers, verdict


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
        extraction, answers, verdict = run(
            golden_path=Path(args.golden),
            questions_path=Path(args.questions),
            recall_bar=args.recall_bar,
        )
    except RuntimeError as exc:
        log.error("could not run eval: %s", exc)
        return 2
    print(render_report(extraction, answers, verdict))
    return 0 if verdict.passed else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
