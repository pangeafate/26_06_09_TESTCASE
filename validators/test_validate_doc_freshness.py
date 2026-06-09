"""Tests for validate_doc_freshness.py (SP_002)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import validate_doc_freshness as v


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _progress(sprint_id: str) -> str:
    return textwrap.dedent(
        f"""\
        ---
        status: living
        last-reconciled: 2026-04-14
        ---

        # Progress

        ## Active Sprint

        **Current:** {sprint_id}
        """
    )


def _validators_yml_enabled() -> str:
    return textwrap.dedent(
        """\
        doc_freshness:
          enabled: true
          source_roots: [src, validators]
          meta_docs:
            - PROGRESS.md
            - FEATURE_LIST.md
            - DATA_SCHEMA.md
            - CODEBASE_STRUCTURE.md
            - USER_STORIES.md
          exempt_paths: ["**/test_*.py"]
        """
    )


def _sprint_plan_fm(
    sprint_id: str = "SP_042",
    features: str = "[]",
    user_stories: str = "[]",
    schema_touched: str = "false",
    structure_touched: str = "false",
    status: str = "Planning",
) -> str:
    return textwrap.dedent(
        f"""\
        ---
        sprint_id: {sprint_id}
        features: {features}
        user_stories: {user_stories}
        schema_touched: {schema_touched}
        structure_touched: {structure_touched}
        status: {status}
        ---

        # {sprint_id}
        """
    )


class GitRepo:
    def __init__(self, root: Path):
        self.root = root

    @classmethod
    def make(
        cls,
        tmp_path: Path,
        subdir: str = "proj",
        initial_branch: str = "main",
    ) -> "GitRepo":
        root = tmp_path / subdir
        root.mkdir()
        env = cls._git_env()
        subprocess.run(
            ["git", "init", f"--initial-branch={initial_branch}"],
            cwd=str(root),
            check=True,
            capture_output=True,
            env=env,
        )
        # Configure identity as local fallback (env should cover it but be safe).
        subprocess.run(["git", "config", "user.email", "test@invalid"], cwd=str(root), check=True, env=env)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(root), check=True, env=env)
        return cls(root)

    @staticmethod
    def _git_env() -> dict:
        return {
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@invalid",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@invalid",
            "GIT_AUTHOR_DATE": "2026-04-14T00:00:00+00:00",
            "GIT_COMMITTER_DATE": "2026-04-14T00:00:00+00:00",
        }

    def write(self, rel: str, content: str) -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def commit(self, message: str):
        env = self._git_env()
        subprocess.run(["git", "add", "-A"], cwd=str(self.root), check=True, env=env)
        subprocess.run(
            ["git", "commit", "-m", message, "--allow-empty"],
            cwd=str(self.root),
            check=True,
            capture_output=True,
            env=env,
        )


# ---------------------------------------------------------------------------
# Helpers / utilities (unit tests, no git) — tests 1-6
# ---------------------------------------------------------------------------


def test_find_active_sprint_returns_slug_from_progress(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "PROGRESS.md").write_text(_progress("SP_007_Demo"), encoding="utf-8")
    assert v.find_active_sprint(root) == "SP_007_Demo"


def test_find_active_sprint_returns_none_when_progress_missing(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    assert v.find_active_sprint(root) is None


def test_parse_frontmatter_required_keys_missing(tmp_path):
    """Stage F-1 must detect missing keys; parse_frontmatter returns the dict."""
    state, parsed = v.parse_frontmatter("---\nsprint_id: SP_1\n---\n")
    assert state == "present"
    assert parsed["sprint_id"] == "SP_1"
    for key in ("features", "user_stories", "schema_touched", "structure_touched", "status"):
        assert key not in parsed


def test_coerce_bool_accepts_bool_and_strings():
    assert v._coerce_bool(True) is True
    assert v._coerce_bool(False) is False
    assert v._coerce_bool("true") is True
    assert v._coerce_bool("FALSE") is False
    assert v._coerce_bool("True") is True
    assert v._coerce_bool("maybe") is None
    assert v._coerce_bool(1) is None


def test_classify_meta_doc_only_at_project_root():
    """Meta-docs are recognized ONLY at project root; a nested copy (e.g.,
    in src/ or templates/) does NOT count as a meta-doc."""
    nested = v._classify(
        "src/FEATURE_LIST.md",
        source_roots=["src"],
        meta_docs=["FEATURE_LIST.md"],
        exempt_paths=[],
    )
    root = v._classify(
        "FEATURE_LIST.md",
        source_roots=["src"],
        meta_docs=["FEATURE_LIST.md"],
        exempt_paths=[],
    )
    assert nested == "source"
    assert root == "meta_doc"


def test_classify_exempt_paths_override_source():
    kind = v._classify(
        "validators/test_validate_x.py",
        source_roots=["validators"],
        meta_docs=[],
        exempt_paths=["**/test_*.py"],
    )
    assert kind == "exempt"


# ---------------------------------------------------------------------------
# Stage F-1 (unit, no git) — tests 7-11
# ---------------------------------------------------------------------------


def test_stage_f1_disabled_by_default_advisory_passes(tmp_path, capsys):
    root = tmp_path / "proj"
    root.mkdir()
    cfg = {}  # no 'enabled' key
    passed, parsed, plan = v.stage_f1(root, cfg)
    assert passed is True
    assert parsed is None
    assert "disabled" in capsys.readouterr().err.lower()


def test_stage_f1_no_active_sprint_advisory_passes(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    passed, parsed, plan = v.stage_f1(root, {"enabled": True})
    assert passed is True
    assert parsed is None


def test_stage_f1_sprint_plan_missing_fails(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "PROGRESS.md").write_text(_progress("SP_100"), encoding="utf-8")
    # no workspace/sprints/SP_100*.md
    passed, _, _ = v.stage_f1(root, {"enabled": True})
    assert passed is False


def test_stage_f1_frontmatter_all_keys_present_passes(tmp_path):
    root = tmp_path / "proj"
    sprints = root / "workspace" / "sprints"
    sprints.mkdir(parents=True)
    (root / "PROGRESS.md").write_text(_progress("SP_042"), encoding="utf-8")
    (sprints / "SP_042_Thing.md").write_text(_sprint_plan_fm("SP_042"), encoding="utf-8")
    passed, parsed, plan_path = v.stage_f1(root, {"enabled": True})
    assert passed is True
    assert parsed["sprint_id"] == "SP_042"
    assert parsed["schema_touched"] is False  # coerced to bool


def test_stage_f1_frontmatter_bad_status_value_fails(tmp_path):
    root = tmp_path / "proj"
    sprints = root / "workspace" / "sprints"
    sprints.mkdir(parents=True)
    (root / "PROGRESS.md").write_text(_progress("SP_042"), encoding="utf-8")
    (sprints / "SP_042.md").write_text(
        _sprint_plan_fm("SP_042", status="ShippingAsFastAsPossible"), encoding="utf-8"
    )
    passed, _, _ = v.stage_f1(root, {"enabled": True})
    assert passed is False


def test_stage_f1_bool_coercion_rejects_garbage(tmp_path):
    root = tmp_path / "proj"
    sprints = root / "workspace" / "sprints"
    sprints.mkdir(parents=True)
    (root / "PROGRESS.md").write_text(_progress("SP_042"), encoding="utf-8")
    (sprints / "SP_042.md").write_text(
        _sprint_plan_fm("SP_042", schema_touched="maybe"), encoding="utf-8"
    )
    passed, _, _ = v.stage_f1(root, {"enabled": True})
    assert passed is False


# ---------------------------------------------------------------------------
# Stage F-2 (unit; changed_files provided directly) — tests 12-17
# ---------------------------------------------------------------------------


def test_stage_f2_features_claimed_but_feature_list_untouched_fails():
    parsed = {"features": ["F-1"], "user_stories": [], "schema_touched": False, "structure_touched": False}
    assert v.stage_f2(parsed, {"src/foo.py"}) is False


def test_stage_f2_features_claimed_and_feature_list_touched_passes():
    parsed = {"features": ["F-1"], "user_stories": [], "schema_touched": False, "structure_touched": False}
    assert v.stage_f2(parsed, {"src/foo.py", "FEATURE_LIST.md"}) is True


def test_stage_f2_user_stories_claimed_but_untouched_fails():
    parsed = {"features": [], "user_stories": ["US-3"], "schema_touched": False, "structure_touched": False}
    assert v.stage_f2(parsed, {"src/foo.py"}) is False


def test_stage_f2_schema_touched_true_but_schema_doc_untouched_fails():
    parsed = {"features": [], "user_stories": [], "schema_touched": True, "structure_touched": False}
    assert v.stage_f2(parsed, {"src/db.py"}) is False


def test_stage_f2_structure_touched_true_but_structure_doc_untouched_fails():
    parsed = {"features": [], "user_stories": [], "schema_touched": False, "structure_touched": True}
    assert v.stage_f2(parsed, {"src/new.py"}) is False


def test_stage_f2_all_claims_empty_and_no_meta_docs_passes():
    parsed = {"features": [], "user_stories": [], "schema_touched": False, "structure_touched": False}
    assert v.stage_f2(parsed, {"src/foo.py"}) is True


def test_stage_f2_empty_diff_with_positive_claims_fails():
    """A sprint plan with declared features but no diff is unfulfilled — must fail."""
    parsed = {"features": ["F-1"], "user_stories": [], "schema_touched": False, "structure_touched": False}
    assert v.stage_f2(parsed, set()) is False


# Multi-agent fleet-freeze fix (PROGRESS.md 2026-05-19) — on a shared
# linear main, DATA_SCHEMA/CODEBASE_STRUCTURE in a sprint's plan-to-HEAD
# range is dominated by PARALLEL agents' commits. Inverse-drift is
# therefore ADVISORY (reconcile-sprint-frontmatter.py is the authoritative
# attribution mechanism per Rule 16); FORWARD-claim checks stay ENFORCE.


def test_stage_f2_inverse_schema_drift_advisory_not_rescoped():
    """Generalized: inverse drift is advisory even on the non-rescoped path."""
    parsed = {"features": [], "user_stories": [], "schema_touched": False,
              "structure_touched": False, "_gate_rescoped": False}
    assert v.stage_f2(parsed, {"src/db.py", "DATA_SCHEMA.md"}) is True


def test_stage_f2_inverse_structure_drift_advisory_not_rescoped():
    parsed = {"features": [], "user_stories": [], "schema_touched": False,
              "structure_touched": False, "_gate_rescoped": False}
    assert v.stage_f2(parsed, {"src/x.py", "CODEBASE_STRUCTURE.md"}) is True


def test_stage_f2_inverse_drift_advisory_when_rescoped():
    parsed = {"features": [], "user_stories": [], "schema_touched": False,
              "structure_touched": False, "_gate_rescoped": True}
    assert v.stage_f2(parsed, {"src/db.py", "DATA_SCHEMA.md",
                               "CODEBASE_STRUCTURE.md"}) is True


def test_stage_f2_forward_claim_still_enforced():
    """Forward claims (declared true, doc absent) cannot false-positive from
    parallel collateral, so they stay ENFORCE."""
    parsed = {"features": [], "user_stories": [], "schema_touched": True,
              "structure_touched": False}
    assert v.stage_f2(parsed, {"src/db.py"}) is False


def test_stage_f2_forward_feature_claim_still_enforced():
    parsed = {"features": ["F-9"], "user_stories": [], "schema_touched": False,
              "structure_touched": False}
    assert v.stage_f2(parsed, {"src/db.py"}) is False


def test_stage_f2_empty_diff_no_claims_advisory_passes():
    """Empty diff with no positive claims is the legitimate fresh-sprint state."""
    parsed = {"features": [], "user_stories": [], "schema_touched": False, "structure_touched": False}
    assert v.stage_f2(parsed, set()) is True


# ---------------------------------------------------------------------------
# Stage F-2 inverse checks — tests 18-19
# ---------------------------------------------------------------------------


def test_stage_f2_schema_doc_in_range_but_schema_touched_false_is_advisory():
    """Multi-agent fleet-freeze fix (PROGRESS.md 2026-05-19): inverse drift
    is ADVISORY — DATA_SCHEMA.md in a sprint's plan-to-HEAD range is
    dominated by parallel agents' commits on the shared linear main;
    reconcile-sprint-frontmatter.py is the authoritative attribution
    mechanism (Rule 16). Was previously a hard FAIL (the fleet-freeze)."""
    parsed = {"features": [], "user_stories": [], "schema_touched": False, "structure_touched": False}
    assert v.stage_f2(parsed, {"DATA_SCHEMA.md"}) is True


def test_stage_f2_structure_doc_in_range_but_structure_touched_false_is_advisory():
    parsed = {"features": [], "user_stories": [], "schema_touched": False, "structure_touched": False}
    assert v.stage_f2(parsed, {"CODEBASE_STRUCTURE.md"}) is True


# ---------------------------------------------------------------------------
# Stage F-3 (unit; changed_files provided directly) — tests 20-25
# ---------------------------------------------------------------------------


def _roots() -> list[str]:
    return ["src", "skills", "validators"]


def _metas() -> list[str]:
    return list(v._DEFAULT_META_DOCS)


def test_stage_f3_source_changes_with_no_meta_doc_touched_fails():
    assert v.stage_f3({"src/foo.py"}, _roots(), _metas(), []) is False


def test_stage_f3_source_changes_with_meta_doc_touched_passes():
    assert v.stage_f3({"src/foo.py", "FEATURE_LIST.md"}, _roots(), _metas(), []) is True


def test_stage_f3_only_meta_doc_changes_passes():
    assert v.stage_f3({"FEATURE_LIST.md"}, _roots(), _metas(), []) is True


def test_stage_f3_only_exempt_path_changes_passes():
    assert v.stage_f3({"validators/test_foo.py"}, _roots(), _metas(), ["**/test_*.py"]) is True


def test_stage_f3_test_only_changes_pass_with_default_roots():
    """test/ is not in default source_roots — test-only sprints don't force meta-doc."""
    assert v.stage_f3({"test/unit/test_x.py"}, _roots(), _metas(), []) is True


