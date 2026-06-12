"""Unit coverage for the require-db guard helper (DB-free).

The guard converts a misconfigured CI database from a silent skip of the whole DB
integration suite into a loud, early failure. This pins the pure decision helper so
the behavior is verifiable without a database (SP_030 Item 1).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

# Import the helper from the root test/conftest.py without going through pytest's
# conftest machinery (conftest is not a normal importable module by name).
_CONFTEST = Path(__file__).resolve().parents[1] / "conftest.py"
_spec = importlib.util.spec_from_file_location("_helixpay_root_conftest", _CONFTEST)
assert _spec is not None and _spec.loader is not None
_conftest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_conftest)
_require_db_violation = _conftest._require_db_violation


def test_absent_url_and_no_flag_is_not_a_violation():
    # The normal local case: no DB, no requirement → skip path preserved (None).
    assert _require_db_violation({}) is None


def test_required_but_absent_url_is_a_violation():
    # CI's contract: flag set, DB missing → loud failure message.
    msg = _require_db_violation({"HELIXPAY_REQUIRE_DB": "1"})
    assert msg is not None
    assert "DATABASE_URL" in msg


def test_required_and_url_present_is_not_a_violation():
    assert (
        _require_db_violation(
            {"HELIXPAY_REQUIRE_DB": "1", "DATABASE_URL": "postgres://x/y"}
        )
        is None
    )


def test_falsey_flag_values_do_not_require_db():
    # Treat the usual "off" spellings as not-required so a stray empty/0/false
    # never reds a no-DB local run.
    for off in ("", "0", "false", "no", "FALSE", "No"):
        assert _require_db_violation({"HELIXPAY_REQUIRE_DB": off}) is None


def test_empty_url_with_flag_is_a_violation():
    # An empty DATABASE_URL is "absent" — must still fail loud, not skip.
    assert _require_db_violation({"HELIXPAY_REQUIRE_DB": "1", "DATABASE_URL": ""}) is not None
