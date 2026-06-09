#!/usr/bin/env python3
"""SP_956 — tests for the promoted staleness helpers in _sprint_frontmatter.

Run: python3 -m unittest validators.test_sprint_frontmatter_staleness -v
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

import _sprint_frontmatter as sfm  # validators/ is on sys.path in CI discovery


class RelativeToDays(unittest.TestCase):
    def test_parity_with_sp955(self):
        cases = {
            "3 days ago": 3,
            "1 days ago": 1,
            "5 weeks ago": 35,
            "2 months ago": 60,
            "1 year ago": 365,
            "6 hours ago": 0,       # sub-day
            "24 hours ago": 1,      # >24h → floor-div to days
            "35 hours ago": 1,
            "47 hours ago": 1,
            "74 seconds ago": 0,
        }
        for rel, exp in cases.items():
            self.assertEqual(sfm.relative_to_days(rel), exp, rel)

    def test_boundary_13_14_15(self):
        self.assertEqual(sfm.relative_to_days("13 days ago"), 13)
        self.assertEqual(sfm.relative_to_days("14 days ago"), 14)
        self.assertEqual(sfm.relative_to_days("15 days ago"), 15)

    def test_unparseable_is_fresh_zero(self):
        # Conservative: unknown forms → 0 (< STALE_DAYS) → never a false zombie.
        self.assertEqual(sfm.relative_to_days("a day ago"), 0)
        self.assertEqual(sfm.relative_to_days(""), 0)
        self.assertEqual(sfm.relative_to_days("ago"), 0)
        self.assertEqual(sfm.relative_to_days("2 decades ago"), 0)


class PlanAgeDays(unittest.TestCase):
    def test_git_error_returns_none_fail_closed(self):
        with mock.patch.object(sfm.subprocess, "run", side_effect=OSError("no git")):
            self.assertIsNone(sfm.plan_age_days(Path("/x"), Path("/x/p.md")))

    def test_timeout_returns_none_fail_closed(self):
        with mock.patch.object(
            sfm.subprocess, "run",
            side_effect=sfm.subprocess.TimeoutExpired(cmd="git", timeout=5),
        ):
            self.assertIsNone(sfm.plan_age_days(Path("/x"), Path("/x/p.md")))

    def test_minutes_unit_is_fresh(self):
        self.assertEqual(sfm.relative_to_days("30 minutes ago"), 0)

    def test_empty_stdout_returns_none(self):
        fake = mock.Mock()
        fake.stdout = ""
        with mock.patch.object(sfm.subprocess, "run", return_value=fake):
            self.assertIsNone(sfm.plan_age_days(Path("/x"), Path("/x/p.md")))

    def test_parses_relative_output(self):
        fake = mock.Mock()
        fake.stdout = "  3 days ago\n"
        with mock.patch.object(sfm.subprocess, "run", return_value=fake):
            self.assertEqual(sfm.plan_age_days(Path("/x"), Path("/x/p.md")), 3)

    def test_cwd_independent_normalises_relative_path(self):
        captured = {}
        fake = mock.Mock()
        fake.stdout = "5 weeks ago"

        def rec(cmd, **kw):
            captured["target"] = cmd[-1]
            captured["cwd"] = kw.get("cwd")
            return fake
        with mock.patch.object(sfm.subprocess, "run", side_effect=rec):
            age = sfm.plan_age_days(Path("/proj"), Path("workspace/sprints/SP_1.md"))
        self.assertEqual(age, 35)
        self.assertEqual(captured["cwd"], Path("/proj"))
        # relative plan path normalised against root → absolute target
        self.assertTrue(str(captured["target"]).startswith("/proj/"))

    def test_stale_days_constant(self):
        self.assertEqual(sfm.STALE_DAYS, 14)


class TrackedFilesUnderShared(unittest.TestCase):
    """SP_957 — `tracked_files_under` promoted from the audit script. Real temp
    git repo (no subprocess mocking) so the load-bearing glob/trailing-slash
    behaviour is asserted against actual git, not a faked stdout."""

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
        for i in range(5):
            (self.root / "scenarios" / f"s{i}.json").write_text("{}")
        (self.root / "src").mkdir()
        (self.root / "src" / "x.ts").write_text("x")
        run("git", "add", "-A")
        run("git", "commit", "-q", "-m", "init")

    def tearDown(self):
        self._shutil.rmtree(self.tmp, ignore_errors=True)

    def test_directory_counts_tracked_files(self):
        self.assertEqual(sfm.tracked_files_under(self.root, "scenarios/"), 5)

    def test_leaf_file_is_one(self):
        self.assertEqual(sfm.tracked_files_under(self.root, "src/x.ts"), 1)

    def test_nonexistent_prefix_is_zero(self):
        self.assertEqual(sfm.tracked_files_under(self.root, "nope/"), 0)

    def test_empty_prefix_is_zero(self):
        self.assertEqual(sfm.tracked_files_under(self.root, "/"), 0)

    def test_glob_prefix_is_zero_trailing_slash_load_bearing(self):
        # LOAD-BEARING for SP_957 relax-safety: a glob-shaped claim must count 0
        # so it stays BELOW the over-broad threshold → still REFUSES (never
        # wrongly relaxed). This holds *because* tracked_files_under appends a
        # trailing slash: `git ls-files -- scenarios/s*/` matches nothing. Were
        # the slash dropped, `git ls-files -- scenarios/s*` would expand to 5 and
        # wrongly relax the glob claim. This test pins the slash behaviour.
        self.assertEqual(sfm.tracked_files_under(self.root, "scenarios/s*"), 0)

    def test_broad_threshold_constant(self):
        self.assertEqual(sfm.BROAD_FILE_THRESHOLD, 20)

    def test_git_error_fails_closed_to_zero_refuses(self):
        # Stage-5 M-2 / HIGH-1: OSError + TimeoutExpired both → 0 (below
        # threshold → over-broad skip NEVER fires → claim still refuses), the
        # same fail-closed contract as plan_age_days on this hot path.
        with mock.patch.object(Path, "is_file", return_value=False), \
                mock.patch.object(sfm.subprocess, "run", side_effect=OSError("no git")):
            self.assertEqual(sfm.tracked_files_under(Path("/x"), "scenarios/"), 0)
        with mock.patch.object(Path, "is_file", return_value=False), \
                mock.patch.object(
                    sfm.subprocess, "run",
                    side_effect=sfm.subprocess.TimeoutExpired(cmd="git", timeout=5)):
            self.assertEqual(sfm.tracked_files_under(Path("/x"), "scenarios/"), 0)


class IsOverBroad(unittest.TestCase):
    def test_boundary_is_strict_gt_threshold(self):
        self.assertFalse(sfm.is_over_broad(0))
        self.assertFalse(sfm.is_over_broad(20))   # exactly threshold → specific
        self.assertTrue(sfm.is_over_broad(21))    # > threshold → over-broad
        self.assertTrue(sfm.is_over_broad(233))


if __name__ == "__main__":
    unittest.main(verbosity=2)