def test_stage_f3_empty_diff_advisory_passes():
    assert v.stage_f3(set(), _roots(), _metas(), []) is True


# ---------------------------------------------------------------------------
# Integration tests using real git — markers = integration
# ---------------------------------------------------------------------------


pytestmark_integration = pytest.mark.integration


@pytest.mark.integration
def test_list_changed_files_includes_untracked(tmp_path):
    repo = GitRepo.make(tmp_path)
    repo.write("README.md", "# initial\n")
    repo.commit("initial")
    # Add untracked file without committing.
    repo.write("src/new.py", "x = 1\n")
    changed = v.list_changed_files(repo.root, "HEAD")
    assert "src/new.py" in changed


@pytest.mark.integration
def test_list_changed_files_empty_when_no_diff(tmp_path):
    repo = GitRepo.make(tmp_path)
    repo.write("README.md", "# initial\n")
    repo.commit("initial")
    changed = v.list_changed_files(repo.root, "HEAD")
    assert changed == set()


@pytest.mark.integration
def test_resolve_diff_base_uses_parent_of_introducing_commit(tmp_path):
    repo = GitRepo.make(tmp_path)
    # Commit 1: some initial code.
    repo.write("README.md", "# init\n")
    repo.commit("c1")
    # Commit 2: introduce sprint plan.
    plan_path = repo.write(
        "workspace/sprints/SP_001.md", _sprint_plan_fm("SP_001")
    )
    repo.commit("c2 adds plan")
    base, sprint_start = v.resolve_diff_base(repo.root, plan_path)
    # Base should be c1 (parent of c2) — we can't easily check its SHA here but
    # we can verify it's NOT equal to HEAD.
    rc, head_sha, _ = v._git(repo.root, "rev-parse", "HEAD")
    assert rc == 0
    assert base and base != head_sha.strip()


