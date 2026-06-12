"""SP_031 I1 — the dev-gateway must run the PROJECT interpreter, not the ambient one.

Root cause of the 15-entry gateway bypass log: the gateway shelled the system
``python3`` (no ``bs4``/``psycopg``) for its child validators/pytest, so every step
``ImportError``ed and was waived. ``_project_python`` resolves the project venv
interpreter instead, with precedence:

    $VIRTUAL_ENV/bin/python  >  <root>/.venv/bin/python  >  sys.executable

Path-existence is the gate (a real probe would cost a subprocess). The guarantee is that
``uv sync --extra dev`` created the venv before the gateway runs; choosing ``.venv/bin/python``
then propagates to all 11 sub-validators because ``run_all.py`` itself spawns each via its
own ``sys.executable`` (which is now the venv python).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _load_gateway():
    spec = importlib.util.spec_from_file_location(
        "dev_gateway_under_test", ROOT / "scripts" / "dev-gateway.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = mod  # frozen dataclass resolves its own module
    spec.loader.exec_module(mod)
    return mod


gw = _load_gateway()


def _make_venv(root: Path) -> Path:
    py = root / ".venv" / "bin" / "python"
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_text("#!/bin/sh\n")
    return py


def test_prefers_local_dotvenv_when_present(tmp_path, monkeypatch):
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    py = _make_venv(tmp_path)
    assert gw._project_python(tmp_path) == str(py)


def test_virtualenv_env_takes_precedence_over_dotvenv(tmp_path, monkeypatch):
    _make_venv(tmp_path)  # a local .venv also exists
    active = tmp_path / "active-env"
    (active / "bin").mkdir(parents=True)
    (active / "bin" / "python").write_text("#!/bin/sh\n")
    monkeypatch.setenv("VIRTUAL_ENV", str(active))
    assert gw._project_python(tmp_path) == str(active / "bin" / "python")


def test_falls_back_to_sys_executable_when_no_venv(tmp_path, monkeypatch):
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    assert gw._project_python(tmp_path) == sys.executable


def test_python_child_steps_use_project_interpreter(tmp_path, monkeypatch):
    """The resolved interpreter must actually drive the python steps (pytest/validators),
    not just exist as a helper — otherwise the bypass root cause survives."""
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    py = _make_venv(tmp_path)
    # minimal project shape so steps are emitted
    (tmp_path / "test_smoke.py").write_text("def test_ok():\n    assert True\n")
    (tmp_path / "validators").mkdir()
    (tmp_path / "validators" / "run_all.py").write_text("")
    (tmp_path / "validators" / "validate_module_size.py").write_text("")
    steps = gw._available_steps(tmp_path, {})
    py_cmds = [
        s.cmd
        for name, s in steps.items()
        if name in ("python-tests", "validators", "module-size")
    ]
    assert py_cmds, "expected python child steps to be emitted"
    for cmd in py_cmds:
        assert cmd[0] == str(py), f"step {cmd} did not use the project interpreter"
