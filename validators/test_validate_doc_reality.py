"""Tests for validate_doc_reality.py (45-test plan per SP_001)."""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import validate_doc_reality as v


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_project(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return root


def _progress_active(sprint_id: str) -> str:
    return textwrap.dedent(
        f"""\
        ---
        status: living
        last-reconciled: 2026-04-13
        ---

        # Progress

        ## Active Sprint

        **Current:** {sprint_id}
        """
    )


def _valid_fm(name: str) -> str:
    return textwrap.dedent(
        f"""\
        ---
        status: living
        last-reconciled: 2026-04-13
        authoritative-for: [features]
        ---

        # {name}
        """
    )


# ---------------------------------------------------------------------------
# Frontmatter parser tests (1-5)
# ---------------------------------------------------------------------------


def test_parse_frontmatter_absent_returns_missing():
    state, parsed = v.parse_frontmatter("no frontmatter here\n")
    assert state == "missing"
    assert parsed is None


def test_parse_frontmatter_unclosed_returns_malformed():
    text = "---\nstatus: living\nstill open\nmore\n"
    state, _ = v.parse_frontmatter(text)
    assert state == "malformed"


def test_parse_frontmatter_valid_yaml_returns_dict():
    text = "---\nstatus: living\nlast-reconciled: 2026-04-13\n---\nbody\n"
    state, parsed = v.parse_frontmatter(text)
    assert state == "present"
    assert parsed["status"] == "living"
    assert str(parsed["last-reconciled"]) == "2026-04-13"


def test_parse_frontmatter_valid_fallback_no_pyyaml_returns_dict(monkeypatch):
    monkeypatch.setattr(v, "_HAS_YAML", False)
    text = "---\nstatus: spec\nlast-reconciled: 2026-01-01\nauthoritative-for: [a, b]\n---\nbody\n"
    state, parsed = v.parse_frontmatter(text)
    assert state == "present"
    assert parsed["status"] == "spec"
    assert parsed["authoritative-for"] == ["a", "b"]


def test_parse_frontmatter_closing_beyond_50_lines_returns_malformed():
    filler = "\n".join(f"key{i}: value{i}" for i in range(60))
    text = f"---\n{filler}\n---\nbody\n"
    state, _ = v.parse_frontmatter(text)
    assert state == "malformed"


def test_read_text_strips_utf8_bom(tmp_path):
    """Stage C must not false-negative on files written by editors that prepend a BOM."""
    p = tmp_path / "PROGRESS.md"
    p.write_bytes("\ufeff---\nstatus: living\nlast-reconciled: 2026-04-13\n---\n".encode("utf-8"))
    text = v._read_text_capped(p)
    assert text is not None
    assert text.startswith("---")
    state, parsed = v.parse_frontmatter(text)
    assert state == "present"
    assert parsed["status"] == "living"


# ---------------------------------------------------------------------------
# Stage A tests (6-18)
# ---------------------------------------------------------------------------


def test_stage_a_empty_project_passes(tmp_path):
    root = _make_project(tmp_path, {"README.md": "# hello\n"})
    failures = v.stage_a_dead_paths(root, v._DEFAULT_EXCLUDE_COMPONENTS, v._DEFAULT_EXCLUDE_FILENAME_GLOBS, [], [])
    assert failures == []


def test_stage_a_live_path_reference_passes(tmp_path):
    root = _make_project(
        tmp_path,
        {
            "README.md": "see `src/foo.py` for details\n",
            "src/foo.py": "# live\n",
        },
    )
    failures = v.stage_a_dead_paths(root, v._DEFAULT_EXCLUDE_COMPONENTS, v._DEFAULT_EXCLUDE_FILENAME_GLOBS, [], [])
    assert failures == []


def test_stage_a_dead_path_fails(tmp_path):
    root = _make_project(tmp_path, {"README.md": "missing: `src/ghost.py`\n"})
    failures = v.stage_a_dead_paths(root, v._DEFAULT_EXCLUDE_COMPONENTS, v._DEFAULT_EXCLUDE_FILENAME_GLOBS, [], [])
    assert any("src/ghost.py" in f for f in failures)


def test_stage_a_path_in_code_fence_ignored(tmp_path):
    root = _make_project(
        tmp_path,
        {"README.md": "```\nsee `src/imaginary.py`\n```\n"},
    )
    failures = v.stage_a_dead_paths(root, v._DEFAULT_EXCLUDE_COMPONENTS, v._DEFAULT_EXCLUDE_FILENAME_GLOBS, [], [])
    assert failures == []


def test_stage_a_path_with_placeholder_XXX_ignored(tmp_path):
    root = _make_project(tmp_path, {"README.md": "skeleton: `src/SP_XXX/file.md`\n"})
    failures = v.stage_a_dead_paths(root, v._DEFAULT_EXCLUDE_COMPONENTS, v._DEFAULT_EXCLUDE_FILENAME_GLOBS, [], [])
    assert failures == []


def test_stage_a_path_with_glob_ignored(tmp_path):
    root = _make_project(tmp_path, {"README.md": "run `test/*.py`\n"})
    failures = v.stage_a_dead_paths(root, v._DEFAULT_EXCLUDE_COMPONENTS, v._DEFAULT_EXCLUDE_FILENAME_GLOBS, [], [])
    assert failures == []


def test_stage_a_path_without_slash_ignored(tmp_path):
    root = _make_project(tmp_path, {"README.md": "bare `setup.py` mention\n"})
    failures = v.stage_a_dead_paths(root, v._DEFAULT_EXCLUDE_COMPONENTS, v._DEFAULT_EXCLUDE_FILENAME_GLOBS, [], [])
    assert failures == []


def test_stage_a_exclusion_dir_skipped(tmp_path):
    root = _make_project(
        tmp_path,
        {
            "node_modules/pkg/README.md": "dead: `src/ghost.py`\n",
            "README.md": "# real\n",
        },
    )
    failures = v.stage_a_dead_paths(root, v._DEFAULT_EXCLUDE_COMPONENTS, v._DEFAULT_EXCLUDE_FILENAME_GLOBS, [], [])
    assert failures == []


def test_stage_a_inline_ignore_marker_respected(tmp_path):
    root = _make_project(
        tmp_path,
        {"README.md": "<!-- doc-reality:ignore-paths -->\nsee `src/ghost.py`\n"},
    )
    failures = v.stage_a_dead_paths(root, v._DEFAULT_EXCLUDE_COMPONENTS, v._DEFAULT_EXCLUDE_FILENAME_GLOBS, [], [])
    assert failures == []


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks require admin on Windows")
def test_stage_a_broken_symlink_passes(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "README.md").write_text("see `src/link.py`\n", encoding="utf-8")
    (root / "src").mkdir()
    os.symlink(root / "nonexistent_target.py", root / "src" / "link.py")
    failures = v.stage_a_dead_paths(root, v._DEFAULT_EXCLUDE_COMPONENTS, v._DEFAULT_EXCLUDE_FILENAME_GLOBS, [], [])
    assert failures == []


def test_stage_a_path_traversal_rejected(tmp_path):
    root = _make_project(tmp_path, {"README.md": "sneak: `src/../../../outside.py`\n"})
    failures = v.stage_a_dead_paths(root, v._DEFAULT_EXCLUDE_COMPONENTS, v._DEFAULT_EXCLUDE_FILENAME_GLOBS, [], [])
    # Should be silently ignored (no failure), not raised.
    assert failures == []


def test_stage_a_dead_path_exclusions_config_respected(tmp_path):
    root = _make_project(tmp_path, {"README.md": "exempt: `src/exempt.py`\n"})
    failures = v.stage_a_dead_paths(
        root,
        v._DEFAULT_EXCLUDE_COMPONENTS,
        v._DEFAULT_EXCLUDE_FILENAME_GLOBS,
        ["src/exempt.py"],
        [],
    )
    assert failures == []


def test_stage_a_glob_exclusions_respected(tmp_path):
    root = _make_project(
        tmp_path,
        {"README.md": "ref: `archive/PROGRESS_ARCHIVE_001.md`\n"},
    )
    failures = v.stage_a_dead_paths(
        root,
        v._DEFAULT_EXCLUDE_COMPONENTS,
        v._DEFAULT_EXCLUDE_FILENAME_GLOBS,
        [],
        ["*PROGRESS_ARCHIVE*.md"],
    )
    assert failures == []


def test_stage_a_file_above_1mb_skipped_with_advisory(tmp_path, capsys):
    root = tmp_path / "proj"
    root.mkdir()
    big = "x" * (2 * 1024 * 1024)
    (root / "BIG.md").write_text(big, encoding="utf-8")
    failures = v.stage_a_dead_paths(root, v._DEFAULT_EXCLUDE_COMPONENTS, v._DEFAULT_EXCLUDE_FILENAME_GLOBS, [], [])
    assert failures == []
    captured = capsys.readouterr()
    assert "skipped" in captured.err.lower()


# ---------------------------------------------------------------------------
# Stage B tests (19-24)
# ---------------------------------------------------------------------------


def test_stage_b_no_active_sprint_passes_with_advisory(tmp_path, capsys):
    root = _make_project(tmp_path, {"README.md": "TBD-by: SP_001 — something\n"})
    failures = v.stage_b_tbd_decay(root, v._DEFAULT_EXCLUDE_COMPONENTS, v._DEFAULT_EXCLUDE_FILENAME_GLOBS)
    assert failures == []
    assert "No active sprint" in capsys.readouterr().err


def test_stage_b_tbd_future_sprint_passes(tmp_path):
    root = _make_project(
        tmp_path,
        {
            "PROGRESS.md": _progress_active("SP_001_Current"),
            "README.md": "TBD-by: SP_005 — future work\n",
        },
    )
    failures = v.stage_b_tbd_decay(root, v._DEFAULT_EXCLUDE_COMPONENTS, v._DEFAULT_EXCLUDE_FILENAME_GLOBS)
    assert failures == []


def test_stage_b_tbd_current_sprint_warn_passes(tmp_path, capsys):
    root = _make_project(
        tmp_path,
        {
            "PROGRESS.md": _progress_active("SP_003_Current"),
            "README.md": "TBD-by: SP_003 — due now\n",
        },
    )
    failures = v.stage_b_tbd_decay(root, v._DEFAULT_EXCLUDE_COMPONENTS, v._DEFAULT_EXCLUDE_FILENAME_GLOBS)
    assert failures == []
    assert "due this sprint" in capsys.readouterr().err


def test_stage_b_tbd_past_sprint_fails(tmp_path):
    root = _make_project(
        tmp_path,
        {
            "PROGRESS.md": _progress_active("SP_010_Current"),
            "README.md": "TBD-by: SP_003 — overdue\n",
        },
    )
    failures = v.stage_b_tbd_decay(root, v._DEFAULT_EXCLUDE_COMPONENTS, v._DEFAULT_EXCLUDE_FILENAME_GLOBS)
    assert len(failures) == 1
    assert "elapsed" in failures[0]


def test_stage_b_four_digit_sprint_number_parsed_correctly(tmp_path):
    root = _make_project(
        tmp_path,
        {
            "PROGRESS.md": _progress_active("SP_0900_Big"),
            "README.md": "TBD-by: SP_1000 — future\n",
        },
    )
    failures = v.stage_b_tbd_decay(root, v._DEFAULT_EXCLUDE_COMPONENTS, v._DEFAULT_EXCLUDE_FILENAME_GLOBS)
    assert failures == []


def test_stage_b_tbd_lowercase_not_matched(tmp_path):
    root = _make_project(
        tmp_path,
        {
            "PROGRESS.md": _progress_active("SP_010_X"),
            "README.md": "tbd-by: SP_001 — lowercase should be ignored\n",
        },
    )
    failures = v.stage_b_tbd_decay(root, v._DEFAULT_EXCLUDE_COMPONENTS, v._DEFAULT_EXCLUDE_FILENAME_GLOBS)
    assert failures == []


# ---------------------------------------------------------------------------
# Stage C tests (25-33)
# ---------------------------------------------------------------------------


def test_stage_c_manifest_file_absent_passes_with_advisory(tmp_path, capsys):
    root = _make_project(tmp_path, {"OTHER.md": "# unrelated\n"})
    failures = v.stage_c_frontmatter(root, ["PROGRESS.md"])
    assert failures == []
    assert "not present" in capsys.readouterr().err


def test_stage_c_valid_frontmatter_passes(tmp_path):
    root = _make_project(tmp_path, {"FEATURE_LIST.md": _valid_fm("Features")})
    failures = v.stage_c_frontmatter(root, ["FEATURE_LIST.md"])
    assert failures == []


def test_stage_c_missing_opening_delimiter_fails(tmp_path):
    root = _make_project(tmp_path, {"FEATURE_LIST.md": "# no frontmatter\n"})
    failures = v.stage_c_frontmatter(root, ["FEATURE_LIST.md"])
    assert len(failures) == 1
    assert "missing frontmatter" in failures[0]


def test_stage_c_missing_status_key_fails(tmp_path):
    root = _make_project(
        tmp_path,
        {"FEATURE_LIST.md": "---\nlast-reconciled: 2026-04-13\n---\n"},
    )
    failures = v.stage_c_frontmatter(root, ["FEATURE_LIST.md"])
    assert any("'status'" in f for f in failures)


def test_stage_c_missing_last_reconciled_fails(tmp_path):
    root = _make_project(
        tmp_path,
        {"FEATURE_LIST.md": "---\nstatus: living\n---\n"},
    )
    failures = v.stage_c_frontmatter(root, ["FEATURE_LIST.md"])
    assert any("'last-reconciled'" in f for f in failures)


def test_stage_c_invalid_status_enum_fails(tmp_path):
    root = _make_project(
        tmp_path,
        {"FEATURE_LIST.md": "---\nstatus: bogus\nlast-reconciled: 2026-04-13\n---\n"},
    )
    failures = v.stage_c_frontmatter(root, ["FEATURE_LIST.md"])
    assert any("'status'" in f and "bogus" in f for f in failures)


def test_stage_c_malformed_last_reconciled_fails(tmp_path):
    root = _make_project(
        tmp_path,
        {"FEATURE_LIST.md": "---\nstatus: living\nlast-reconciled: April 13 2026\n---\n"},
    )
    failures = v.stage_c_frontmatter(root, ["FEATURE_LIST.md"])
    assert any("ISO-8601" in f for f in failures)


def test_stage_c_accepts_all_five_status_values(tmp_path):
    for status in v._ACCEPTED_STATUS_VALUES:
        root = tmp_path / status
        root.mkdir()
        (root / "FEATURE_LIST.md").write_text(
            f"---\nstatus: {status}\nlast-reconciled: 2026-04-13\n---\n",
            encoding="utf-8",
        )
        assert v.stage_c_frontmatter(root, ["FEATURE_LIST.md"]) == []


def test_stage_c_config_override_adds_to_manifest(tmp_path):
    root = _make_project(tmp_path, {"CUSTOM.md": "# no frontmatter\n"})
    failures = v.stage_c_frontmatter(root, ["CUSTOM.md"])
    assert len(failures) == 1


def test_stage_c_template_sentinel_date_fails(tmp_path):
    """1970-01-01 is the template sentinel; must be rejected so unreplaced templates cannot pass."""
    root = _make_project(
        tmp_path,
        {"FEATURE_LIST.md": "---\nstatus: living\nlast-reconciled: 1970-01-01\n---\n"},
    )
    failures = v.stage_c_frontmatter(root, ["FEATURE_LIST.md"])
    assert any("template sentinel" in f for f in failures)


def test_load_config_fallback_no_pyyaml(tmp_path, monkeypatch):
    """Fallback parser handles .validators.yml without PyYAML."""
    monkeypatch.setattr(v, "_HAS_YAML", False)
    root = tmp_path / "proj"
    root.mkdir()
    (root / ".validators.yml").write_text(
        textwrap.dedent(
            """\
            doc_reality:
              exclude_dirs: []
              dead_path_exclusions:
                - test/unit/
              duplication_threshold: 25
              paired_files:
                - [A.md, B.md]
            """
        ),
        encoding="utf-8",
    )
    cfg = v.load_config(root)
    assert cfg.get("duplication_threshold") == 25
    assert "test/unit/" in cfg.get("dead_path_exclusions", [])
    pairs = cfg.get("paired_files", [])
    assert pairs and pairs[0] == ["A.md", "B.md"]


# ---------------------------------------------------------------------------
# Stage D tests (34-41)
# ---------------------------------------------------------------------------


def test_stage_d_no_pairs_passes(tmp_path):
    root = _make_project(tmp_path, {"A.md": "alpha\n", "B.md": "beta\n"})
    failures = v.stage_d_paired_duplication(root, [], 30)
    assert failures == []


def test_stage_d_pair_with_missing_file_skipped(tmp_path):
    root = _make_project(tmp_path, {"A.md": "only one\n"})
    failures = v.stage_d_paired_duplication(root, [["A.md", "B.md"]], 30)
    assert failures == []


def test_stage_d_pair_no_duplication_passes(tmp_path):
    root = _make_project(tmp_path, {"A.md": "unique A content\n", "B.md": "totally different B\n"})
    failures = v.stage_d_paired_duplication(root, [["A.md", "B.md"]], 30)
    assert failures == []


def _dup_content(prefix: str, n_lines: int) -> str:
    body = "\n".join(f"{prefix} line {i}" for i in range(n_lines))
    return f"# header\n{body}\n"


def test_stage_d_pair_duplication_30_lines_fails(tmp_path):
    shared = "\n".join(f"shared line {i}" for i in range(30)) + "\n"
    root = _make_project(
        tmp_path,
        {"A.md": f"# A\n{shared}extra A\n", "B.md": f"# B\n{shared}extra B\n"},
    )
    failures = v.stage_d_paired_duplication(root, [["A.md", "B.md"]], 30)
    assert len(failures) >= 1


def test_stage_d_pair_duplication_19_lines_passes(tmp_path):
    shared = "\n".join(f"shared {i}" for i in range(19)) + "\n"
    root = _make_project(
        tmp_path,
        {"A.md": f"# A\n{shared}extra A\n", "B.md": f"# B\n{shared}extra B\n"},
    )
    failures = v.stage_d_paired_duplication(root, [["A.md", "B.md"]], 30)
    assert failures == []


def test_stage_d_inherits_block_suppresses_detection(tmp_path):
    shared = "\n".join(f"shared line {i}" for i in range(30))
    root = _make_project(
        tmp_path,
        {
            "A.md": f"# A\n@inherits: B.md\n{shared}\n@inherits-end:\nextra\n",
            "B.md": f"# B\n{shared}\nextra B\n",
        },
    )
    failures = v.stage_d_paired_duplication(root, [["A.md", "B.md"]], 30)
    assert failures == []


def test_stage_d_unterminated_inherits_emits_advisory_does_not_bypass(tmp_path, capsys):
    shared = "\n".join(f"shared line {i}" for i in range(30))
    # A has unterminated @inherits: — only the directive line itself is suppressed.
    # The shared block still matches B, so duplication should still fail.
    root = _make_project(
        tmp_path,
        {
            "A.md": f"# A\n@inherits: B.md\n{shared}\n",
            "B.md": f"# B\n{shared}\n",
        },
    )
    failures = v.stage_d_paired_duplication(root, [["A.md", "B.md"]], 30)
    assert "unterminated" in capsys.readouterr().err
    assert len(failures) >= 1


def test_stage_d_custom_threshold_via_config(tmp_path):
    shared = "\n".join(f"shared {i}" for i in range(25)) + "\n"
    root = _make_project(
        tmp_path,
        {"A.md": f"# A\n{shared}extra A\n", "B.md": f"# B\n{shared}extra B\n"},
    )
    # Threshold=20 triggers on 25-line run; default would be 30 (wouldn't trigger).
    failures = v.stage_d_paired_duplication(root, [["A.md", "B.md"]], 20)
    assert len(failures) >= 1


# ---------------------------------------------------------------------------
# Integration / CLI tests (42-45)
# ---------------------------------------------------------------------------


def _invoke_cli(project_root: Path, extra: list[str] | None = None) -> subprocess.CompletedProcess:
    script = Path(v.__file__)
    args = [sys.executable, str(script), str(project_root)]
    if extra:
        args.extend(extra)
    return subprocess.run(args, capture_output=True, text=True)


def test_cli_happy_path_exits_zero(tmp_path):
    root = _make_project(
        tmp_path,
        {
            "PROGRESS.md": _progress_active("SP_001_Clean"),
            "README.md": "# clean\n",
        },
    )
    result = _invoke_cli(root)
    assert result.returncode == 0, result.stderr


def test_cli_dead_path_exits_one(tmp_path):
    root = _make_project(
        tmp_path,
        {"PROGRESS.md": _progress_active("SP_001_X"), "README.md": "`src/ghost.py`\n"},
    )
    result = _invoke_cli(root)
    assert result.returncode == 1


def test_cli_skip_stage_flag_skips_stage(tmp_path):
    root = _make_project(
        tmp_path,
        {"PROGRESS.md": _progress_active("SP_001_X"), "README.md": "`src/ghost.py`\n"},
    )
    # Skip A means the dead path isn't caught.
    result = _invoke_cli(root, ["--skip-stage", "A"])
    assert result.returncode == 0


def test_run_all_py_invokes_validate_doc_reality(tmp_path):
    """Integration: run_all.py invokes validate_doc_reality when present."""
    # Use a fake validators dir with only validate_doc_reality to prove it's on the list.
    fake_dir = tmp_path / "fake_validators"
    fake_dir.mkdir()
    for name in [
        "validate_structure",
        "validate_workspace",
        "validate_tdd",
        "validate_rdd",
        "validate_sprint",
        "validate_doc_reality",
    ]:
        (fake_dir / f"{name}.py").write_text(
            "import sys; print(f'ran {__file__}'); sys.exit(0)\n",
            encoding="utf-8",
        )
    env = os.environ.copy()
    env["_VALIDATOR_DIR_OVERRIDE"] = str(fake_dir)
    run_all_path = Path(__file__).parent / "run_all.py"
    proj = tmp_path / "proj"
    proj.mkdir()
    result = subprocess.run(
        [sys.executable, str(run_all_path), str(proj)],
        capture_output=True,
        text=True,
        env=env,
    )
    assert "validate_doc_reality" in result.stdout + result.stderr
