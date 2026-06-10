"""SP_015 — the hard-rule guard (advisory, but re-derived and non-forgeable).

The guard refuses a 44-doc record unless it RE-DERIVES 9/9 PASS from check_smoke's
machine JSON (hash-checked against the live corpus) AND a real MCP round-trip succeeds.
Stage-3 findings encoded: a human-typed `signed` flag gates nothing; a stale/edited proof
fails the hash check; and the refusal path constructs NO paid client and never imports the
record path.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _load_guard():
    spec = importlib.util.spec_from_file_location("full_run", ROOT / "scripts" / "full_run.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _corpus(tmp_path: Path):
    """A tiny fake corpus + a matching green proof JSON. Returns (root, uris, proof_path)."""
    root = tmp_path
    (root / "data").mkdir()
    uris = ["data/a.md", "data/b.md"]
    for u in uris:
        (root / u).write_text(f"content of {u}")
    g = _load_guard()
    fingerprint = g.corpus_fingerprint(root, uris)
    proof = {
        "docs": {u: {"verdict": "PASS"} for u in uris},
        "fingerprint": fingerprint,
        "signed_by": "operator",  # narrative only — must NOT be what gates
    }
    proof_path = root / "proof.json"
    proof_path.write_text(json.dumps(proof))
    return g, root, uris, proof_path


def test_refuses_when_proof_absent(tmp_path: Path) -> None:
    g = _load_guard()
    ok, reason = g.gate(tmp_path / "nope.json", tmp_path, mcp_check=lambda: True, uris=["data/a.md"])
    assert ok is False and "proof" in reason.lower()


def test_refuses_forged_signed_but_not_green(tmp_path: Path) -> None:
    g, root, uris, proof_path = _corpus(tmp_path)
    proof = json.loads(proof_path.read_text())
    proof["docs"]["data/a.md"]["verdict"] = "INCOMPLETE"  # forged "signed" but not actually green
    proof["signed"] = True
    proof_path.write_text(json.dumps(proof))
    ok, reason = g.gate(proof_path, root, mcp_check=lambda: True, uris=uris)
    assert ok is False, "a typed signed flag must not pass a non-green proof"


def test_refuses_stale_proof_hash_mismatch(tmp_path: Path) -> None:
    g, root, uris, proof_path = _corpus(tmp_path)
    (root / "data" / "a.md").write_text("the doc changed after the proof was written")
    ok, reason = g.gate(proof_path, root, mcp_check=lambda: True, uris=uris)
    assert ok is False and ("hash" in reason.lower() or "changed" in reason.lower())


def test_refuses_when_mcp_unreachable(tmp_path: Path) -> None:
    g, root, uris, proof_path = _corpus(tmp_path)
    ok, reason = g.gate(proof_path, root, mcp_check=lambda: False, uris=uris)
    assert ok is False and "mcp" in reason.lower()


def test_permits_when_proven_and_deployed(tmp_path: Path) -> None:
    g, root, uris, proof_path = _corpus(tmp_path)
    ok, reason = g.gate(proof_path, root, mcp_check=lambda: True, uris=uris)
    assert ok is True


def test_refusal_runs_no_record_and_imports_no_paid_path(tmp_path: Path) -> None:
    g = _load_guard()
    sys.modules.pop("helixpay.ingest.replay", None)
    calls = []
    rc = g.main(
        argv=["--proof", str(tmp_path / "absent.json"), "--corpus-root", str(tmp_path)],
        record_runner=lambda: calls.append("ran"),
        mcp_check=lambda: True,
        uris=["data/a.md"],
    )
    assert rc != 0, "refusal must be a non-zero exit"
    assert calls == [], "the paid record must NOT run on refusal"
    assert "helixpay.ingest.replay" not in sys.modules, "record path must be imported lazily (permit only)"


def test_default_record_runner_not_imported_on_refusal(tmp_path: Path) -> None:
    # the REAL default runner (not an injected stub) must stay unimported on refusal —
    # proving _default_record_runner's `import helixpay.ingest.replay` is genuinely lazy.
    g = _load_guard()
    sys.modules.pop("helixpay.ingest.replay", None)
    rc = g.main(
        argv=["--proof", str(tmp_path / "absent.json"), "--corpus-root", str(tmp_path)],
        mcp_check=lambda: True,
        uris=["data/a.md"],  # record_runner omitted → uses the real default
    )
    assert rc != 0
    assert "helixpay.ingest.replay" not in sys.modules


def test_permit_runs_record_once(tmp_path: Path) -> None:
    g, root, uris, proof_path = _corpus(tmp_path)
    calls = []
    rc = g.main(
        argv=["--proof", str(proof_path), "--corpus-root", str(root)],
        record_runner=lambda: calls.append("ran"),
        mcp_check=lambda: True,
        uris=uris,
    )
    assert rc == 0
    assert calls == ["ran"], "the governed record must run exactly once on permit"
