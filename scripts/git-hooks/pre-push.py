#!/usr/bin/env python3
"""Generic pre-push gauntlet.

Runs before pushes to `main` or to branches tracking `origin/main`.

Bypass:
    DEV_PREPUSH_BYPASS=1 DEV_PREPUSH_BYPASS_REASON=<reason> \
      DEV_PREPUSH_BYPASS_APPROVED_BY=<operator> git push

Test hooks:
    DEV_PREPUSH_TEST_FAIL_STEP=<step>
    DEV_PREPUSH_TEST_NOOP_STEPS=1
    DEV_PREPUSH_TEST_TIMEOUT_STEP=<step>
"""
from __future__ import annotations

import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ZERO_SHA = "0" * 40
LOCK_TIMEOUT_S = 600
LOCK_RETRY_INTERVAL_S = 2
DEFAULT_STEP_TIMEOUT_S = 300
STEP_TIMEOUTS_S = {
    "typecheck": 180,
    "lint-invariants": 60,
    "dev-gateway": 600,
    "validators/run_all.py": 300,
    "npm test": 300,
}
GIT_LOCAL_ENV_FALLBACK = {
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_DIR",
    "GIT_INDEX_FILE",
    "GIT_NAMESPACE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_PREFIX",
    "GIT_WORK_TREE",
    "GIT_IMPLICIT_WORK_TREE",
    "GIT_INTERNAL_SUPER_PREFIX",
}


def _run(
    cmd: list[str],
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        capture_output=True,
        text=True,
    )


def _repo_root() -> Path:
    result = _run(["git", "rev-parse", "--show-toplevel"])
    if result.returncode != 0:
        print("[pre-push] FATAL: not inside a git repo", file=sys.stderr)
        sys.exit(1)
    return Path(result.stdout.strip())


def _git_local_env_names(repo: Path) -> set[str]:
    result = _run(["git", "rev-parse", "--local-env-vars"], cwd=repo)
    if result.returncode != 0:
        return set(GIT_LOCAL_ENV_FALLBACK)
    names = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    return names | GIT_LOCAL_ENV_FALLBACK


def _child_env(repo: Path) -> dict[str, str]:
    env = {**os.environ}
    for name in _git_local_env_names(repo):
        env.pop(name, None)
    return env


def _parse_stdin() -> list[tuple[str, str, str, str]]:
    refs: list[tuple[str, str, str, str]] = []
    for line in sys.stdin:
        parts = line.strip().split()
        if len(parts) == 4:
            refs.append((parts[0], parts[1], parts[2], parts[3]))
    return refs


def _should_run_gauntlet(refs: list[tuple[str, str, str, str]], repo: Path) -> bool:
    for local_ref, _local_sha, remote_ref, _remote_sha in refs:
        if remote_ref.startswith("refs/tags/"):
            continue
        if remote_ref == "refs/heads/main":
            return True
        if not local_ref.startswith("refs/heads/"):
            continue
        local_branch = local_ref[len("refs/heads/") :]
        merge_cfg = _run(
            ["git", "config", "--get", f"branch.{local_branch}.merge"], cwd=repo
        )
        remote_cfg = _run(
            ["git", "config", "--get", f"branch.{local_branch}.remote"], cwd=repo
        )
        if (
            merge_cfg.stdout.strip() == "refs/heads/main"
            and remote_cfg.stdout.strip() == "origin"
        ):
            return True
    return False


def _package_scripts(repo: Path) -> set[str]:
    package = repo / "package.json"
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


def _run_step_command(
    name: str,
    cmd: list[str],
    cwd: Path,
    env: dict[str, str],
    timeout_s: int,
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
        return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = proc.communicate()
        stderr = (stderr or "") + (
            f"[pre-push] TIMEOUT: {name} exceeded {timeout_s}s; "
            "killed process group\n"
        )
        return subprocess.CompletedProcess(cmd, 124, stdout or "", stderr)


def _check_bypass(repo: Path) -> int | None:
    if os.environ.get("DEV_PREPUSH_BYPASS") != "1":
        return None
    reason = (os.environ.get("DEV_PREPUSH_BYPASS_REASON") or "").strip()
    approved_by = (os.environ.get("DEV_PREPUSH_BYPASS_APPROVED_BY") or "").strip()
    if not reason or not approved_by:
        print(
            "[pre-push] BYPASS REJECTED: set DEV_PREPUSH_BYPASS_REASON and "
            "DEV_PREPUSH_BYPASS_APPROVED_BY to non-empty values.",
            file=sys.stderr,
        )
        return 1
    log = repo / "workspace" / "git-bypass-log.txt"
    log.parent.mkdir(parents=True, exist_ok=True)
    iso = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    head_sha = _run(["git", "rev-parse", "HEAD"], cwd=repo).stdout.strip()
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo).stdout.strip()
    with log.open("a", encoding="utf-8") as fp:
        fp.write(f"{iso}\t{head_sha}\t{branch}\tapproved_by={approved_by}\treason={reason}\n")
    print("[pre-push] BYPASS: reason logged.", file=sys.stderr)
    return 0