@pytest.mark.integration
def test_stage_f4_last_reconciled_bumped_passes(tmp_path):
    repo = GitRepo.make(tmp_path)
    repo.write(
        "FEATURE_LIST.md",
        "---\nstatus: living\nlast-reconciled: 2026-04-01\n---\n\n# Features\n",
    )
    repo.write("PROGRESS.md", _progress("SP_001"))
    plan_path = repo.write("workspace/sprints/SP_001.md", _sprint_plan_fm("SP_001"))
    repo.commit("initial + plan")
    # Bump last-reconciled.
    repo.write(
        "FEATURE_LIST.md",
        "---\nstatus: living\nlast-reconciled: 2026-04-14\n---\n\n# Features\nupdated\n",
    )
    repo.commit("feature update with last-reconciled bump")
    base, start = v.resolve_diff_base(repo.root, plan_path)
    changed = v.list_changed_files(repo.root, base)
    assert v.stage_f4(repo.root, base, start, changed, _metas()) is True


def test_stage_f4_same_date_guard_fails(monkeypatch):
    """Unit test: when the diff union contains identical `-` and `+` dates,
    F-4 fails. Uses monkeypatch to inject a controlled diff; no git needed."""
    fake_diff = textwrap.dedent(
        """\
        diff --git a/FEATURE_LIST.md b/FEATURE_LIST.md
        --- a/FEATURE_LIST.md
        +++ b/FEATURE_LIST.md
        @@ -1,4 +1,4 @@
         ---
        -last-reconciled: 2026-04-14
        +last-reconciled: 2026-04-14
         status: living
         ---
        """
    )
    monkeypatch.setattr(v, "_file_diff_union", lambda root, base, path: fake_diff)
    monkeypatch.setattr(v, "_file_is_added", lambda root, base, path: False)
    # Run F-4 with the fake diff behind the scenes.
    passed = v.stage_f4(
        project_root=Path("/tmp/fake"),
        base="abc123",
        sprint_start="2026-04-01",
        changed_files={"FEATURE_LIST.md"},
        meta_docs=["FEATURE_LIST.md"],
    )
    assert passed is False


