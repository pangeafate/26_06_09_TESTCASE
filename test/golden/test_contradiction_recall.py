"""The contradiction-recall oracle: well-formedness, the no-hardcoding guard, and the
blind DB ratchet.

The oracle (``test/golden/contradictions.yaml``) captures the 8 conflicts a human found by
eye. These tests assert (1) the oracle itself is well-formed and points at real sources — a
wrong oracle is worse than none; (2) it is NEVER imported by the pipeline (the no-hardcoding
contract the user asked for); (3) its values do not leak into prompts/; and (4) — when a DB
is reachable — the LIVE detector's catch count never drops below the known baseline.

The DB test is marked ``db`` and auto-skips without ``DATABASE_URL`` (conftest).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from eval.contradiction_recall import (
    DEFAULT_ORACLE,
    _SEVERITIES,
    format_report,
    load_oracle,
    score,
)
from helixpay.seed.metric_vocab import canonical_key

_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="module")
def oracle():
    return load_oracle()


# --------------------------------------------------------------------------- #
# Well-formedness — a wrong oracle is worse than none                         #
# --------------------------------------------------------------------------- #
def test_oracle_has_the_eight_findings(oracle):
    assert len(oracle) == 8, "the human found exactly 8 conflicts; the oracle must hold all 8"


def test_ids_unique(oracle):
    ids = [c.id for c in oracle]
    assert len(ids) == len(set(ids)), "duplicate oracle id"


def test_core_fields_present_and_severities_known(oracle):
    for c in oracle:
        assert c.subject and c.predicate and c.value_a and c.value_b, c.id
        assert c.value_a != c.value_b or c.predicate_b, (
            f"{c.id}: a same-value conflict must be cross-predicate (predicate_b set)"
        )
        assert c.severity in _SEVERITIES, f"{c.id}: unknown severity {c.severity!r}"
        assert c.expected == "surfaced", f"{c.id}: every conflict must end up surfaced, never resolved"


def test_every_source_exists(oracle):
    for c in oracle:
        for uri in (c.source_a, c.source_b):
            assert (_ROOT / uri).is_file(), f"{c.id}: missing source {uri}"


def test_each_item_declares_root_cause_and_lever(oracle):
    # The oracle doubles as the remediation map: every miss names why it is missed and which
    # research/ lever should catch it, so a flipped baseline_caught is traceable to a change.
    for c in oracle:
        assert c.root_cause, f"{c.id}: missing root_cause"
        assert c.lever, f"{c.id}: missing lever"


def test_baseline_is_the_confluence_target_only(oracle):
    # Measured 2026-06-11: the detector materializes exactly one of the eight today. Flip a
    # flag to true (and raise this expectation) as a lever lands — never silently.
    caught = {c.id for c in oracle if c.baseline_caught}
    assert caught == {"confluence-ga-target"}, (
        f"baseline_caught set changed to {caught} — update this test when a lever lifts an item"
    )


# --------------------------------------------------------------------------- #
# No-hardcoding contract — the oracle informs the TEST, never the pipeline    #
# --------------------------------------------------------------------------- #
def test_oracle_not_referenced_by_pipeline():
    # The bright line the user drew: if a helixpay/ module read this oracle, the detector would
    # be "finding" conflicts it was told about — hardcoding. Assert no production module names it.
    hits = []
    for py in (_ROOT / "helixpay").rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="ignore")
        if "contradictions.yaml" in text or "contradiction_recall" in text:
            hits.append(str(py.relative_to(_ROOT)))
    assert not hits, f"oracle leaked into the pipeline (hardcoding): {hits}"


def test_oracle_values_do_not_leak_into_prompts(oracle):
    # Ground-truth values must never appear in few-shot prompts (DEV_RULES §12 leakage), or the
    # extractor would be coached with the answer. Check the distinctive tokens.
    prompts_dir = _ROOT / "prompts"
    if not prompts_dir.is_dir():
        pytest.skip("no prompts/ dir")
    blob = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore") for p in prompts_dir.rglob("*.md")
    ).casefold()
    # Graded VALUE tokens that must never be handed to the extractor as a few-shot. (Softer
    # entity-NAME hints — "Project Confluence", "CRM migration" — and bare date phrasings are a
    # separate, entangled class tracked in research/; this guards the clearly-graded values.)
    distinctive = [
        "hx-loy-487",
        "r$ 2.140",
        "northwind",
        "açaí express sp",
        "cosmos hotels",
        "620k",  # Northwind deal_amount
        "2026-05-12",  # Northwind expected_close_date (the graded value)
    ]
    leaked = [tok for tok in distinctive if tok in blob]
    assert not leaked, f"oracle tokens leaked into prompts/: {leaked}"


def test_predicates_are_stable_keys(oracle):
    # canonical_key must be a no-op-or-map (never raise) on every oracle predicate, so the blind
    # scorer's predicate match is well-defined.
    for c in oracle:
        for pred in c.predicates:
            assert canonical_key(pred) is not None, f"{c.id}: predicate {pred!r} canonicalizes to None"


# --------------------------------------------------------------------------- #
# Blind DB ratchet — the live detector must not regress below baseline        #
# --------------------------------------------------------------------------- #
# SP_030: pre-existing failure exposed when CI first ran the db suite. This "live
# detector" ratchet connects directly (no pg_repo/apply_schema) and expects a BUILT,
# seeded corpus DB; against an empty CI pgvector it errors (relation "contradictions"
# does not exist) instead of skipping gracefully. SP_031 makes it empty-DB-safe (skip
# when unbuilt) or seeds a CI corpus.
@pytest.mark.db
def test_live_detector_meets_baseline(oracle, db_url):
    """Score the oracle against whatever the live DB materialized. Skip an UNBUILT DB (nothing
    to measure); on a built DB, assert caught >= baseline (the ratchet) and print the scorecard."""
    pytest.importorskip("psycopg")
    from helixpay.db.connection import connect
    from helixpay.db.repository import PostgresRepository

    conn = connect(db_url)
    try:
        repo = PostgresRepository(conn)
        # SP_031/D4: an empty CI DB may have NO schema applied — `get_contradictions` would
        # raise `relation "contradictions" does not exist` (which also aborts the txn). Guard
        # the missing-relation case first; `to_regclass` returns NULL (never raises) when absent.
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('contradictions') AS t")
            if cur.fetchone()["t"] is None:
                pytest.skip("contradictions relation absent — schema not applied, nothing to score")
        if not repo.get_contradictions(None):
            pytest.skip("DB has no contradictions — KB not built, nothing to score")
        report = score(repo, oracle)
        print("\n" + format_report(report))  # noqa: T201 — surfaced by `pytest -s`
        assert report.caught >= report.baseline, (
            f"contradiction recall regressed: caught {report.caught} < baseline {report.baseline}\n"
            + format_report(report)
        )
    finally:
        conn.close()
