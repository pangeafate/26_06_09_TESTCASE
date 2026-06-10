"""SP_015 — the per-doc proving bar (pure logic + integrity helpers, no DB/net/paid).

The DB-backed `check()` is exercised by an operator/db-gated run; here we pin the
verdict aggregation (golden + completeness + embedding), the INCOMPLETE-never-PASS rule
when the SP_014 ledger is absent, the corpus fingerprint, and the "no paid surface"
guarantee (check_smoke must never reach Opus `ask()` / `build_engine`).
"""

from __future__ import annotations

from pathlib import Path

from eval.smoke import check_smoke as cs

ROOT = Path(__file__).resolve().parents[3]

_CLEAN_LEDGER = {"empty_extractions": 0, "truncated_calls": 0, "items_dropped": 0}


def test_pass_when_golden_complete_ledger_clean_embedding_ok() -> None:
    v = cs.doc_verdict("data/overview.md", golden_found=2, golden_total=2,
                       golden_precision=1.0, ledger_entry=_CLEAN_LEDGER, embedding_ok=True)
    assert v["verdict"] == "PASS"


def test_absent_ledger_is_incomplete_never_pass() -> None:
    # the architect's load-bearing rule: golden green but completeness unverifiable -> INCOMPLETE.
    v = cs.doc_verdict("data/overview.md", golden_found=2, golden_total=2,
                       golden_precision=1.0, ledger_entry=None, embedding_ok=True)
    assert v["verdict"] == "INCOMPLETE"
    assert v["verdict"] != "PASS"


def test_missing_golden_fact_fails() -> None:
    v = cs.doc_verdict("data/org-chart.md", golden_found=2, golden_total=3,
                       golden_precision=1.0, ledger_entry=_CLEAN_LEDGER, embedding_ok=True)
    assert v["verdict"] == "FAIL"


def test_silent_empty_extraction_fails_even_without_golden() -> None:
    # completeness catches what golden can't: a silent empty is a FAIL.
    led = {"empty_extractions": 1, "truncated_calls": 0, "items_dropped": 0}
    v = cs.doc_verdict("data/dashboards/april-2026-kpi-dashboard.html", golden_found=0,
                       golden_total=0, golden_precision=None, ledger_entry=led, embedding_ok=True)
    assert v["verdict"] == "FAIL"


def test_truncated_call_fails() -> None:
    led = {"empty_extractions": 0, "truncated_calls": 2, "items_dropped": 0}
    v = cs.doc_verdict("x", 1, 1, 1.0, led, True)
    assert v["verdict"] == "FAIL"


def test_drops_need_human_review_incomplete() -> None:
    led = {"empty_extractions": 0, "truncated_calls": 0, "items_dropped": 3}
    v = cs.doc_verdict("x", 1, 1, 1.0, led, True)
    assert v["verdict"] == "INCOMPLETE"


def test_zero_norm_embedding_fails() -> None:
    v = cs.doc_verdict("x", 1, 1, 1.0, _CLEAN_LEDGER, embedding_ok=False)
    assert v["verdict"] == "FAIL"


def test_fail_dominates_incomplete() -> None:
    # a FAIL on golden plus an absent ledger still reports FAIL (most severe wins).
    v = cs.doc_verdict("x", 0, 2, 1.0, ledger_entry=None, embedding_ok=True)
    assert v["verdict"] == "FAIL"


def test_corpus_fingerprint_is_stable_and_sensitive(tmp_path: Path) -> None:
    d = tmp_path / "data"
    d.mkdir()
    (d / "a.md").write_text("hello")
    uris = ["data/a.md"]
    fp1 = cs.corpus_fingerprint(tmp_path, uris)
    fp2 = cs.corpus_fingerprint(tmp_path, uris)
    assert fp1 == fp2 and fp1["data/a.md"]
    (d / "a.md").write_text("changed")
    fp3 = cs.corpus_fingerprint(tmp_path, uris)
    assert fp3 != fp1, "fingerprint must change when a doc changes"


def test_check_smoke_has_no_paid_answer_surface() -> None:
    # Stage-3 security finding: check_smoke must call Level-1 check_extraction only,
    # never run()/main()/check_answers()/build_engine() (which reach Opus ask()).
    src = (ROOT / "eval" / "smoke" / "check_smoke.py").read_text()
    # exclude the explanatory comment lines so the guard checks real references, not prose.
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
    for forbidden in ("build_engine", "check_answers", ".ask(", "MockQueryEngine", "from eval.run import run"):
        assert forbidden not in code, f"check_smoke must not reference {forbidden} (paid/answer surface)"