@pytest.mark.integration
def test_stage_f4_last_reconciled_not_bumped_fails(tmp_path):
    repo = GitRepo.make(tmp_path)
    repo.write(
        "FEATURE_LIST.md",
        "---\nstatus: living\nlast-reconciled: 2026-04-01\n---\n\n# Features\n",
    )
    repo.write("PROGRESS.md", _progress("SP_001"))
    plan_path = repo.write("workspace/sprints/SP_001.md", _sprint_plan_fm("SP_001"))
    repo.commit("initial + plan")
    # Modify content but not last-reconciled line.
    repo.write(
        "FEATURE_LIST.md",
        "---\nstatus: living\nlast-reconciled: 2026-04-01\n---\n\n# Features\nupdated\n",
    )
    repo.commit("feature update without bump")
    base, start = v.resolve_diff_base(repo.root, plan_path)
    changed = v.list_changed_files(repo.root, base)
    assert v.stage_f4(repo.root, base, start, changed, _metas()) is False


@pytest.mark.integration
def test_stage_f4_date_bumped_backwards_fails(tmp_path):
    repo = GitRepo.make(tmp_path)
    repo.write(
        "FEATURE_LIST.md",
        "---\nstatus: living\nlast-reconciled: 2026-04-10\n---\n\n# F\n",
    )
    repo.write("PROGRESS.md", _progress("SP_001"))
    plan_path = repo.write("workspace/sprints/SP_001.md", _sprint_plan_fm("SP_001"))
    repo.commit("initial")
    repo.write(
        "FEATURE_LIST.md",
        "---\nstatus: living\nlast-reconciled: 2020-01-01\n---\n\n# F updated\n",
    )
    repo.commit("backwards bump")
    base, start = v.resolve_diff_base(repo.root, plan_path)
    changed = v.list_changed_files(repo.root, base)
    assert v.stage_f4(repo.root, base, start, changed, _metas()) is False


