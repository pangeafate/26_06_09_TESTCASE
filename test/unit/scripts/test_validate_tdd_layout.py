"""Unit coverage for validate_tdd.py's layout-tolerant resolution (SP_030 Item 5).

These pin the additions that let the structural check work against HelixPay's real
layout (no ``src/``; a FLATTENED test mirror) without reddening the deploy gate:

- ``_resolve_src_dir`` auto-detects ``helixpay`` when ``src/`` is absent.
- ``_find_test_file`` matches a ``test_<name>.py`` anywhere under the test tree
  (flattened/behavior-named layouts), while a genuinely test-less module still
  resolves to ``None``.
- ``_tdd_settings`` reads ``structure_advisory`` so unmatched sources are reported
  but do not fail the build.

The existing strict contract is owned by ``validators/test_validate_tdd.py`` (kept green).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[3] / "validators" / "validate_tdd.py"
_spec = importlib.util.spec_from_file_location("_validate_tdd_under_test", _MOD_PATH)
assert _spec is not None and _spec.loader is not None
vt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vt)


# --- _resolve_src_dir --------------------------------------------------------- #


def test_resolve_uses_requested_dir_when_present(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    assert vt._resolve_src_dir(tmp_path, "src", None) == "src"


def test_resolve_falls_back_to_helixpay_when_src_absent(tmp_path: Path) -> None:
    (tmp_path / "helixpay").mkdir()
    # No src/ → auto-detect the real package.
    assert vt._resolve_src_dir(tmp_path, "src", None) == "helixpay"


def test_resolve_prefers_configured_src_dir(tmp_path: Path) -> None:
    (tmp_path / "mypkg").mkdir()
    (tmp_path / "helixpay").mkdir()
    assert vt._resolve_src_dir(tmp_path, "src", "mypkg") == "mypkg"


def test_resolve_keeps_requested_when_nothing_exists(tmp_path: Path) -> None:
    assert vt._resolve_src_dir(tmp_path, "src", None) == "src"


# --- _find_test_file: flattened-mirror tolerance ------------------------------ #


def test_flattened_mirror_path_resolves(tmp_path: Path) -> None:
    # helixpay/ingest/extract/coerce.py → test/unit/ingest/test_coerce.py
    src = tmp_path / "helixpay"
    (src / "ingest" / "extract").mkdir(parents=True)
    source = src / "ingest" / "extract" / "coerce.py"
    source.write_text("x = 1\n")

    test_dir = tmp_path / "test"
    (test_dir / "unit" / "ingest").mkdir(parents=True)
    (test_dir / "unit" / "ingest" / "test_coerce.py").write_text("def test_x():\n    pass\n")

    found = vt._find_test_file(source, src, test_dir)
    assert found is not None and found.name == "test_coerce.py"


def test_testless_module_still_resolves_to_none(tmp_path: Path) -> None:
    # The genuine-gap signal must survive: no test_<name>.py anywhere → None.
    src = tmp_path / "helixpay"
    src.mkdir()
    source = src / "orphan.py"
    source.write_text("x = 1\n")

    test_dir = tmp_path / "test"
    (test_dir / "unit").mkdir(parents=True)
    (test_dir / "unit" / "test_something_else.py").write_text("def test_y():\n    pass\n")

    assert vt._find_test_file(source, src, test_dir) is None


# --- _tdd_settings ------------------------------------------------------------ #


def test_tdd_settings_defaults_strict() -> None:
    s = vt._tdd_settings({})
    assert s["structure_advisory"] is False
    assert s["src_dir"] is None


def test_tdd_settings_reads_advisory_and_src_dir() -> None:
    s = vt._tdd_settings({"tdd": {"src_dir": "helixpay", "structure_advisory": True}})
    assert s["structure_advisory"] is True
    assert s["src_dir"] == "helixpay"


# --- end-to-end: advisory mode reports gaps without failing ------------------- #


def test_advisory_mode_reports_gap_but_exits_zero(tmp_path: Path) -> None:
    src = tmp_path / "helixpay"
    src.mkdir()
    (src / "covered.py").write_text("x = 1\n")
    (src / "orphan.py").write_text("y = 2\n")

    test_dir = tmp_path / "test" / "unit"
    test_dir.mkdir(parents=True)
    (test_dir / "test_covered.py").write_text("def test_c():\n    pass\n")

    (tmp_path / ".validators.yml").write_text(
        "tdd:\n  src_dir: helixpay\n  structure_advisory: true\n"
    )

    code, messages = vt.validate(tmp_path, "src", "test")
    joined = "\n".join(messages)
    assert code == 0  # advisory: the orphan does not fail the build
    assert "ADVISORY: orphan.py" in joined
    assert "no test file found" in joined
