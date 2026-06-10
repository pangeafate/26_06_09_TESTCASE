"""Unit tests for scripts/prod_seed.sh (SP_016, TDD).

These run offline (no DB, no network, no paid calls) and verify:
  - The script exists and is syntactically valid bash.
  - The dry-run path asserts the correct operation ORDER:
      CREATE EXTENSION vector (via migration) BEFORE pg_restore.
  - The script REFUSES (exits non-zero) if SP015_proof.md has not been filled in
    (i.e. still contains the TEMPLATE marker) — no ungated production seed.
  - The script never echoes DATABASE_URL or any DSN/password.
  - The script uses idempotent restore flags (--clean --if-exists) to be safe
    on a pre-existing DB.

These tests inspect the script text and run it with --dry-run; they never
actually connect to a database.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "prod_seed.sh"
SP015_PROOF = ROOT / "workspace" / "acceptance" / "SP015_proof.md"


def _script_text() -> str:
    assert SCRIPT.exists(), f"scripts/prod_seed.sh not found at {SCRIPT}"
    return SCRIPT.read_text(encoding="utf-8")


def _signed_proof(tmp_path: Path) -> Path:
    p = tmp_path / "SP015_proof.md"
    p.write_text("# SP015 proof\n9/9 PASS, signed by operator.\n", encoding="utf-8")
    return p


def _green_machine(tmp_path: Path) -> Path:
    p = tmp_path / "SP015_smoke_result.json"
    p.write_text(json.dumps({"all_green": True,
                             "docs": {"a": {"verdict": "PASS"}, "b": {"verdict": "PASS"}}}),
                 encoding="utf-8")
    return p


def _run_safe_db_host(url: str) -> str:
    """Run the script's _safe_db_host function in ISOLATION (no whole-script exec, no .env)."""
    m = re.search(r"(_safe_db_host\(\)\s*\{.*?\n\})", _script_text(), re.DOTALL)
    assert m, "could not extract _safe_db_host() from prod_seed.sh"
    r = subprocess.run(["bash", "-c", f'{m.group(1)}\n_safe_db_host "$1"', "_", url],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


# ---------------------------------------------------------------------------
# Existence and syntax
# ---------------------------------------------------------------------------

def test_script_exists():
    assert SCRIPT.exists(), "scripts/prod_seed.sh must exist"


def test_script_syntax_valid():
    """bash -n must pass (syntax check without execution)."""
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"scripts/prod_seed.sh has bash syntax errors:\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# Ordering invariant: CREATE EXTENSION vector before restore
# ---------------------------------------------------------------------------

def test_migration_before_restore_in_script():
    """The script must run the migration (which creates the vector extension)
    BEFORE executing pg_restore.  We assert this by checking that the migration
    call appears earlier in the file than the pg_restore call."""
    text = _script_text()
    assert "helixpay.db.migrate" in text or "migrate" in text, (
        "prod_seed.sh must invoke the migration step"
    )
    assert "pg_restore" in text, "prod_seed.sh must invoke pg_restore"

    # Find line numbers
    lines = text.splitlines()
    migrate_line = next(
        (i for i, l in enumerate(lines) if "migrate" in l and not l.strip().startswith("#")),
        None,
    )
    restore_line = next(
        (i for i, l in enumerate(lines) if "pg_restore" in l and not l.strip().startswith("#")),
        None,
    )
    assert migrate_line is not None, "Could not find migration invocation"
    assert restore_line is not None, "Could not find pg_restore invocation"
    assert migrate_line < restore_line, (
        f"Migration (line {migrate_line}) must come BEFORE pg_restore (line {restore_line})"
    )


# ---------------------------------------------------------------------------
# SP015 proof guard — refuses if proof is a template / unsigned
# ---------------------------------------------------------------------------

def test_script_checks_sp015_proof():
    """prod_seed.sh must reference SP015_proof.md to guard against ungated seeding."""
    text = _script_text()
    assert "SP015_proof" in text or "SP015" in text, (
        "prod_seed.sh must check for a signed SP015_proof.md before proceeding"
    )


def test_script_refuses_template_proof(tmp_path):
    """dry-run with a template (unsigned) SP015_proof.md must exit non-zero.
    The template contains 'TEMPLATE' in its header."""
    # Copy the real template proof into tmp
    proof_src = SP015_PROOF
    assert proof_src.exists(), "SP015_proof.md template must exist"
    proof_text = proof_src.read_text(encoding="utf-8")
    assert "TEMPLATE" in proof_text, (
        "The proof file must contain 'TEMPLATE' marker (pre-condition for this test)"
    )

    result = subprocess.run(
        ["bash", str(SCRIPT), "--dry-run", "--proof", str(proof_src)],
        capture_output=True,
        text=True,
        env={**os.environ, "DRY_RUN": "1"},
    )
    assert result.returncode != 0, (
        "prod_seed.sh must refuse (exit non-zero) when SP015_proof.md is still a template\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# Secret handling — must not echo DATABASE_URL / DSN
# ---------------------------------------------------------------------------

# Matches `echo ... $SECRET` / `${SECRET}` — i.e. printing the *expanded value* of a
# secret env var. It deliberately does NOT match echoing the bare variable NAME as
# diagnostic text (e.g. `echo "REMOTE_DATABASE_URL=postgres://user:pass@host..."`,
# prod_seed.sh:165), which is a usage hint, not a leak. `$` (optional `{`) must sit
# immediately before the name for it to be an expansion.
_SECRET_ECHO = re.compile(r"echo[^\n]*\$\{?(DATABASE_URL|LOCAL_DB_URL|POSTGRES_PASSWORD)\b")


def test_script_does_not_echo_secret_env_values():
    """prod_seed.sh must never echo the expanded value of a secret env var.
    Comment lines are excluded; only a real `echo ... $SECRET` expansion is a leak."""
    code = "\n".join(l for l in _script_text().splitlines() if not l.strip().startswith("#"))
    leak = _SECRET_ECHO.search(code)
    if leak:
        pytest.fail(
            f"prod_seed.sh must not echo a secret env value (secrets must never be logged): "
            f"{leak.group(0)!r}"
        )


# ---------------------------------------------------------------------------
# Restore flags — must use --clean --if-exists for idempotency
# ---------------------------------------------------------------------------

def test_restore_uses_clean_and_if_exists():
    """pg_restore must include --clean and --if-exists so the restore is safe
    on a non-empty database (idempotent on repeated runs)."""
    text = _script_text()
    # Find the pg_restore line(s)
    restore_lines = [
        l for l in text.splitlines()
        if "pg_restore" in l and not l.strip().startswith("#")
    ]
    assert restore_lines, "prod_seed.sh must contain a pg_restore invocation"
    restore_cmd = " ".join(restore_lines)
    assert "--clean" in restore_cmd, (
        "pg_restore must use --clean to drop existing objects before restore"
    )
    assert "--if-exists" in restore_cmd, (
        "pg_restore must use --if-exists to avoid errors when objects don't exist yet"
    )


# ---------------------------------------------------------------------------
# C1 — pg_restore must use a REAL connection flag (--dburl does not exist)
# ---------------------------------------------------------------------------

def test_restore_uses_valid_dbname_flag_not_dburl():
    """Stage-5 C1: `pg_restore --dburl=...` is not a valid flag — it aborts every restore.
    The connection must go via --dbname (which accepts a URI) or -d."""
    code = "\n".join(l for l in _script_text().splitlines() if not l.strip().startswith("#"))
    assert "--dburl" not in code, "pg_restore has no --dburl option; the restore would abort"
    assert "--dbname=" in code or re.search(r"\s-d\s", code), (
        "pg_restore must connect via --dbname=/-d (a URI is accepted there)"
    )


# ---------------------------------------------------------------------------
# H1 — _safe_db_host must never leak a password (even one containing '@')
# ---------------------------------------------------------------------------

def test_safe_db_host_does_not_leak_at_sign_password():
    out = _run_safe_db_host("postgres://user:p@ss@dbhost:5432/helixpay")
    assert out == "dbhost:5432/helixpay"
    assert "p@ss" not in out and "ss@" not in out, f"password leaked: {out!r}"


def test_safe_db_host_handles_ipv6_passwordless_and_colon():
    assert _run_safe_db_host("postgresql://u:pw@[2001:db8::1]:5432/db") == "2001:db8::1:5432/db"
    assert _run_safe_db_host("postgres://localhost/helixpay") == "localhost/helixpay"
    # colon-in-password must not leak either
    out = _run_safe_db_host("postgres://user:p:ss@host:5432/db")
    assert out == "host:5432/db" and "p:ss" not in out


# ---------------------------------------------------------------------------
# H2 — the seed must be bound to the MACHINE proof (all_green), not just markdown
# ---------------------------------------------------------------------------

def test_refuses_when_machine_proof_missing(tmp_path):
    """A signed markdown proof is NOT enough — the machine JSON must exist (Stage-5 H2)."""
    proof = _signed_proof(tmp_path)
    r = subprocess.run(
        ["bash", str(SCRIPT), "--dry-run", "--proof", str(proof),
         "--smoke-result", str(tmp_path / "nonexistent.json")],
        capture_output=True, text=True,
    )
    assert r.returncode != 0, "must refuse when the machine proof is absent"
    assert "machine proof" in (r.stdout + r.stderr).lower()


def test_refuses_when_machine_proof_not_green(tmp_path):
    proof = _signed_proof(tmp_path)
    mp = tmp_path / "result.json"
    mp.write_text(json.dumps({"all_green": False, "docs": {"a": {"verdict": "FAIL"}}}))
    r = subprocess.run(
        ["bash", str(SCRIPT), "--dry-run", "--proof", str(proof), "--smoke-result", str(mp)],
        capture_output=True, text=True,
    )
    assert r.returncode != 0, "must refuse when the machine proof is not all-green"


def test_green_machine_proof_passes_the_gate_in_dry_run(tmp_path):
    """With a signed markdown + green machine JSON + DB URLs set, --dry-run reaches the
    dry-run summary (exit 0) — proving 0b is a real gate that opens only when proven."""
    proof = _signed_proof(tmp_path)
    mp = _green_machine(tmp_path)
    r = subprocess.run(
        ["bash", str(SCRIPT), "--dry-run", "--proof", str(proof), "--smoke-result", str(mp)],
        capture_output=True, text=True,
        env={**os.environ,
             "DATABASE_URL": "postgres://u:pw@localhost:5432/helixpay",
             "REMOTE_DATABASE_URL": "postgres://u:pw@remote:5432/helixpay"},
    )
    # NOTE: if a repo-root .env defines DATABASE_URL it is sourced AFTER our env — but the
    # gate (0b) and dry-run exit happen regardless of which DSN is used, so exit 0 holds.
    assert r.returncode == 0, f"dry-run should pass with a green proof:\n{r.stdout}\n{r.stderr}"