@pytest.mark.integration
def test_stage_f4_corrective_reset_from_future_passes(tmp_path):
    """A future-dated `last-reconciled` is the runaway-ratchet bug; F-4
    must accept a rollback that brings the marker back to today.
    Bound: new_date must be <= today (no rollback to ancient past)."""
    import datetime as _dt
    today_iso = _dt.date.today().isoformat()
    far_future = "2099-12-31"
    repo = GitRepo.make(tmp_path)
    repo.write(
        "FEATURE_LIST.md",
        f"---\nstatus: living\nlast-reconciled: {far_future}\n---\n\n# F\n",
    )
    repo.write("PROGRESS.md", _progress("SP_001"))
    plan_path = repo.write("workspace/sprints/SP_001.md", _sprint_plan_fm("SP_001"))
    repo.commit("initial")
    repo.write(
        "FEATURE_LIST.md",
        f"---\nstatus: living\nlast-reconciled: {today_iso}\n---\n\n# F reset\n",
    )
    repo.commit("corrective reset")
    base, start = v.resolve_diff_base(repo.root, plan_path)
    changed = v.list_changed_files(repo.root, base)
    assert v.stage_f4(repo.root, base, start, changed, _metas()) is True


@pytest.mark.integration
def test_stage_f4_new_file_with_last_reconciled_passes(tmp_path):
    repo = GitRepo.make(tmp_path)
    repo.write("README.md", "# init\n")
    repo.write("PROGRESS.md", _progress("SP_001"))
    plan_path = repo.write("workspace/sprints/SP_001.md", _sprint_plan_fm("SP_001"))
    repo.commit("initial")
    # Add FEATURE_LIST.md fresh.
    repo.write(
        "FEATURE_LIST.md",
        "---\nstatus: living\nlast-reconciled: 2026-04-14\n---\n\n# Features\n",
    )
    repo.commit("add feature list")
    base, start = v.resolve_diff_base(repo.root, plan_path)
    changed = v.list_changed_files(repo.root, base)
    assert v.stage_f4(repo.root, base, start, changed, _metas()) is True


