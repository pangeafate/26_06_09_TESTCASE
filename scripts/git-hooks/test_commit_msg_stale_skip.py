#!/usr/bin/env python3
"""SP_956 — behavioural tests for commit-msg `_foreign_claim_match` stale-skip.

Run: python3 -m unittest discover -s scripts/git-hooks -p 'test_commit_msg*.py' -v
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


def _claim(sprint_id: str, paths):
    return cm.Claim(
        sprint_id=sprint_id,
        status="In Progress",
        path=Path(f"/proj/workspace/sprints/{sprint_id}.md"),
        touches_paths=tuple(paths),
        touches_checklist_items=(),
    )


class ForeignClaimStaleSkip(unittest.TestCase):
    def test_stale_claim_skipped_returns_none(self):
        claims = [_claim("SP_364", ["src/x.ts"])]
        with mock.patch.object(cm, "plan_age_days", return_value=20):  # ≥14 → zombie
            r = cm._foreign_claim_match("src/x.ts", "SP_999", claims, ROOT, {})
        self.assertIsNone(r)  # skipped → commit allowed

    def test_fresh_claim_still_refuses(self):
        claims = [_claim("SP_950", ["src/x.ts"])]
        with mock.patch.object(cm, "plan_age_days", return_value=2):  # <14 → fresh
            r = cm._foreign_claim_match("src/x.ts", "SP_999", claims, ROOT, {})
        self.assertIsNotNone(r)
        self.assertEqual(r.sprint_id, "SP_950")

    def test_co_claim_stale_plus_fresh_returns_fresh(self):
        # The load-bearing case (HIGH-1): a hot path co-claimed by a zombie AND
        # a fresh sprint must still refuse via the fresh one.
        claims = [_claim("SP_364", ["src/x.ts"]), _claim("SP_950", ["src/x.ts"])]
        ages = {"/proj/workspace/sprints/SP_364.md": 30, "/proj/workspace/sprints/SP_950.md": 1}
        with mock.patch.object(cm, "plan_age_days", side_effect=lambda root, p: ages[str(p)]):
            r = cm._foreign_claim_match("src/x.ts", "SP_999", claims, ROOT, {})
        self.assertIsNotNone(r)
        self.assertEqual(r.sprint_id, "SP_950")  # fresh wins; stale skipped individually

    def test_git_error_age_none_fails_closed_refuses(self):
        claims = [_claim("SP_364", ["src/x.ts"])]
        with mock.patch.object(cm, "plan_age_days", return_value=None):  # git error
            r = cm._foreign_claim_match("src/x.ts", "SP_999", claims, ROOT, {})
        self.assertIsNotNone(r)  # fail-closed → still blocks

    def test_age_zero_unparseable_fails_closed_refuses(self):
        # plan_age_days → 0 (unparseable %cr) must NOT skip (0 < STALE_DAYS).
        claims = [_claim("SP_364", ["src/x.ts"])]
        with mock.patch.object(cm, "plan_age_days", return_value=0):
            r = cm._foreign_claim_match("src/x.ts", "SP_999", claims, ROOT, {})
        self.assertIsNotNone(r)  # fail-closed → still blocks

    def test_own_sprint_never_blocks(self):
        claims = [_claim("SP_999", ["src/x.ts"])]
        with mock.patch.object(cm, "plan_age_days", return_value=2) as paged:
            r = cm._foreign_claim_match("src/x.ts", "SP_999", claims, ROOT, {})
        self.assertIsNone(r)
        paged.assert_not_called()  # own-sprint guard short-circuits before aging

    def test_memoisation_ages_each_plan_once(self):
        # Two staged paths both co-claimed by the same zombie → age once (cache).
        claims = [_claim("SP_364", ["src/x.ts", "src/y.ts"])]
        cache: dict = {}
        with mock.patch.object(cm, "plan_age_days", return_value=30) as paged:
            cm._foreign_claim_match("src/x.ts", "SP_999", claims, ROOT, cache)
            cm._foreign_claim_match("src/y.ts", "SP_999", claims, ROOT, cache)
        self.assertEqual(paged.call_count, 1)  # memoised across the two calls


if __name__ == "__main__":
    unittest.main(verbosity=2)
