"""DB-gated integration smoke: the grader runs end-to-end against a real Postgres
through the Repository (no build slice), using the gate's seeded query fixture.

Skipped automatically when ``DATABASE_URL`` is unset (see test/conftest.py). This is
the "runnable before real extraction lands, on the seeded fixture" check from the brief.
"""

from __future__ import annotations

from datetime import date

import pytest

from eval.models import GoldenFact, GoldenSet, Verdict
from eval.run import check_extraction, load_golden


@pytest.mark.db
def test_check_extraction_runs_against_seeded_fixture(pg_repo):
    """A clean migrated DB + the gate query fixture; the grader executes and the
    fixture's Q1-revenue claim is matched as FOUND through the real Repository."""
    from helixpay.seed.fixtures import load_fixture

    load_fixture(pg_repo)  # entity "Revenue" + two revenue claims + one contradiction

    fact = GoldenFact.model_validate(
        {
            "id": "fixture-revenue",
            "format": "html",
            "kind": "claim",
            "subject": "Revenue",
            "predicate": "revenue",
            "value": "SGD 14.2M",
            "as_of": date(2026, 3, 31),
            "source_uri": "data/dashboards/april-2026-kpi-dashboard.html",
        }
    )
    report = check_extraction(pg_repo, GoldenSet(facts=[fact], contradictions=[]))
    assert report.verdicts[0].verdict is Verdict.found
    assert report.recall == 1.0


@pytest.mark.db
def test_full_golden_set_runs_without_error(pg_repo):
    """The real golden set grades against an (un-ingested) DB without raising; recall
    is low here (extraction hasn't run) — the point is the grader executes cleanly and
    reports honestly rather than crashing."""
    golden = load_golden()
    report = check_extraction(pg_repo, golden)
    assert report.total == len(golden.bar_facts)
    assert 0.0 <= report.recall <= 1.0
    assert 0.0 <= report.precision <= 1.0
