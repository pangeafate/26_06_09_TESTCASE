"""End-to-end smoke over the REAL data/ with the REAL LLM + Voyage (the §8 "≥1 real
contradiction on the actual data" proof).

Triple-gated and so skips in CI/dev unless everything is present:
* ``db`` mark      — needs ``DATABASE_URL`` (conftest auto-skip);
* key ``skipif``   — needs ``ANTHROPIC_API_KEY`` and ``VOYAGE_API_KEY`` (the ``db`` mark
                     gates only the database, not the API keys — Stage-3 M-2);
* ``importorskip`` — needs Agent 1's ``helixpay.ingest.loaders`` merged.

This is the integration-time oracle the orchestrator runs; it is not part of the fast unit
bar (which is fully stubbed).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.db

_HAVE_KEYS = bool(os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("VOYAGE_API_KEY"))


@pytest.mark.smoke
@pytest.mark.skipif(not _HAVE_KEYS, reason="needs ANTHROPIC_API_KEY and VOYAGE_API_KEY")
def test_real_ingest_surfaces_a_contradiction(pg_repo):
    pytest.importorskip(
        "helixpay.ingest.loaders", reason="Agent 1 loaders (SP_002) not merged yet"
    )
    from helixpay.seed.run_seed import seed_all  # roster + metric_vocab so resolution/canon work
    from helixpay.ingest.pipeline import run

    seed_all(pg_repo, Path("data"), with_fixture=False)
    report = run("data", pg_repo)

    assert report.documents > 0 and report.claims > 0
    assert report.contradictions >= 1, "expected at least one real contradiction on data/"
