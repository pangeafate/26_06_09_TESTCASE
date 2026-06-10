"""CLI — ``helixpay ask`` prints a cited, contradiction-surfacing answer via the engine;
``helixpay ingest`` imports the pipeline lazily (so the CLI works before Agent 2 lands)."""

from __future__ import annotations

import pytest

from helixpay.api.engine import MockQueryEngine, get_engine, set_engine
from helixpay.cli import main


@pytest.fixture(autouse=True)
def _mock_engine():
    original = get_engine()
    set_engine(MockQueryEngine())
    yield
    set_engine(original)


def test_ask_prints_answer_citations_and_contradictions(capsys):
    code = main(["ask", "What was Q1 revenue?"])
    out = capsys.readouterr().out
    assert code == 0
    assert "[mock]" in out                      # the answer
    assert "Citations:" in out
    assert "as_of 2025-04-15" in out            # citation carries its as_of date
    assert "Contradictions:" in out
    assert "value_conflict" in out              # the planted conflict is surfaced


def test_ingest_imports_pipeline_lazily(monkeypatch):
    """The CLI imports helixpay.ingest.pipeline.run only inside the subcommand, and only
    when invoked — so importing the CLI never requires Agent 2's code."""
    calls = {}

    import sys
    import types

    fake_pipeline = types.ModuleType("helixpay.ingest.pipeline")

    def fake_run(path, **kwargs):  # SP_013: CLI now passes repo=/already_ingested=
        calls["path"] = path
        return {"documents": 3}

    fake_pipeline.run = fake_run  # type: ignore[attr-defined]
    fake_ingest = types.ModuleType("helixpay.ingest")
    monkeypatch.setitem(sys.modules, "helixpay.ingest", fake_ingest)
    monkeypatch.setitem(sys.modules, "helixpay.ingest.pipeline", fake_pipeline)

    code = main(["ingest", "./data"])
    assert code == 0
    assert calls["path"] == "./data"


def test_ingest_wires_already_ingested_and_prints_skipped(monkeypatch, capsys):
    """SP_013: the CLI builds `already_ingested` from `repo.known_content_hashes()` and
    threads BOTH it and the repo into pipeline.run, then surfaces the skipped count.
    The pipeline's skip-before-extract guarantee (zero LLM calls) is covered by the
    pipeline unit tests (test_already_ingested_skips_embed_and_extract)."""
    import sys
    import types

    from helixpay.ingest.pipeline import IngestReport

    captured = {}

    fake_pipeline = types.ModuleType("helixpay.ingest.pipeline")

    def fake_run(path, *, repo=None, already_ingested=None, **kwargs):
        captured["path"] = path
        captured["repo"] = repo
        captured["already_ingested"] = already_ingested
        return IngestReport(documents=0, skipped_documents=1)

    fake_pipeline.run = fake_run  # type: ignore[attr-defined]
    fake_pipeline.IngestReport = IngestReport  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "helixpay.ingest", types.ModuleType("helixpay.ingest"))
    monkeypatch.setitem(sys.modules, "helixpay.ingest.pipeline", fake_pipeline)

    class _FakeRepo:
        def known_content_hashes(self):
            return {"h1"}

    monkeypatch.setattr(
        "helixpay.db.repository.PostgresRepository.from_url",
        classmethod(lambda cls: _FakeRepo()),
    )

    code = main(["ingest", "./data"])
    out = capsys.readouterr().out
    assert code == 0
    # the same repo is handed to the pipeline (single connection, no dual build)
    assert isinstance(captured["repo"], _FakeRepo)
    # already_ingested is the membership test over the DB's known hashes
    pred = captured["already_ingested"]
    assert callable(pred) and pred("h1") is True and pred("not-seen") is False
    # the skipped count is observable in the summary
    assert "skipped 1" in out


def test_ingest_degrades_to_full_ingest_when_db_unavailable(monkeypatch, capsys):
    """If the DB can't be reached, idempotency is skipped (already_ingested=None) and a
    full ingest is still attempted — the CLI never crashes on the optimisation path."""
    import sys
    import types

    captured = {}

    fake_pipeline = types.ModuleType("helixpay.ingest.pipeline")

    def fake_run(path, *, repo=None, already_ingested=None, **kwargs):
        captured["already_ingested"] = already_ingested
        captured["repo"] = repo
        return {"documents": 1}

    fake_pipeline.run = fake_run  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "helixpay.ingest", types.ModuleType("helixpay.ingest"))
    monkeypatch.setitem(sys.modules, "helixpay.ingest.pipeline", fake_pipeline)

    def _boom(cls):
        raise RuntimeError("no DATABASE_URL")

    monkeypatch.setattr(
        "helixpay.db.repository.PostgresRepository.from_url", classmethod(_boom)
    )

    code = main(["ingest", "./data"])
    assert code == 0
    assert captured["already_ingested"] is None
    assert captured["repo"] is None


def test_cli_module_does_not_import_ingest_at_module_level(monkeypatch):
    """Importing the CLI must NOT pull in helixpay.ingest — the dependency is resolved
    lazily inside the ingest subcommand only. Proven by clearing any cached ingest
    modules, reloading the CLI, and asserting none were imported as a side effect."""
    import importlib
    import sys

    for mod in [m for m in sys.modules if m == "helixpay.ingest" or m.startswith("helixpay.ingest.")]:
        monkeypatch.delitem(sys.modules, mod, raising=False)

    import helixpay.cli as cli

    importlib.reload(cli)
    assert "helixpay.ingest" not in sys.modules
    assert "helixpay.ingest.pipeline" not in sys.modules
