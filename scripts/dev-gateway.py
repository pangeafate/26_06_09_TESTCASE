#!/usr/bin/env python3
"""Local-first development gateway.

This is the portable entry point hooks and humans should run before code leaves
the machine. It intentionally detects common runtime checks instead of assuming
a specific language stack.

Stages:
  pre-commit  Fast checks only: invariant lint and module-size/god-file sensor.
  pre-push    Full local gate: detected runtime checks plus validators.
  manual      Same as pre-push, for explicit local runs.
  ci          Same as pre-push; CI is an alerting backstop, not the source of truth.

Bypass:
  DEV_GATEWAY_BYPASS=1 DEV_GATEWAY_BYPASS_REASON=... DEV_GATEWAY_BYPASS_APPROVED_BY=...

The bypass is narrow and audited. It cannot protect against `git --no-verify`,
because Git skips hooks before this script can run; server-side CI should still
run the gateway as an alerting backstop for that case.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


DEFAULT_TIMEOUT_S = 300
FAST_STEPS = ("lint-invariants", "module-size")
FULL_STEPS = (
    "npm-typecheck",
    "npm-lint",
    "shellcheck",
    "python-tests",
    "npm-test",
    "lint-invariants",
    "module-size",
    "validators",
)


@dataclass(frozen=True)
class Step:
    name: str
    cmd: list[str]
    timeout_s: int = DEFAULT_TIMEOUT_S


def _load_config(project_root: Path) -> dict:
    path = project_root / ".validators.yml"
    if not path.is_file() or yaml is None:
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _package_scripts(project_root: Path) -> set[str]:
    package = project_root / "package.json"
    if not package.is_file():
        return set()
    try:
        data = json.loads(package.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    scripts = data.get("scripts")
    if not isinstance(scripts, dict):
        return set()
    return {str(name) for name in scripts}


def _has_python_tests(project_root: Path) -> bool:
    for path in project_root.rglob("test_*.py"):
        if any(part in {".git", ".venv", "venv", "__pycache__"} for part in path.parts):
            continue
        return True
    return False


def _declares_pytest(project_root: Path) -> bool:
    pytest_files = ("pytest.ini", "tox.ini")
    if any((project_root / name).is_file() for name in pytest_files):
        return True
    pyproject = project_root / "pyproject.toml"
    if pyproject.is_file():
        try:
            content = pyproject.read_text(encoding="utf-8")
        except OSError:
            content = ""
        if "pytest" in content or "[tool.pytest" in content:
            return True
    requirements = project_root / "requirements.txt"
    if requirements.is_file():
        try:
            content = requirements.read_text(encoding="utf-8").lower()
        except OSError:
            content = ""
        if "pytest" in content:
            return True
    return False


def _has_shell_scripts(project_root: Path) -> bool:
    scripts_dir = project_root / "scripts"
    if not scripts_dir.is_dir():
        return False
    return any(path.is_file() and path.suffix == ".sh" for path in scripts_dir.rglob("*.sh"))


def _git_value(project_root: Path, args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _append_bypass_log(project_root: Path, stage: str, reason: str, approved_by: str) -> None:
    log = project_root / "workspace" / "gateway-bypass-log.txt"
    log.parent.mkdir(parents=True, exist_ok=True)
    iso = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    head_sha = _git_value(project_root, ["rev-parse", "HEAD"]) or "unknown"
    branch = _git_value(project_root, ["rev-parse", "--abbrev-ref", "HEAD"]) or "unknown"
    with log.open("a", encoding="utf-8") as fp:
        fp.write(
            f"{iso}\t{head_sha}\t{branch}\tstage={stage}\t"
            f"approved_by={approved_by}\treason={reason}\n"
        )


def _check_bypass(project_root: Path, stage: str) -> int | None:
    if os.environ.get("DEV_GATEWAY_BYPASS") != "1":
        return None
    reason = (os.environ.get("DEV_GATEWAY_BYPASS_REASON") or "").strip()
    approved_by = (os.environ.get("DEV_GATEWAY_BYPASS_APPROVED_BY") or "").strip()
    if not reason or not approved_by:
        print(
            "[gateway] BYPASS REJECTED: set DEV_GATEWAY_BYPASS_REASON and "
            "DEV_GATEWAY_BYPASS_APPROVED_BY.",
            file=sys.stderr,
        )
        return 1
    _append_bypass_log(project_root, stage, reason, approved_by)
    print("[gateway] BYPASS: operator-approved reason logged.", file=sys.stderr)
    return 0


def _step_timeout(config: dict, name: str, default: int) -> int:
    gateway = config.get("gateway")
    if not isinstance(gateway, dict):
        return default
    timeouts = gateway.get("timeouts")
    if not isinstance(timeouts, dict):
        return default
    try:
        return int(timeouts.get(name, default))
    except (TypeError, ValueError):
        return default


def _configured_steps(config: dict, stage: str, default: tuple[str, ...]) -> tuple[str, ...]:
    gateway = config.get("gateway")
    if not isinstance(gateway, dict):
        return default
    stages = gateway.get("stages")
    if not isinstance(stages, dict):
        return default
    value = stages.get(stage.replace("-", "_"))
    if not isinstance(value, list):
        return default
    return tuple(str(item) for item in value)


def _available_steps(project_root: Path, config: dict) -> dict[str, Step]:
    scripts = _package_scripts(project_root)
    steps: dict[str, Step] = {}

    if "typecheck" in scripts:
        steps["npm-typecheck"] = Step(
            "npm-typecheck",
            ["npm", "run", "typecheck"],
            _step_timeout(config, "npm-typecheck", 180),
        )
    if "lint" in scripts:
        steps["npm-lint"] = Step(
            "npm-lint",
            ["npm", "run", "lint"],
            _step_timeout(config, "npm-lint", 180),
        )
    if "test" in scripts:
        steps["npm-test"] = Step(
            "npm-test",
            ["npm", "test"],
            _step_timeout(config, "npm-test", 300),
        )

    if _has_python_tests(project_root):
        if _declares_pytest(project_root):
            cmd = [sys.executable, "-m", "pytest", "-q"]
        else:
            cmd = [sys.executable, "-m", "unittest", "discover", "-p", "test_*.py", "-v"]
        steps["python-tests"] = Step(
            "python-tests",
            cmd,
            _step_timeout(config, "python-tests", 300),
        )

    lint_script = project_root / "scripts" / "lint-invariants.sh"
    if lint_script.is_file():
        steps["lint-invariants"] = Step(
            "lint-invariants",
            ["bash", "scripts/lint-invariants.sh", "."],
            _step_timeout(config, "lint-invariants", 60),
        )

    module_size = project_root / "validators" / "validate_module_size.py"
    if module_size.is_file():
        steps["module-size"] = Step(
            "module-size",
            [sys.executable, "validators/validate_module_size.py", "."],
            _step_timeout(config, "module-size", 120),
        )

    run_all = project_root / "validators" / "run_all.py"
    if run_all.is_file():
        steps["validators"] = Step(
            "validators",
            [sys.executable, "validators/run_all.py", "."],
            _step_timeout(config, "validators", 300),
        )

    if shutil.which("shellcheck") and _has_shell_scripts(project_root):
        steps["shellcheck"] = Step(
            "shellcheck",
            ["shellcheck", "-S", "error", *sorted(
                path.as_posix()
                for path in (project_root / "scripts").rglob("*.sh")
                if path.is_file()
            )],
            _step_timeout(config, "shellcheck", 120),
        )

    return steps


def _run_step(step: Step, project_root: Path) -> int:
    if os.environ.get("DEV_GATEWAY_TEST_FAIL_STEP") == step.name:
        print(f"[gateway] FAIL: {step.name} (test-injected)", file=sys.stderr)
        return 1
    if os.environ.get("DEV_GATEWAY_TEST_NOOP_STEPS") == "1":
        print(f"[gateway] NOOP: {step.name}", file=sys.stderr)
        return 0

    print(f"[gateway] running {step.name}...", file=sys.stderr)
    start = time.time()
    try:
        result = subprocess.run(
            step.cmd,
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=step.timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        if exc.stdout:
            sys.stderr.write(exc.stdout if isinstance(exc.stdout, str) else exc.stdout.decode())
        if exc.stderr:
            sys.stderr.write(exc.stderr if isinstance(exc.stderr, str) else exc.stderr.decode())
        print(
            f"[gateway] TIMEOUT: {step.name} exceeded {step.timeout_s}s",
            file=sys.stderr,
        )
        return 124

    if result.stdout:
        sys.stderr.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    elapsed = time.time() - start
    if result.returncode != 0:
        print(
            f"[gateway] FAIL: {step.name} exited {result.returncode} ({elapsed:.1f}s)",
            file=sys.stderr,
        )
        return result.returncode
    print(f"[gateway] PASS: {step.name} ({elapsed:.1f}s)", file=sys.stderr)
    return 0


def _stage_default_steps(stage: str) -> tuple[str, ...]:
    if stage == "pre-commit":
        return FAST_STEPS
    return FULL_STEPS


def run_gateway(project_root: Path, stage: str) -> int:
    config = _load_config(project_root)
    gateway = config.get("gateway")
    if isinstance(gateway, dict) and gateway.get("enabled") is False:
        print("[gateway] disabled via .validators.yml", file=sys.stderr)
        return 0

    bypass = _check_bypass(project_root, stage)
    if bypass is not None:
        return bypass

    available = _available_steps(project_root, config)
    requested = _configured_steps(config, stage, _stage_default_steps(stage))

    ran = 0
    for name in requested:
        step = available.get(name)
        if step is None:
            print(f"[gateway] skip {name} (not detected)", file=sys.stderr)
            continue
        ran += 1
        rc = _run_step(step, project_root)
        if rc != 0:
            return rc

    if ran == 0:
        print("[gateway] no applicable checks detected", file=sys.stderr)
    else:
        print(f"[gateway] all {ran} applicable check(s) passed", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the local development gateway.")
    parser.add_argument(
        "project_root",
        nargs="?",
        default=".",
        type=Path,
        help="Project root to validate.",
    )
    parser.add_argument(
        "--stage",
        choices=["pre-commit", "pre-push", "manual", "ci"],
        default="manual",
        help="Gateway stage to run.",
    )
    args = parser.parse_args(argv)

    project_root = args.project_root.resolve()
    return run_gateway(project_root, args.stage)


if __name__ == "__main__":
    sys.exit(main())
