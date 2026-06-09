#!/usr/bin/env python3
"""SP_957 — behavioural tests for commit-msg `_foreign_claim_match` over-broad skip.

Run: python3 -m unittest discover -s scripts/git-hooks -p 'test_commit_msg_overbroad_skip.py' -v
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest import mock

_SPEC = importlib.util.spec_from_file_location(
    "commit_msg_hook", Path(__file__).resolve().parent / "commit-msg.py"
)
cm = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(cm)

ROOT = Path("/proj")


def _claim(sprint_id, paths):
    return cm.Claim(
        sprint_id=sprint_id,
        status="In Progress",
        path=Path(f"/proj/workspace/sprints/{sprint_id}.md"),
        touches_paths=tuple(paths),
        touches_checklist_items=(),
    )


def _fresh():
    # Hold the foreign plan FRESH (2 < STALE_DAYS) so the SP_956 stale-skip never
    # fires — the SP_957 over-broad logic is what every test below exercises.
    return mock.patch.object(cm, "plan_age_days", return_value=2)


class OverBroadClaimSkip(unittest.TestCase):
    def test_over_broad_fresh_claim_skipped(self):
        # Blanket bare-directory claim (>20 files) on a fresh sprint → relaxed.
        claims = [_claim("SP_751", ["scenarios/"])]
        with _fresh(), mock.patch.object(cm, "tracked_files_under", return_value=76):
            r = cm._foreign_claim_match("scenarios/foo.json", "SP_999", claims, ROOT, {})
        self.assertIsNone(r)  # over-broad → commit allowed

    def test_specific_fresh_claim_still_refuses(self):
        # A specific (≤20) prefix is a real conflict signal → still blocks.
        claims = [_claim("SP_751", ["scenarios/my-scn.json"])]
        with _fresh(), mock.patch.object(cm, "tracked_files_under", return_value=1):
            r = cm._foreign_claim_match("scenarios/my-scn.json", "SP_999", claims, ROOT, {})
        self.assertIsNotNone(r)
        self.assertEqual(r.sprint_id, "SP_751")

    def test_mixed_single_claim_two_prefixes_specific_wins(self):
        # ONE claim whose touches_paths holds BOTH an over-broad dir AND a
        # specific leaf, where the staged path matches both. The `all(... >
        # THRESHOLD ...)` must be False (leaf counts 1) → refuse. Proves
        # "specific wins" via the `all`, not via two-separate-claim short-circuit.
        claims = [_claim("SP_816", ["src/jobs/", "src/jobs/client.ts"])]

        def counts(root, cp):
            return 73 if cp == "src/jobs/" else 1

        with _fresh(), mock.patch.object(cm, "tracked_files_under", side_effect=counts):
            r = cm._foreign_claim_match("src/jobs/client.ts", "SP_999", claims, ROOT, {})
        self.assertIsNotNone(r)  # specific leaf prefix wins → still blocks
        self.assertEqual(r.sprint_id, "SP_816")

    def test_mixed_parent_broad_child_specific_dir_refuses(self):
        # Stage-5 M-1: parent dir over-broad, a co-claimed SUB-dir specific, both
        # match the staged path → "specific wins" via the sub-dir (not a leaf).
        claims = [_claim("SP_950", ["scenarios/", "scenarios/sub/"])]

        def counts(root, cp):
            return 76 if cp == "scenarios/" else 5  # sub/ is specific (≤20)

        with _fresh(), mock.patch.object(cm, "tracked_files_under", side_effect=counts):
            r = cm._foreign_claim_match("scenarios/sub/x.json", "SP_999", claims, ROOT, {})
        self.assertIsNotNone(r)  # specific sub-dir prefix wins → still blocks
        self.assertEqual(r.sprint_id, "SP_950")

    def test_stale_skip_precedes_overbroad_no_count(self):
        # A claim that is BOTH stale AND over-broad: the SP_956 stale-skip fires
        # first, so tracked_files_under (the costlier `git ls-files`) is never run.
        claims = [_claim("SP_720", ["scenarios/"])]
        with mock.patch.object(cm, "plan_age_days", return_value=30), \
                mock.patch.object(cm, "tracked_files_under") as tfu:
            r = cm._foreign_claim_match("scenarios/foo.json", "SP_999", claims, ROOT, {})
        self.assertIsNone(r)
        tfu.assert_not_called()

    def test_overbroad_memoised_once_per_prefix(self):
        # Same broad prefix co-claimed across two staged paths → counted once.
        claims = [_claim("SP_751", ["scenarios/"])]
        broad_cache: dict = {}
        with _fresh(), mock.patch.object(cm, "tracked_files_under", return_value=76) as tfu:
            cm._foreign_claim_match("scenarios/a.json", "SP_999", claims, ROOT, {}, broad_cache)
            cm._foreign_claim_match("scenarios/b.json", "SP_999", claims, ROOT, {}, broad_cache)
        self.assertEqual(tfu.call_count, 1)  # memoised across the two calls

    def test_two_over_broad_prefixes_both_match_still_skipped(self):
        # Relax-only: when ALL matching prefixes are over-broad the claim is
        # skipped — never a new block.
        claims = [_claim("SP_950", ["scenarios/", "scenarios/sub/"])]
        with _fresh(), mock.patch.object(cm, "tracked_files_under", return_value=76):
            r = cm._foreign_claim_match("scenarios/sub/x.json", "SP_999", claims, ROOT, {})
        self.assertIsNone(r)

    def test_backward_compat_five_positional_args(self):
        # SP_956 tests call with 5 positional args (no broad_cache). The optional
        # 6th param (default None → fresh dict) must not break them: a specific
        # fresh claim still refuses.
        claims = [_claim("SP_751", ["src/x.ts"])]
        with _fresh(), mock.patch.object(cm, "tracked_files_under", return_value=1):
            r = cm._foreign_claim_match("src/x.ts", "SP_999", claims, ROOT, {})
        self.assertIsNotNone(r)

    def test_own_sprint_overbroad_short_circuits_before_count(self):
        # Own-sprint guard precedes both skips — tracked_files_under never runs.
        claims = [_claim("SP_999", ["scenarios/"])]
        with _fresh(), mock.patch.object(cm, "tracked_files_under") as tfu:
            r = cm._foreign_claim_match("scenarios/foo.json", "SP_999", claims, ROOT, {})
        self.assertIsNone(r)
        tfu.assert_not_called()


class OverBroadRealGitSeam(unittest.TestCase):
    """Stage-5 MEDIUM-1: the OverBroadClaimSkip tests all mock
    `tracked_files_under`, so the hook→helper→`git ls-files` seam is never run
    end-to-end. This class exercises it against a REAL temp git repo (only
    `plan_age_days` is held fresh so the staleness skip doesn't pre-empt) — if
    the import wiring in commit-msg.py ever drifts, the mocked tests stay green
    but this one breaks."""

    def setUp(self):
        import os
        import shutil
        import subprocess
        import tempfile
        self._shutil = shutil
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null",
               "GIT_CONFIG_SYSTEM": "/dev/null"}

        def run(*a):
            subprocess.run(list(a), cwd=self.root, check=True,
                           capture_output=True, env=env)

        run("git", "init", "-q")
        run("git", "config", "user.email", "t@t")
        run("git", "config", "user.name", "t")
        (self.root / "scenarios").mkdir()
        for i in range(25):  # > BROAD_FILE_THRESHOLD (20)
            (self.root / "scenarios" / f"s{i}.json").write_text("{}")
        (self.root / "src").mkdir()
        (self.root / "src" / "only.ts").write_text("x")  # specific leaf (1 file)
        (self.root / "small").mkdir()
        for i in range(3):  # specific DIR (3 ≤ 20) — exercises real `git ls-files`
            (self.root / "small" / f"f{i}.ts").write_text("x")
        run("git", "add", "-A")
        run("git", "commit", "-q", "-m", "init")

    def tearDown(self):
        self._shutil.rmtree(self.tmp, ignore_errors=True)

    def test_real_over_broad_dir_skipped(self):
        # `scenarios/` holds 25 tracked files (>20) → real git count relaxes it.
        claims = [_claim("SP_751", ["scenarios/"])]
        with _fresh():  # only staleness mocked; tracked_files_under is REAL
            r = cm._foreign_claim_match("scenarios/s0.json", "SP_999", claims, self.root, {})
        self.assertIsNone(r)

    def test_real_specific_file_claim_refuses(self):
        # `src/only.ts` is a leaf claim → real count 1 (≤20) → still blocks.
        claims = [_claim("SP_751", ["src/only.ts"])]
        with _fresh():
            r = cm._foreign_claim_match("src/only.ts", "SP_999", claims, self.root, {})
        self.assertIsNotNone(r)
        self.assertEqual(r.sprint_id, "SP_751")

    def test_real_specific_small_dir_claim_refuses(self):
        # Stage-5 iter-2 LOW-3: `small/` holds 3 tracked files (≤20) → exercises
        # the REAL `git ls-files` count path (NOT the is_file() shortcut) for a
        # sub-threshold directory → still blocks.
        claims = [_claim("SP_751", ["small/"])]
        with _fresh():
            r = cm._foreign_claim_match("small/f0.ts", "SP_999", claims, self.root, {})
        self.assertIsNotNone(r)
        self.assertEqual(r.sprint_id, "SP_751")


if __name__ == "__main__":
    unittest.main(verbosity=2)
