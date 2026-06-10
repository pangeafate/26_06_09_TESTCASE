"""SP_015 ↔ SP_014 seam: a real ``LossLedger`` must plug into the proving bar.

SP_014's ``LossLedger.probe()`` is zero-arg (returns the whole table); ``check_smoke`` wants a
per-URI callable. ``ledger_probe_from`` bridges them. This test exercises the *actual* SP_014
ledger (not a hand-rolled dict) so a drift in either side's shape fails here — the one place
the two sprints are coupled. Pure, no DB/net/paid.
"""

from __future__ import annotations

from eval.smoke.check_smoke import doc_verdict, embedding_probe_from, ledger_probe_from
from helixpay.ingest.extract.ledger import LossLedger

_CLEAN = "data/overview.md"
_EMPTY = "data/board-deck-q1-2026.pdf"
_TRUNC = "data/dashboards/april-2026-kpi-dashboard.html"
_DROP = "data/org-chart.md"
_UNSEEN = "data/never-extracted.md"


def _ledger() -> LossLedger:
    led = LossLedger()
    # a clean doc: chunks + emitted items, nothing lost
    led.record_chunk(_CLEAN)
    led.record_emitted(_CLEAN, 3)
    # a doc with a silent empty extraction (Defect A)
    led.record_chunk(_EMPTY)
    led.record_empty(_EMPTY)
    # a doc with a truncated call
    led.record_chunk(_TRUNC)
    led.record_truncated(_TRUNC)
    # a doc with a coerce drop (Defect B — needs human explanation)
    led.record_chunk(_DROP)
    led.record_emitted(_DROP, 5)
    led.record_drop(_DROP, "unmappable_enum")
    return led


def test_real_ledger_probe_shape_matches_check_smoke_contract() -> None:
    probe = ledger_probe_from(_ledger())
    entry = probe(_CLEAN)
    assert entry is not None
    # exactly the three keys check_smoke reads
    assert set(entry) == {"empty_extractions", "truncated_calls", "items_dropped"}


def test_clean_doc_passes() -> None:
    probe = ledger_probe_from(_ledger())
    v = doc_verdict(_CLEAN, golden_found=2, golden_total=2, golden_precision=1.0,
                    ledger_entry=probe(_CLEAN), embedding_ok=True)
    assert v["verdict"] == "PASS"


def test_silent_empty_is_fail() -> None:
    probe = ledger_probe_from(_ledger())
    v = doc_verdict(_EMPTY, 1, 1, 1.0, probe(_EMPTY), embedding_ok=True)
    assert v["verdict"] == "FAIL"


def test_truncated_call_is_fail() -> None:
    probe = ledger_probe_from(_ledger())
    v = doc_verdict(_TRUNC, 1, 1, 1.0, probe(_TRUNC), embedding_ok=True)
    assert v["verdict"] == "FAIL"


def test_coerce_drop_is_incomplete() -> None:
    probe = ledger_probe_from(_ledger())
    v = doc_verdict(_DROP, 1, 1, 1.0, probe(_DROP), embedding_ok=True)
    assert v["verdict"] == "INCOMPLETE"


def test_unseen_uri_is_incomplete_never_pass() -> None:
    # a doc the ledger never recorded → None → completeness unverified → INCOMPLETE.
    probe = ledger_probe_from(_ledger())
    assert probe(_UNSEEN) is None
    v = doc_verdict(_UNSEEN, 1, 1, 1.0, probe(_UNSEEN), embedding_ok=True)
    assert v["verdict"] == "INCOMPLETE"


def test_ledger_probe_accepts_a_materialised_dict() -> None:
    # ledger_probe_from also accepts an already-materialised probe() dict, not just the object.
    table = _ledger().probe()
    probe = ledger_probe_from(table)
    assert probe(_CLEAN) == table[_CLEAN]


def test_embedding_probe_adapter() -> None:
    probe = embedding_probe_from({_CLEAN: True, _EMPTY: False})
    assert probe(_CLEAN) is True
    assert probe(_EMPTY) is False
    assert probe(_UNSEEN) is None  # unseen → None → embedding-unverified (INCOMPLETE)
