"""Tests for scripts/dev-gateway.py."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "scripts" / "dev-gateway.py"
PRE_PUSH = ROOT / "scripts" / "git-hooks" / "pre-push.py"


def run_gateway(project: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GATEWAY), str(project), *args],
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    )


def init_repo(project: Path) -> str:
    subprocess.run(["git", "init", "--quiet", "-b", "main", str(project)], check=True)
    subprocess.run(["git", "-C", str(project), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(project), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(project), "config", "commit.gpgsign", "false"], check=True)
    (project / "README.md").write_text("# Test\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(project), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(project), "commit", "--quiet", "-m", "init"], check=True)
    return subprocess.check_output(["git", "-C", str(project), "rev-parse", "HEAD"], text=True).strip()


def install_gateway_fixture(project: Path) -> None:
    scripts = project / "scripts"
    validators = project / "validators"
    scripts.mkdir()
    validators.mkdir()
    (scripts / "dev-gateway.py").write_text(GATEWAY.read_text(encoding="utf-8"), encoding="utf-8")
    (validators / "validate_module_size.py").write_text(
        "import sys\nprint('module-size fixture')\nsys.exit(0)\n",
        encoding="utf-8",
    )


def test_pre_commit_stage_runs_module_size_when_detected(tmp_path: Path) -> None:
    install_gateway_fixture(tmp_path)
    result = run_gateway(
        tmp_path,
        "--stage",
        "pre-commit",
        env={"DEV_GATEWAY_TEST_NOOP_STEPS": "1"},
    )
    assert result.returncode == 0
    assert "NOOP: module-size" in result.stderr


def test_gateway_injected_failure_blocks(tmp_path: Path) -> None:
    install_gateway_fixture(tmp_path)
    result = run_gateway(
        tmp_path,
        "--stage",
        "pre-commit",
        env={"DEV_GATEWAY_TEST_FAIL_STEP": "module-size"},
    )
    assert result.returncode == 1
    assert "FAIL: module-size" in result.stderr


def test_gateway_bypass_requires_operator_approval(tmp_path: Path) -> None:
    install_gateway_fixture(tmp_path)
    result = run_gateway(
        tmp_path,
        "--stage",
        "pre-commit",
        env={"DEV_GATEWAY_BYPASS": "1", "DEV_GATEWAY_BYPASS_REASON": "testing"},
    )
    assert result.returncode == 1
    assert "BYPASS REJECTED" in result.stderr


def test_gateway_bypass_logs_reason_and_operator(tmp_path: Path) -> None:
    init_repo(tmp_path)
    install_gateway_fixture(tmp_path)
    result = run_gateway(
        tmp_path,
        "--stage",
        "pre-commit",
        env={
            "DEV_GATEWAY_BYPASS": "1",
            "DEV_GATEWAY_BYPASS_REASON": "testing",
            "DEV_GATEWAY_BYPASS_APPROVED_BY": "operator",
        },
    )
    assert result.returncode == 0
    log = tmp_path / "workspace" / "gateway-bypass-log.txt"
    assert log.is_file()
    content = log.read_text(encoding="utf-8")
    assert "approved_by=operator" in content
    assert "reason=testing" in content


def test_pre_push_delegates_to_gateway_when_present(tmp_path: Path) -> None:
    head = init_repo(tmp_path)
    install_gateway_fixture(tmp_path)
    refs = f"refs/heads/main {head} refs/heads/main {head}\n"
    result = subprocess.run(
        [sys.executable, str(PRE_PUSH)],
        input=refs,
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={**os.environ, "DEV_GATEWAY_TEST_NOOP_STEPS": "1"},
    )
    assert result.returncode == 0
    assert "running dev-gateway" in result.stderr
    assert "NOOP: module-size" in result.stderr
