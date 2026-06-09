"""
Tests for validate_workspace.py

Validator contract:
- Bootstrap files are scanned for size: warn at 18,000 bytes, hard-fail at 20,000 bytes
- Bootstrap files are scanned for credential patterns:
    - ssh-rsa (SSH public keys)
    - BEGIN PRIVATE KEY / BEGIN RSA/EC/DSA/OPENSSH PRIVATE KEY (private keys)
    - password= (plaintext password assignments)
    - assignment-style secrets: api_key/secret_key/client_secret/access_token/
      auth_token/secret/token followed by `=`/`:` and a >=8-char value
    - provider key formats: AWS AKIA…, OpenAI/Anthropic sk-…, GitHub ghp_…,
      Slack xox?-…, Google AIza…, and `Bearer <token>` values
    - prose that merely mentions secrets/tokens (no value) must NOT match
- Bootstrap file list is configurable via .validators.yml (key: bootstrap_files)
- Default bootstrap files apply when .validators.yml is absent or has no bootstrap_files key
- Size thresholds are measured in bytes, not character count (multibyte UTF-8 matters)
- Returns 0 on pass, 1 on failure
"""
import subprocess
import sys
from pathlib import Path

import pytest

VALIDATOR = Path(__file__).parent / "validate_workspace.py"

# Size boundary constants matching the validator's thresholds
WARN_LIMIT = 18_000
HARD_LIMIT = 20_000


def run_validator(project_root: Path, *extra_args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(project_root), *extra_args],
        capture_output=True,
        text=True,
    )


def write_config(project_root: Path, config: dict) -> None:
    """Write .validators.yml as hand-crafted YAML. Only handles str lists as values."""
    lines = []
    for key, value in config.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
        else:
            lines.append(f"{key}: {value}")
    (project_root / ".validators.yml").write_text("\n".join(lines) + "\n")


def make_file_of_size(path: Path, size_bytes: int, content_char: str = "x") -> None:
    """Write a file whose UTF-8 byte length equals size_bytes."""
    path.write_bytes(content_char.encode("utf-8") * size_bytes)


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


def test_passes_within_limits(tmp_path: Path) -> None:
    """All bootstrap files under 18K bytes with no credentials exit 0."""
    bootstrap_file = tmp_path / "AGENT_INSTRUCTIONS.md"
    make_file_of_size(bootstrap_file, 5_000)

    write_config(tmp_path, {"bootstrap_files": ["AGENT_INSTRUCTIONS.md"]})

    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stderr


def test_passes_file_exactly_at_warn_boundary(tmp_path: Path) -> None:
    """A file exactly at 18,000 bytes passes (warn threshold is exclusive)."""
    bootstrap_file = tmp_path / "AGENT_INSTRUCTIONS.md"
    make_file_of_size(bootstrap_file, WARN_LIMIT)

    write_config(tmp_path, {"bootstrap_files": ["AGENT_INSTRUCTIONS.md"]})

    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stderr


def test_default_files_when_no_config(tmp_path: Path) -> None:
    """When .validators.yml is absent, default bootstrap files are checked.
    If those files don't exist, the validator exits 0 (advisory, not hard fail)."""
    # No .validators.yml, no default files — nothing to fail on
    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stderr


def test_uses_custom_config_bootstrap_files(tmp_path: Path) -> None:
    """Custom bootstrap_files list is used instead of defaults."""
    custom_file = tmp_path / "MY_BOOTSTRAP.md"
    make_file_of_size(custom_file, 1_000)

    write_config(tmp_path, {"bootstrap_files": ["MY_BOOTSTRAP.md"]})

    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# Warning threshold tests (warn but still exit 0 at 18K–20K range)
# ---------------------------------------------------------------------------