def _step(
    name: str,
    cmd: list[str],
    cwd: Path,
    env: dict[str, str],
    recovery: str = "",
) -> int:
    if os.environ.get("DEV_PREPUSH_TEST_ASSERT_CLEAN_GIT_ENV_STEP") == name:
        dirty = sorted(key for key in GIT_LOCAL_ENV_FALLBACK if env.get(key))
        if dirty:
            print(
                f"[pre-push] FAIL: {name} inherited local git env: {dirty}",
                file=sys.stderr,
            )
            return 1
    if os.environ.get("DEV_PREPUSH_TEST_TIMEOUT_STEP") == name:
        marker = os.environ.get("DEV_PREPUSH_TEST_TIMEOUT_MARKER", "")
        child_code = (
            "import pathlib,sys,time; "
            "time.sleep(5); "
            "pathlib.Path(sys.argv[1]).write_text('survived')"
        )
        parent_code = (
            "import subprocess,sys,time; "
            "subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[2]]); "
            "time.sleep(60)"
        )
        cmd = [sys.executable, "-c", parent_code, child_code, marker]
    if os.environ.get("DEV_PREPUSH_TEST_FAIL_STEP") == name:
        print(f"[pre-push] FAIL: {name} (test-injected)", file=sys.stderr)
        return 1
    if os.environ.get("DEV_PREPUSH_TEST_NOOP_STEPS") == "1":
        print(f"[pre-push] NOOP: {name} (test-injected)", file=sys.stderr)
        return 0

    print(f"[pre-push] running {name}...", file=sys.stderr)
    timeout_s = int(
        os.environ.get(
            "DEV_PREPUSH_TEST_STEP_TIMEOUT_S",
            str(STEP_TIMEOUTS_S.get(name, DEFAULT_STEP_TIMEOUT_S)),
        )
    )
    result = _run_step_command(name, cmd, cwd=cwd, env=env, timeout_s=timeout_s)
    if result.stdout:
        sys.stderr.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    if result.returncode != 0:
        print(f"[pre-push] FAIL: {name} exited {result.returncode}", file=sys.stderr)
        if recovery:
            print(f"[pre-push] RECOVERY: {recovery}", file=sys.stderr)
        return result.returncode
    return 0


def _run_gauntlet(repo: Path) -> int:
    env = _child_env(repo)
    gateway = repo / "scripts" / "dev-gateway.py"
    if gateway.is_file():
        return _step(
            "dev-gateway",
            ["python3", "scripts/dev-gateway.py", ".", "--stage", "pre-push"],
            repo,
            env,
            recovery="fix the local gateway failure and re-push",
        )

    scripts = _package_scripts(repo)

    if "typecheck" in scripts:
        rc = _step(
            "typecheck",
            ["npm", "run", "typecheck"],
            repo,
            env,
            recovery="fix the typecheck error and re-push",
        )
        if rc != 0:
            return rc
    else:
        print("[pre-push] skipping typecheck (no npm script)", file=sys.stderr)

    if (repo / "scripts" / "lint-invariants.sh").is_file():
        rc = _step(
            "lint-invariants",
            ["bash", "scripts/lint-invariants.sh", "."],
            repo,
            env,
            recovery="fix the invariant violation and re-push",
        )
        if rc != 0:
            return rc

    if (repo / "validators" / "run_all.py").is_file():
        rc = _step(
            "validators/run_all.py",
            ["python3", "validators/run_all.py", "."],
            repo,
            env,
            recovery="see the failing validator's stderr",
        )
        if rc != 0:
            return rc

    if "test" in scripts:
        rc = _step(
            "npm test",
            ["npm", "test"],
            repo,
            env,
            recovery="fix the failing test and re-push",
        )
        if rc != 0:
            return rc
    else:
        print("[pre-push] skipping npm test (no npm script)", file=sys.stderr)

    return 0


def main() -> int:
    repo = _repo_root()
    refs = _parse_stdin()
    if not refs:
        return 0
    if not _should_run_gauntlet(refs, repo):
        print("[pre-push] non-main push detected; skipping gauntlet", file=sys.stderr)
        return 0

    bypass_rc = _check_bypass(repo)
    if bypass_rc is not None:
        return bypass_rc

    git_path = _run(["git", "rev-parse", "--git-path", "dev-rules-prepush.lock"], cwd=repo)
    lock_path_str = git_path.stdout.strip() or ".git/dev-rules-prepush.lock"
    lock_path = (
        Path(lock_path_str) if Path(lock_path_str).is_absolute() else repo / lock_path_str
    )
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    deadline = time.time() + LOCK_TIMEOUT_S
    with open(lock_path, "w", encoding="utf-8") as lock_fp:
        while True:
            try:
                fcntl.flock(lock_fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.time() >= deadline:
                    print("[pre-push] another push is in flight; retry later", file=sys.stderr)
                    return 1
                time.sleep(LOCK_RETRY_INTERVAL_S)
        try:
            return _run_gauntlet(repo)
        finally:
            fcntl.flock(lock_fp.fileno(), fcntl.LOCK_UN)


if __name__ == "__main__":
    sys.exit(main())
