"""Tests for the deploy-gate scoping helper."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import _diff_scope  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


def _set_env(monkeypatch, code, files=""):
    if code is None:
        monkeypatch.delenv("DEV_DEPLOY_CODE_CHANGED", raising=False)
    else:
        monkeypatch.setenv("DEV_DEPLOY_CODE_CHANGED", code)
    monkeypatch.setenv("DEV_DEPLOY_CHANGED_FILES", files)


# ---- R4a: the ONLY advisory case — provably code-free push ----
def test_R4a_code_false_is_advisory(monkeypatch):
    _set_env(monkeypatch, "false", "workspace/sprints/SP_999_Foo.md")
    sid, mode = _diff_scope.scope_gate(REPO, "SP_999")
    assert mode == "advisory"
    assert sid is None  # advisory contract: gated_sprint_id is None


# ---- R1: unrelated WIP sibling (plan-only) does not fleet-fail ----
def test_R1_plan_only_sibling_advisory(monkeypatch):
    # code=false because the only changed file is a sibling plan doc
    _set_env(monkeypatch, "false", "workspace/sprints/SP_731_Bar.md")
    sid, mode = _diff_scope.scope_gate(REPO, "SP_731")
    assert mode == "advisory"
    assert sid is None


# ---- LOAD-BEARING INVARIANT: advisory reachable ONLY via literal "false" ----
@pytest.mark.parametrize(
    "val",
    [" false ", "False", "FALSE", "0", "no", "", "true ", "f", "false ",
     "false\n", " false", "false\t"],
)
def test_casing_whitespace_never_advisory(monkeypatch, val):
    """advisory must be reachable ONLY via the exact literal "false". Any
    other value (casing/whitespace/falsey-ish) MUST fail-closed enforce —
    a silent advisory on a code-bearing deploy is the only dangerous
    state this whole module exists to prevent."""
    _set_env(monkeypatch, val, "validators/_common.py")
    sid, mode = _diff_scope.scope_gate(REPO, "SP_736")
    assert mode == "enforce", f"value {val!r} must NOT yield advisory"
    assert sid == "SP_736"


# ---- R2: a code-bearing deploy still ENFORCES (scoped, not weakened) ----
def test_R2_code_bearing_enforces(monkeypatch):
    _set_env(monkeypatch, "true", "validators/_common.py")
    _sid, mode = _diff_scope.scope_gate(REPO, "SP_736")
    assert mode == "enforce"


# ---- R3: code-bearing + no touches_paths match → FAIL-CLOSED enforce ----
def test_R3_code_bearing_no_match_fail_closed(monkeypatch):
    _set_env(monkeypatch, "true", "src/some/unmapped/file.ts")
    sid, mode = _diff_scope.scope_gate(REPO, "SP_736")
    assert mode == "enforce"
    assert sid == "SP_736"  # fail-closed to the resolver-resolved sprint


# ---- R4c: all-zeros BEFORE / CI fail-safe surfaced as code=true ----
def test_R4c_fail_safe_true_enforces(monkeypatch):
    _set_env(monkeypatch, "true", "")  # CI fail-safe emits true, files empty
    _sid, mode = _diff_scope.scope_gate(REPO, "SP_736")
    assert mode == "enforce"


# ---- R4d: env ABSENT (off-CI / local) → ENFORCE, never advisory ----
def test_R4d_absent_env_fail_closed_enforce(monkeypatch):
    _set_env(monkeypatch, None)
    sid, mode = _diff_scope.scope_gate(REPO, "SP_736")
    assert mode == "enforce"
    assert sid == "SP_736"  # symmetric with R3: never None on enforce


# ---- block-style YAML touches_paths must scope correctly ----
def test_block_style_touches_paths_scopes(tmp_path, monkeypatch):
    """A sprint declaring touches_paths as a YAML block sequence (bare
    key + `  - item` lines, no inline []) must still be matched by the
    code-set so the gate scopes to it — not silently dropped to []."""
    sd = tmp_path / "workspace" / "sprints"
    sd.mkdir(parents=True)
    (sd / "SP_801_Block.md").write_text(
        "---\n"
        "status: In Progress\n"
        "touches_paths:\n"
        '  - "src/blockmod/"\n'
        "  - src/other.py\n"
        "---\n# plan\n"
    )
    monkeypatch.setenv("DEV_DEPLOY_CODE_CHANGED", "true")
    monkeypatch.setenv("DEV_DEPLOY_CHANGED_FILES", "src/blockmod/handler.ts")
    sid, mode = _diff_scope.scope_gate(tmp_path, "SP_999_Resolver")
    assert mode == "enforce"
    assert sid == "SP_801"  # scoped to the block-style deploying sprint


def test_completed_recent_deploying_sprint_scopes_before_blocked_sibling(tmp_path, monkeypatch):
    """Stage-7 code deploys may have already marked the owning sprint
    Complete. A newer blocked/planning sibling mentioned in recent commit
    subjects must not steal the gate when the changed code still belongs to
    the completed deploying sprint."""
    sd = tmp_path / "workspace" / "sprints"
    sd.mkdir(parents=True)
    (sd / "SP_753_BlockedSibling.md").write_text(
        "---\n"
        "status: Planning\n"
        'touches_paths: ["src/jobs/task-package-sla-enforcer.ts"]\n'
        "---\n"
    )
    (sd / "SP_756_CompletedDeploying.md").write_text(
        "---\n"
        "status: Complete\n"
        "touches_paths:\n"
        '  - "src/middleware/decision.ts"\n'
        '  - "validators/_diff_scope.py"\n'
        "---\n"
    )
    monkeypatch.setattr(
        _diff_scope,
        "_recent_sprint_tokens",
        lambda _root: ["SP_753", "SP_756"],
    )
    monkeypatch.setenv("DEV_DEPLOY_CODE_CHANGED", "true")
    monkeypatch.setenv("DEV_DEPLOY_CHANGED_FILES", "src/middleware/decision.ts")

    sid, mode = _diff_scope.scope_gate(tmp_path, "SP_753")

    assert mode == "enforce"
    assert sid == "SP_756"


# ---- prefix match must not false-positive on a non-slash sibling ----
def test_prefix_match_no_false_positive(tmp_path, monkeypatch):
    sd = tmp_path / "workspace" / "sprints"
    sd.mkdir(parents=True)
    (sd / "SP_802_Pref.md").write_text(
        "---\nstatus: In Progress\ntouches_paths: [\"src/a\"]\n---\n"
    )
    monkeypatch.setenv("DEV_DEPLOY_CODE_CHANGED", "true")
    monkeypatch.setenv("DEV_DEPLOY_CHANGED_FILES", "src/abc.py")
    sid, mode = _diff_scope.scope_gate(tmp_path, "SP_999_Resolver")
    assert mode == "enforce"
    # "src/a" must NOT match "src/abc.py" → fail-closed to the resolver
    assert sid == "SP_999_Resolver"


# ---- M-2: explicit empty inline touches_paths: [] → no match ----
def test_empty_inline_touches_paths_no_match(tmp_path, monkeypatch):
    sd = tmp_path / "workspace" / "sprints"
    sd.mkdir(parents=True)
    (sd / "SP_803_Empty.md").write_text(
        "---\nstatus: In Progress\ntouches_paths: []\n---\n"
    )
    monkeypatch.setenv("DEV_DEPLOY_CODE_CHANGED", "true")
    monkeypatch.setenv("DEV_DEPLOY_CHANGED_FILES", "src/anything.ts")
    sid, mode = _diff_scope.scope_gate(tmp_path, "SP_999_Resolver")
    assert mode == "enforce"
    assert sid == "SP_999_Resolver"  # [] matches nothing → fail-closed


# ---- M-1: status line with inline YAML comment still recognised open ----
def test_status_inline_comment_still_open(tmp_path, monkeypatch):
    sd = tmp_path / "workspace" / "sprints"
    sd.mkdir(parents=True)
    (sd / "SP_804_Cmt.md").write_text(
        "---\n"
        "status: In Progress  # auto-set by tool\n"
        'touches_paths: ["src/cmtmod/"]\n'
        "---\n"
    )
    monkeypatch.setenv("DEV_DEPLOY_CODE_CHANGED", "true")
    monkeypatch.setenv("DEV_DEPLOY_CHANGED_FILES", "src/cmtmod/x.ts")
    sid, mode = _diff_scope.scope_gate(tmp_path, "SP_999_Resolver")
    assert mode == "enforce"
    assert sid == "SP_804"  # comment-annotated status must not drop the sprint


# ---- block list immediately followed by another block key: no over-capture ----
def test_block_list_then_block_key_no_overcapture(tmp_path, monkeypatch):
    sd = tmp_path / "workspace" / "sprints"
    sd.mkdir(parents=True)
    (sd / "SP_805_Adj.md").write_text(
        "---\n"
        "status: In Progress\n"
        "touches_paths:\n"
        '  - "src/adj/"\n'
        "touches_checklist_items:\n"
        '  - "§17.4"\n'
        '  - "§16.6"\n'
        "---\n"
    )
    monkeypatch.setenv("DEV_DEPLOY_CODE_CHANGED", "true")
    # a checklist token must NEVER have been absorbed as a path
    monkeypatch.setenv("DEV_DEPLOY_CHANGED_FILES", "§17.4")
    sid, mode = _diff_scope.scope_gate(tmp_path, "SP_999_Resolver")
    assert mode == "enforce"
    assert sid == "SP_999_Resolver"  # §17.4 is NOT a path of SP_805


# ---- iter-3 LOW-1: trailing inline comment on a block path item ----
def test_block_path_trailing_comment_stripped(tmp_path, monkeypatch):
    sd = tmp_path / "workspace" / "sprints"
    sd.mkdir(parents=True)
    (sd / "SP_806_Cmt.md").write_text(
        "---\nstatus: In Progress\ntouches_paths:\n"
        "  - src/cmtpath/  # owns the handler\n---\n"
    )
    monkeypatch.setenv("DEV_DEPLOY_CODE_CHANGED", "true")
    monkeypatch.setenv("DEV_DEPLOY_CHANGED_FILES", "src/cmtpath/h.ts")
    sid, mode = _diff_scope.scope_gate(tmp_path, "SP_999_Resolver")
    assert mode == "enforce"
    assert sid == "SP_806"  # comment stripped → "src/cmtpath/" matches


# ---- iter-3 LOW-2: bare `-` empty item is skipped, block continues ----
def test_block_empty_item_does_not_end_block(tmp_path, monkeypatch):
    sd = tmp_path / "workspace" / "sprints"
    sd.mkdir(parents=True)
    (sd / "SP_807_Empty.md").write_text(
        "---\nstatus: In Progress\ntouches_paths:\n"
        "  -\n"
        "  - src/realpath/\n---\n"
    )
    monkeypatch.setenv("DEV_DEPLOY_CODE_CHANGED", "true")
    monkeypatch.setenv("DEV_DEPLOY_CHANGED_FILES", "src/realpath/z.ts")
    sid, mode = _diff_scope.scope_gate(tmp_path, "SP_999_Resolver")
    assert mode == "enforce"
    assert sid == "SP_807"  # empty item skipped, real path still parsed


# ---- iter-3 architect: CRLF plan stays fail-closed enforce ----
def test_crlf_plan_fail_closed_enforce(tmp_path, monkeypatch):
    sd = tmp_path / "workspace" / "sprints"
    sd.mkdir(parents=True)
    (sd / "SP_808_CRLF.md").write_bytes(
        b"---\r\nstatus: In Progress\r\n"
        b'touches_paths: ["src/crlf/"]\r\n---\r\n'
    )
    monkeypatch.setenv("DEV_DEPLOY_CODE_CHANGED", "true")
    monkeypatch.setenv("DEV_DEPLOY_CHANGED_FILES", "src/crlf/a.ts")
    sid, mode = _diff_scope.scope_gate(tmp_path, "SP_999_Resolver")
    # CRLF may defeat the `^---\n` frontmatter match → text[:4000]
    # fallback; either way the ONLY guarantee that matters holds:
    # never advisory on a code-bearing deploy.
    assert mode == "enforce"


def test_doc_exclusion_constant_covers_generic_doc_paths():
    assert _diff_scope._is_doc("docs/guide.md")
    assert _diff_scope._is_doc("workspace/sprints/SP_001.md")
    assert _diff_scope._is_doc("principles/layering.md")
    assert not _diff_scope._is_doc("src/runtime.ts")