def test_warns_approaching_limit(tmp_path: Path) -> None:
    """A file at 18,500 bytes triggers a warning but the validator still exits 0."""
    bootstrap_file = tmp_path / "AGENT_INSTRUCTIONS.md"
    make_file_of_size(bootstrap_file, 18_500)

    write_config(tmp_path, {"bootstrap_files": ["AGENT_INSTRUCTIONS.md"]})

    result = run_validator(tmp_path)
    # Warning issued, but not a hard failure
    assert result.returncode == 0, result.stderr
    # Warning message should appear in stdout or stderr
    combined = result.stdout + result.stderr
    assert "warn" in combined.lower() or "approaching" in combined.lower() or "18" in combined, (
        "Expected a size warning in output"
    )


def test_warns_at_just_above_warn_limit(tmp_path: Path) -> None:
    """A file at 18,001 bytes triggers a warning (just over threshold)."""
    bootstrap_file = tmp_path / "AGENT_INSTRUCTIONS.md"
    make_file_of_size(bootstrap_file, WARN_LIMIT + 1)

    write_config(tmp_path, {"bootstrap_files": ["AGENT_INSTRUCTIONS.md"]})

    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# Hard-fail size tests
# ---------------------------------------------------------------------------


def test_fails_over_limit(tmp_path: Path) -> None:
    """A file at 21,000 bytes exceeds the 20K hard limit and causes failure."""
    bootstrap_file = tmp_path / "AGENT_INSTRUCTIONS.md"
    make_file_of_size(bootstrap_file, 21_000)

    write_config(tmp_path, {"bootstrap_files": ["AGENT_INSTRUCTIONS.md"]})

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


def test_fails_file_exactly_at_hard_limit(tmp_path: Path) -> None:
    """A file exactly at 20,000 bytes hits the hard limit and causes failure."""
    bootstrap_file = tmp_path / "AGENT_INSTRUCTIONS.md"
    make_file_of_size(bootstrap_file, HARD_LIMIT)

    write_config(tmp_path, {"bootstrap_files": ["AGENT_INSTRUCTIONS.md"]})

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


def test_fails_just_one_byte_over_hard_limit(tmp_path: Path) -> None:
    """A file at 20,001 bytes fails."""
    bootstrap_file = tmp_path / "AGENT_INSTRUCTIONS.md"
    make_file_of_size(bootstrap_file, HARD_LIMIT + 1)

    write_config(tmp_path, {"bootstrap_files": ["AGENT_INSTRUCTIONS.md"]})

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


# ---------------------------------------------------------------------------
# Credential scanning tests
# ---------------------------------------------------------------------------


def test_fails_credential_found_ssh_public_key(tmp_path: Path) -> None:
    """A file containing an SSH public key pattern causes failure."""
    bootstrap_file = tmp_path / "AGENT_INSTRUCTIONS.md"
    bootstrap_file.write_text(
        "# Instructions\n\nConnect with: ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAAB user@host\n"
    )

    write_config(tmp_path, {"bootstrap_files": ["AGENT_INSTRUCTIONS.md"]})

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


def test_fails_private_key_found_rsa(tmp_path: Path) -> None:
    """A file containing an RSA private key header causes failure."""
    bootstrap_file = tmp_path / "AGENT_INSTRUCTIONS.md"
    bootstrap_file.write_text(
        "# Instructions\n\n-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----\n"
    )

    write_config(tmp_path, {"bootstrap_files": ["AGENT_INSTRUCTIONS.md"]})

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


def test_fails_private_key_found_generic(tmp_path: Path) -> None:
    """A file containing a generic PRIVATE KEY header causes failure."""
    bootstrap_file = tmp_path / "AGENT_INSTRUCTIONS.md"
    bootstrap_file.write_text(
        "# Key material\n-----BEGIN PRIVATE KEY-----\nMIIEvAIBADANBgkq...\n-----END PRIVATE KEY-----\n"
    )

    write_config(tmp_path, {"bootstrap_files": ["AGENT_INSTRUCTIONS.md"]})

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