# ---------------------------------------------------------------------------
# Lockfile tests (unit + light git) — tests 26-29
# ---------------------------------------------------------------------------


def test_lockfile_written_by_default_on_success(tmp_path):
    v.write_lockfile(tmp_path, "SP_042_X", ["F-1", "F-2"], "abc123")
    data = json.loads((tmp_path / ".docs_reconciled").read_text())
    assert data["schema_version"] == 1
    assert data["sprint_id"] == "SP_042_X"
    assert data["sprint_num"] == 42
    assert "F-1" in data["stages_checked"]


def test_lockfile_atomic_write_replaces_stale(tmp_path):
    (tmp_path / ".docs_reconciled").write_text("truncated garbage", encoding="utf-8")
    v.write_lockfile(tmp_path, "SP_002_Y", ["F-1"], None)
    data = json.loads((tmp_path / ".docs_reconciled").read_text())
    assert data["sprint_id"] == "SP_002_Y"


def test_no_lockfile_flag_suppresses_write(tmp_path):
    """Via CLI: --no-lockfile should not create the lockfile."""
    root = tmp_path / "proj"
    root.mkdir()
    # Validator disabled by default → passes, but even on pass --no-lockfile suppresses.
    script = Path(v.__file__)
    result = subprocess.run(
        [sys.executable, str(script), str(root), "--no-lockfile"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert not (root / ".docs_reconciled").exists()


# ---------------------------------------------------------------------------
# CLI tests — tests 30-32
# ---------------------------------------------------------------------------


def _invoke_cli(root: Path, *extra: str) -> subprocess.CompletedProcess:
    script = Path(v.__file__)
    return subprocess.run(
        [sys.executable, str(script), str(root), *extra],
        capture_output=True, text=True,
    )


def test_cli_happy_path_disabled_exits_zero(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    result = _invoke_cli(root)
    assert result.returncode == 0


def test_cli_skip_stage_flag(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    result = _invoke_cli(root, "--skip-stage", "F1,F2,F3,F4")
    assert result.returncode == 0


def test_cli_missing_project_root_fails(tmp_path):
    result = _invoke_cli(tmp_path / "nonexistent")
    assert result.returncode == 1


# ---------------------------------------------------------------------------
# Integration-with-config tests — tests 33-35
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_cli_enabled_with_bad_frontmatter_exits_one(tmp_path):
    repo = GitRepo.make(tmp_path)
    repo.write(".validators.yml", _validators_yml_enabled())
    repo.write("PROGRESS.md", _progress("SP_001"))
    repo.write("workspace/sprints/SP_001.md", "no frontmatter here\n")
    repo.commit("initial")
    result = _invoke_cli(repo.root)
    assert result.returncode == 1


@pytest.mark.integration
def test_cli_enabled_with_clean_sprint_exits_zero_and_writes_lockfile(tmp_path):
    repo = GitRepo.make(tmp_path)
    repo.write(".validators.yml", _validators_yml_enabled())
    repo.write("PROGRESS.md", _progress("SP_001"))
    repo.write("workspace/sprints/SP_001.md", _sprint_plan_fm("SP_001"))
    repo.commit("initial sprint plan")
    result = _invoke_cli(repo.root)
    assert result.returncode == 0, result.stderr
    assert (repo.root / ".docs_reconciled").exists()
    data = json.loads((repo.root / ".docs_reconciled").read_text())
    assert data["sprint_id"] == "SP_001"


@pytest.mark.integration
def test_cli_enabled_source_change_without_meta_doc_fails(tmp_path):
    repo = GitRepo.make(tmp_path)
    # Pre-sprint initial: PROGRESS.md + .validators.yml pre-exist. A PROGRESS
    # Current-marker will be added in the sprint-opening commit, so the active
    # sprint plan lives only in the sprint's diff range.
    repo.write("README.md", "# pre-sprint\n")
    repo.write(".validators.yml", _validators_yml_enabled())
    repo.write(
        "PROGRESS.md",
        "---\nstatus: living\nlast-reconciled: 2026-04-01\n---\n\n# Progress\n",
    )
    repo.commit("pre-sprint initial")
    # Sprint opens.
    repo.write("PROGRESS.md", _progress("SP_001"))
    repo.write("workspace/sprints/SP_001.md", _sprint_plan_fm("SP_001"))
    repo.commit("sprint opened")
    # Source change without a separate meta-doc bump. PROGRESS.md already in
    # sprint-opening commit; its content doesn't change here, so F-3 sees only
    # a source change with no NEW meta-doc touch in this final commit. However
    # the diff base is the pre-sprint commit, so PROGRESS.md IS in the diff
    # (from sprint-open). To isolate the "pure source" change, we need to also
    # test with a scenario where PROGRESS.md is NOT in the base..HEAD set.
    #
    # Use a different approach: skip-stage F4 so PROGRESS's unbumped
    # last-reconciled doesn't interfere, and rely on F-3's meta_count check
    # against a configured meta_docs list that DOES NOT include PROGRESS.md.
    repo.write("src/new_module.py", "def f(): pass\n")
    repo.commit("add source only")
    # Override meta_docs via config so PROGRESS.md doesn't automatically count.
    repo.write(
        ".validators.yml",
        textwrap.dedent(
            """\
            doc_freshness:
              enabled: true
              source_roots: [src]
              meta_docs: [FEATURE_LIST.md, DATA_SCHEMA.md]
              exempt_paths: []
            """
        ),
    )
    repo.commit("tighten meta_docs list")
    result = _invoke_cli(repo.root)
    assert result.returncode == 1, result.stderr


@pytest.mark.integration
def test_advisory_codefree_deploy_still_writes_lockfile(tmp_path):
    """SP_736 seam regression guard.

    On a docs-only deploy, scope_gate goes ADVISORY and stage_f1
    short-circuits with parsed=None — so main() used to early-return a
    pass WITHOUT writing `.docs_reconciled`. deploy.yml then hard-asserts
    that lockfile ("FATAL: .docs_reconciled missing") → every docs-only
    deploy FATALs fleet-wide, re-introducing the freeze SP_736 removed.
    An advisory pass IS a pass and MUST emit the deploy receipt.
    """
    repo = GitRepo.make(tmp_path)
    repo.write(".validators.yml", _validators_yml_enabled())
    repo.write("PROGRESS.md", _progress("SP_001"))
    repo.write("workspace/sprints/SP_001.md", _sprint_plan_fm("SP_001"))
    repo.commit("initial sprint plan")
    env = {**os.environ, "DEV_DEPLOY_CODE_CHANGED": "false"}
    result = subprocess.run(
        [sys.executable, str(Path(v.__file__)), str(repo.root)],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "ADVISORY" in result.stderr
    assert (repo.root / ".docs_reconciled").exists(), (
        "advisory (code-free) pass must still write the deploy receipt"
    )
    data = json.loads((repo.root / ".docs_reconciled").read_text())
    assert data["sprint_id"] == "SP_001"


def test_advisory_codefree_respects_no_lockfile(tmp_path):
    """Advisory write must still honour --no-lockfile (CI dry-run)."""
    repo = GitRepo.make(tmp_path)
    repo.write(".validators.yml", _validators_yml_enabled())
    repo.write("PROGRESS.md", _progress("SP_001"))
    repo.write("workspace/sprints/SP_001.md", _sprint_plan_fm("SP_001"))
    repo.commit("initial sprint plan")
    env = {**os.environ, "DEV_DEPLOY_CODE_CHANGED": "false"}
    result = subprocess.run(
        [sys.executable, str(Path(v.__file__)), str(repo.root), "--no-lockfile"],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stderr
    assert not (repo.root / ".docs_reconciled").exists()
