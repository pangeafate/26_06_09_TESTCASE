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

    def fake_run(path):
        calls["path"] = path
        return {"documents": 3}

    fake_pipeline.run = fake_run  # type: ignore[attr-defined]
    fake_ingest = types.ModuleType("helixpay.ingest")
    monkeypatch.setitem(sys.modules, "helixpay.ingest", fake_ingest)
    monkeypatch.setitem(sys.modules, "helixpay.ingest.pipeline", fake_pipeline)

    code = main(["ingest", "./data"])
    assert code == 0
    assert calls["path"] == "./data"


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