def test_fails_password_assignment_found(tmp_path: Path) -> None:
    """A file containing 'password=' (plaintext) causes failure."""
    bootstrap_file = tmp_path / "AGENT_INSTRUCTIONS.md"
    bootstrap_file.write_text(
        "# Config\nDB settings:\npassword=supersecret123\nhost=localhost\n"
    )

    write_config(tmp_path, {"bootstrap_files": ["AGENT_INSTRUCTIONS.md"]})

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


def test_fails_password_env_var_style(tmp_path: Path) -> None:
    """PASSWORD= (uppercase) is also detected as a credential leak."""
    bootstrap_file = tmp_path / "AGENT_INSTRUCTIONS.md"
    bootstrap_file.write_text("export PASSWORD=hunter2\n")

    write_config(tmp_path, {"bootstrap_files": ["AGENT_INSTRUCTIONS.md"]})

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


def test_passes_file_discussing_credentials_without_containing_them(tmp_path: Path) -> None:
    """A file that talks about credentials conceptually but has no actual key data passes."""
    bootstrap_file = tmp_path / "AGENT_INSTRUCTIONS.md"
    bootstrap_file.write_text(
        "# Security Guidelines\n\n"
        "Never store SSH keys in documentation files.\n"
        "Avoid plaintext passwords in configuration.\n"
        "Use environment variables for secrets.\n"
        "Rotate every API token and secret regularly; never paste a token here.\n"
    )

    write_config(tmp_path, {"bootstrap_files": ["AGENT_INSTRUCTIONS.md"]})

    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# Expanded credential scanning (M-3): assignment-style + provider key formats
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("leak", [
    "API_KEY=sk_live_0123456789abcdef",
    "OPENAI_API_KEY = abc123def456ghi789",
    'api_key: "abcd1234efgh5678"',
    "secret_key=AKIAIOSFODNN7EXAMPLE12345",
    "client_secret: 0123456789abcdefghij",
    "access_token=ghijklmnop1234567890",
    "auth_token = 0123456789abcdefghij",
    "token=0123456789abcdefghij",
    "secret = supersecretvalue123",
])
def test_fails_assignment_style_secret(tmp_path: Path, leak: str) -> None:
    """`<secret-key> = <value>` style leaks are detected."""
    bootstrap_file = tmp_path / "AGENT_INSTRUCTIONS.md"
    bootstrap_file.write_text(f"# Config\n{leak}\n")
    write_config(tmp_path, {"bootstrap_files": ["AGENT_INSTRUCTIONS.md"]})

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


@pytest.mark.parametrize("leak", [
    "AKIAIOSFODNN7EXAMPLE",                              # AWS access key id
    "sk-ant-api03-AbCdEf0123456789ZyXwVu",               # Anthropic-style
    "sk-proj-0123456789ABCDEFabcdef",                    # OpenAI-style
    "ghp_0123456789abcdefABCDEF0123456789abcd",          # GitHub PAT
    "xoxb-0123456789-abcdefghij",                        # Slack bot token
    "AIzaSyA0123456789abcdefghijklmnopqrstuv",           # Google API key
    "Authorization: Bearer 0123456789abcdef.token-xyz",  # Bearer token
])
def test_fails_provider_key_format(tmp_path: Path, leak: str) -> None:
    """Self-identifying provider key formats are detected without an assignment."""
    bootstrap_file = tmp_path / "AGENT_INSTRUCTIONS.md"
    bootstrap_file.write_text(f"# Notes\nleftover value: {leak}\n")
    write_config(tmp_path, {"bootstrap_files": ["AGENT_INSTRUCTIONS.md"]})

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


