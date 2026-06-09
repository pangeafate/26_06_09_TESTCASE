"""SP_719 — _common.find_active_sprint behaviour + deploy.py parity.

Two guarantees:
  1. The robust resolver returns the git-HEAD SP-tagged open-plan
     sprint, NOT the first `**Current:**` in PROGRESS.md (the
     multi-agent bug). Plus closed-plan-skip, none, shallow/no-git
     fallback, tightened SP_\\d{2,} (prose `SP_NNN` not matched).
  2. NON-SKIPPABLE parity: `skills/dev-deploy/scripts/deploy.py`'s
     vendored `_read_active_sprint` produces byte-identical output to
     `_common.find_active_sprint` across the matrix — so the lockfile
     WRITER (validate_doc_freshness→_common) and the Stage-7 lockfile
     READER (deploy.py vendored) agree by construction (HIGH-1).
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_HERE))

import _common  # noqa: E402

_DEPLOY_PY = _REPO / "skills" / "dev-deploy" / "scripts" / "deploy.py"


def _load_deploy_resolver():
    spec = importlib.util.spec_from_file_location("_sp719_deploy", _DEPLOY_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._read_active_sprint


def _git(root: Path, *a: str) -> None:
    subprocess.run(["git", *a], cwd=root, check=True, capture_output=True, text=True)


def _mk_repo(tmp: Path) -> Path:
    r = tmp / "proj"
    (r / "workspace" / "sprints").mkdir(parents=True)
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    (r / "seed.txt").write_text("x")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "seed", "--allow-empty")
    return r


def _plan(r: Path, sid: str, status: str) -> None:
    (r / "workspace" / "sprints" / f"{sid}_x.md").write_text(
        f"---\nsprint_id: {sid}\nstatus: {status}\n---\n# {sid}\n"
    )


def _progress(r: Path, *current_ids: str) -> None:
    body = "# Progress\n\n## Active Sprint\n\n"
    for cid in current_ids:
        body += f"**Current:** {cid} — blah\n\n"
    (r / "PROGRESS.md").write_text(body)


def test_resolves_git_head_over_first_current(tmp_path: Path) -> None:
    # PROGRESS first **Current:** is a parallel agent's sprint (SP_900);
    # the in-flight one (SP_901) is the newest SP-tagged HEAD commit.
    r = _mk_repo(tmp_path)
    _plan(r, "SP_900", "Complete")
    _plan(r, "SP_901", "In Progress")
    _progress(r, "SP_900", "SP_902")
    (r / "f.txt").write_text("1")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "feat(SP_901): real work", "--allow-empty")
    assert _common.find_active_sprint(r) == "SP_901"  # NOT SP_900


def test_closed_plan_commit_skipped_then_fallback(tmp_path: Path) -> None:
    r = _mk_repo(tmp_path)
    _plan(r, "SP_910", "Complete")  # newest commit tags a CLOSED sprint
    _plan(r, "SP_911", "Planning")
    _progress(r, "SP_911")
    (r / "f.txt").write_text("1")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "docs(SP_910): closeout", "--allow-empty")
    # SP_910 closed → skip; no other open SP-tagged commit → PROGRESS
    # fallback resolves SP_911.
    assert _common.find_active_sprint(r) == "SP_911"


def test_prose_placeholder_not_matched(tmp_path: Path) -> None:
    r = _mk_repo(tmp_path)
    _progress(r, "SP_NNN")  # literal placeholder must NOT resolve
    assert _common.find_active_sprint(r) is None


def test_none_when_nothing(tmp_path: Path) -> None:
    r = _mk_repo(tmp_path)
    (r / "PROGRESS.md").write_text("# Progress\nno active marker\n")
    assert _common.find_active_sprint(r) is None


def test_no_git_falls_back_to_progress(tmp_path: Path) -> None:
    r = tmp_path / "nogit"
    (r / "workspace" / "sprints").mkdir(parents=True)
    _plan(r, "SP_920", "In Progress")
    _progress(r, "SP_920")
    # no .git → git scan rc!=0 → PROGRESS fallback
    assert _common.find_active_sprint(r) == "SP_920"


def test_deploy_py_vendored_parity(tmp_path: Path) -> None:
    """deploy.py vendored resolver == _common across the matrix. The
    per-test body is the strong guard; a COLLECTION-TIME module-level
    parity assertion (bottom of this file) is the genuine non-skippable
    backstop — it runs when pytest imports this module and cannot be
    suppressed by a per-test skip/xfail marker (Stage-5 iter-1: the old
    `assert True` sentinel was dead code — a skip marker aborts before
    the body — so the real anti-skip mechanism is module-import-time)."""
    deploy_resolver = _load_deploy_resolver()
    scenarios = []

    r1 = _mk_repo(tmp_path / "a")
    _plan(r1, "SP_930", "Complete")
    _plan(r1, "SP_931", "In Progress")
    _progress(r1, "SP_930", "SP_932")
    (r1 / "f").write_text("1")
    _git(r1, "add", "-A")
    _git(r1, "commit", "-qm", "fix(SP_931): x", "--allow-empty")
    scenarios.append(r1)

    r2 = _mk_repo(tmp_path / "b")
    _progress(r2, "SP_NNN")
    scenarios.append(r2)

    r3 = tmp_path / "c"
    (r3 / "workspace" / "sprints").mkdir(parents=True)
    _plan(r3, "SP_940", "In Progress")
    _progress(r3, "SP_940")
    scenarios.append(r3)

    for root in scenarios:
        assert _common.find_active_sprint(root) == deploy_resolver(root), (
            f"parity divergence at {root}"
        )


# ── COLLECTION-TIME non-skippable parity backstop (Stage-5 iter-1) ──
# Runs when pytest IMPORTS this module to collect tests; a per-test
# `@pytest.mark.skip`/`xfail` cannot suppress module import, so the
# deploy.py vendored resolver can never silently diverge from _common
# even if every test function above is skipped. Cheap (no-git tmp dir →
# both resolvers exercise the PROGRESS fallback path).
def _collection_time_parity_backstop() -> None:
    # Covers BOTH resolver branches so the non-skippable guarantee is
    # not fallback-only (Stage-5 iter-2 MED-1): scenario A = no-`.git`
    # tmp dir → PROGRESS fallback; scenario B = real git repo whose
    # newest commit subject is SP-tagged with an open plan → git-HEAD
    # PRIMARY path. Fail-closed by design: a tempfile/git/deploy-load
    # error here aborts collection of the whole module (the non-skip
    # guarantee is preserved over a transiently-renamed deploy.py — a
    # known, intentional failure mode, not a flake).
    import tempfile

    _dep = _load_deploy_resolver()
    _msg = (
        "SP_719 deploy-gate parity backstop FAILED: deploy.py vendored "
        "_read_active_sprint diverged from validators/_common.py "
        "find_active_sprint — the Stage-7 lockfile reader/writer would "
        "disagree. Re-sync the vendored copy (SOURCE OF TRUTH: "
        "validators/_common.py:find_active_sprint, SP_719)."
    )
    with tempfile.TemporaryDirectory() as _d:
        # A — PROGRESS fallback path
        _a = Path(_d) / "fallback"
        (_a / "workspace" / "sprints").mkdir(parents=True)
        (_a / "workspace" / "sprints" / "SP_999_x.md").write_text(
            "---\nsprint_id: SP_999\nstatus: In Progress\n---\n# SP_999\n"
        )
        (_a / "PROGRESS.md").write_text(
            "# Progress\n\n## Active Sprint\n\n**Current:** SP_999 — b\n"
        )
        assert _common.find_active_sprint(_a) == _dep(_a) == "SP_999", _msg

        # B — git-HEAD PRIMARY path (real repo; newest commit SP-tagged,
        # open plan; PROGRESS first **Current:** is a DIFFERENT sprint so
        # a fallback-only or first-match resolver would mis-resolve).
        _b = Path(_d) / "primary"
        (_b / "workspace" / "sprints").mkdir(parents=True)
        (_b / "workspace" / "sprints" / "SP_998_x.md").write_text(
            "---\nsprint_id: SP_998\nstatus: In Progress\n---\n# SP_998\n"
        )
        (_b / "workspace" / "sprints" / "SP_997_x.md").write_text(
            "---\nsprint_id: SP_997\nstatus: Complete\n---\n# SP_997\n"
        )
        (_b / "PROGRESS.md").write_text(
            "# Progress\n\n## Active Sprint\n\n**Current:** SP_997 — old\n"
        )
        for _a2 in (
            ("init", "-q"), ("config", "user.email", "t@t"),
            ("config", "user.name", "t"), ("add", "-A"),
            ("commit", "-qm", "feat(SP_998): primary-path parity", "--allow-empty"),
        ):
            subprocess.run(["git", *_a2], cwd=_b, check=True,
                           capture_output=True, text=True)
        assert _common.find_active_sprint(_b) == _dep(_b) == "SP_998", _msg


_collection_time_parity_backstop()