@pytest.mark.parametrize("prose", [
    "Set the API key as an environment variable, never in this file.",
    "The auth token is rotated automatically by the platform.",
    "Store every secret in the vault; do not commit secrets.",
    "Use a bearer token for the request (configured elsewhere).",
])
def test_passes_prose_mentioning_secrets(tmp_path: Path, prose: str) -> None:
    """Prose that mentions secrets/tokens without an actual value must not match."""
    bootstrap_file = tmp_path / "AGENT_INSTRUCTIONS.md"
    bootstrap_file.write_text(f"# Guidance\n{prose}\n")
    write_config(tmp_path, {"bootstrap_files": ["AGENT_INSTRUCTIONS.md"]})

    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# Byte vs character counting
# ---------------------------------------------------------------------------


def test_measures_bytes_not_chars(tmp_path: Path) -> None:
    """File size check uses byte length, not character count.

    A file with many 3-byte UTF-8 characters (e.g., Chinese) can exceed the
    byte limit even with fewer characters than a pure ASCII file of the same
    character count.
    """
    bootstrap_file = tmp_path / "AGENT_INSTRUCTIONS.md"
    # Each Chinese character is 3 bytes in UTF-8
    # 7,000 such characters = 21,000 bytes → over the 20K hard limit
    chinese_char = "\u4e2d"  # 中 — 3 bytes in UTF-8
    content = chinese_char * 7_000  # 21,000 bytes
    bootstrap_file.write_text(content, encoding="utf-8")

    byte_size = len(content.encode("utf-8"))
    assert byte_size == 21_000, f"Expected 21000 bytes, got {byte_size}"

    write_config(tmp_path, {"bootstrap_files": ["AGENT_INSTRUCTIONS.md"]})

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


def test_multibyte_file_under_limit_passes(tmp_path: Path) -> None:
    """A file with multibyte chars that is under 18K bytes passes."""
    bootstrap_file = tmp_path / "AGENT_INSTRUCTIONS.md"
    # 5,000 × 3 bytes = 15,000 bytes — well under the 18K warning threshold
    chinese_char = "\u4e2d"
    content = chinese_char * 5_000
    bootstrap_file.write_text(content, encoding="utf-8")

    byte_size = len(content.encode("utf-8"))
    assert byte_size == 15_000, f"Expected 15000 bytes, got {byte_size}"

    write_config(tmp_path, {"bootstrap_files": ["AGENT_INSTRUCTIONS.md"]})

    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# Multiple bootstrap files
# ---------------------------------------------------------------------------


def test_fails_if_any_bootstrap_file_has_credential(tmp_path: Path) -> None:
    """When multiple bootstrap files are configured, ALL are scanned."""
    clean_file = tmp_path / "INSTRUCTIONS.md"
    clean_file.write_text("# Instructions\nAll good.\n")

    dirty_file = tmp_path / "CONFIG.md"
    dirty_file.write_text("ssh-rsa AAAAB3NzaC1yc2E secret_key_here\n")

    write_config(
        tmp_path,
        {"bootstrap_files": ["INSTRUCTIONS.md", "CONFIG.md"]},
    )

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


def test_fails_if_any_bootstrap_file_exceeds_size(tmp_path: Path) -> None:
    """When multiple files are configured, the one over the limit causes failure."""
    small_file = tmp_path / "INSTRUCTIONS.md"
    make_file_of_size(small_file, 1_000)

    large_file = tmp_path / "CONFIG.md"
    make_file_of_size(large_file, 25_000)

    write_config(
        tmp_path,
        {"bootstrap_files": ["INSTRUCTIONS.md", "CONFIG.md"]},
    )

    result = run_validator(tmp_path)
    assert result.returncode == 1, result.stdout


def test_missing_bootstrap_file_is_skipped_not_failed(tmp_path: Path) -> None:
    """A configured bootstrap file that does not exist on disk is skipped gracefully."""
    write_config(
        tmp_path,
        {"bootstrap_files": ["NONEXISTENT.md"]},
    )
    # NONEXISTENT.md is not created — validator should not crash or fail

    result = run_validator(tmp_path)
    assert result.returncode == 0, result.stderr
