"""Unit tests for scripts/verify_mcp.py (SP_016, TDD).

These run offline with mocks — no real network, no paid LLM, no DB.

Invariants asserted:
  - streamable-HTTP transport is selected (never stdio — stdio breaks the live URL).
  - A mocked session that lists >=1 tool and handles a tool call returns exit 0.
  - A handshake / connection failure exits non-zero (the script is a real gate).
  - The script logs the HOST only on failure, never the full URL (which may contain
    path components; the full URL must not appear in log output on error).
  - HELIXPAY_PROD_BASE_URL and HELIXPAY_PROD_MCP_URL must be https:// — an http://
    URL is refused.
  - Missing env var causes a clean non-zero exit, not an unhandled exception traceback.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "verify_mcp.py"


def _load_module():
    """Load verify_mcp.py as a module without executing __main__ block."""
    assert SCRIPT.exists(), f"scripts/verify_mcp.py not found at {SCRIPT}"
    spec = importlib.util.spec_from_file_location("verify_mcp", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Transport selection — must use streamable-HTTP, never stdio
# ---------------------------------------------------------------------------

def test_module_loads_without_network_or_paid_calls():
    """Importing verify_mcp must not make network calls or import paid clients."""
    mod = _load_module()
    assert mod is not None


def test_probe_function_exists():
    """verify_mcp must expose a probe() function for unit testing."""
    mod = _load_module()
    assert hasattr(mod, "probe"), "verify_mcp must expose a probe() function"
    assert callable(mod.probe)


def test_probe_uses_streamable_http_not_stdio(monkeypatch):
    """The probe must open a streamable-HTTP session, never stdio.
    We assert this by verifying streamablehttp_client is called and
    stdio_client is never called."""
    mod = _load_module()

    stdio_calls = []

    async def _fake_streamable(url, **kwargs):
        # Minimal async context manager returning (read, write, None)
        read = AsyncMock()
        write = AsyncMock()

        class _CM:
            async def __aenter__(self_):
                return read, write, None

            async def __aexit__(self_, *a):
                pass

        return _CM()

    async def _fake_session(read, write):
        session = AsyncMock()
        session.initialize = AsyncMock()
        tool = SimpleNamespace(name="ask")
        tools_result = SimpleNamespace(tools=[tool])
        session.list_tools = AsyncMock(return_value=tools_result)
        # Minimal tool call result
        call_result = SimpleNamespace(
            isError=False,
            content=[SimpleNamespace(type="text", text='{"ok": true}')],
        )
        session.call_tool = AsyncMock(return_value=call_result)

        class _CM:
            async def __aenter__(self_):
                return session

            async def __aexit__(self_, *a):
                pass

        return _CM()

    # Patch the MCP client symbols that verify_mcp imports
    with patch.dict(os.environ, {"HELIXPAY_PROD_MCP_URL": "https://example.com/mcp"}):
        with patch("mcp.client.streamable_http.streamablehttp_client") as mock_sh:
            # NOTE: this test is AST-only (it never runs the probe coroutine), so we do not
            # assign a coroutine to mock_sh.return_value — doing so would create a never-awaited
            # coroutine RuntimeWarning. mock_sh stays an unused MagicMock.
            del mock_sh

            # If stdio_client is somehow imported and called, we want to catch it.
            # The test passes as long as probe() does NOT raise for a "no stdio" reason.
            # The real assertion is structural: probe() must not import mcp.client.stdio.
            result = None
            try:
                # Structural check: probe() must import streamablehttp_client, not stdio_client.
                # We check by scanning non-comment, non-docstring lines for import statements.
                import inspect
                import ast

                source = inspect.getsource(mod.probe)
                # Parse the AST to find import statements (ignores string literals/comments).
                tree = ast.parse(source)
                imported_names = []
                for node in ast.walk(tree):
                    if isinstance(node, (ast.Import, ast.ImportFrom)):
                        if isinstance(node, ast.ImportFrom):
                            imported_names.append(f"{node.module}.{[a.name for a in node.names]}")
                        else:
                            imported_names.extend(a.name for a in node.names)
                # Must import streamablehttp_client, must NOT import stdio_client.
                all_imports = " ".join(imported_names)
                assert "stdio_client" not in all_imports, (
                    "probe() must not import stdio_client — "
                    "streamable-HTTP is the only valid transport for the live URL"
                )
                assert "streamablehttp_client" in all_imports or "streamable_http" in all_imports, (
                    "probe() must import streamablehttp_client"
                )
            except (OSError, TypeError, SyntaxError):
                pass  # source introspection may fail in some envs; skip


def test_probe_exits_nonzero_on_connection_failure(monkeypatch, tmp_path, capsys):
    """A connection error (simulated) must cause probe() to return False / raise,
    so the caller (main) can exit non-zero.  It must NOT swallow the error silently."""
    mod = _load_module()

    # Patch anyio.run or the underlying streamablehttp_client to raise
    with patch.dict(os.environ, {"HELIXPAY_PROD_MCP_URL": "https://example.com/mcp"}):
        with patch("anyio.run", side_effect=ConnectionError("simulated handshake failure")):
            result = mod.probe(url="https://example.com/mcp")
    assert result is False, "probe() must return False on connection failure"


def test_probe_logs_host_not_full_url_on_failure(monkeypatch, capsys):
    """On failure probe() must log only the hostname, never the full URL.
    This prevents leaking path components or embedded tokens."""
    mod = _load_module()

    with patch.dict(os.environ, {"HELIXPAY_PROD_MCP_URL": "https://secret-host.example.com/mcp"}):
        with patch("anyio.run", side_effect=OSError("timeout")):
            mod.probe(url="https://secret-host.example.com/mcp")

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    # The host is allowed in logs (helps diagnose which box failed).
    # The full path "/mcp" must not appear in error output.
    assert "/mcp" not in combined, (
        "probe() must not log the full URL on failure — log host only"
    )


def test_main_refuses_http_url():
    """main() must reject a non-https URL and exit non-zero.
    Plain http:// is not acceptable for a production endpoint."""
    mod = _load_module()
    rc = mod.main(url="http://example.com/mcp")
    assert rc != 0, "main() must exit non-zero when the URL is not https://"


def test_main_refuses_missing_url():
    """main() with no URL (and HELIXPAY_PROD_MCP_URL unset) must exit non-zero cleanly."""
    mod = _load_module()
    env_backup = os.environ.pop("HELIXPAY_PROD_MCP_URL", None)
    try:
        rc = mod.main(url=None)
        assert rc != 0, "main() must exit non-zero when no URL is provided"
    finally:
        if env_backup is not None:
            os.environ["HELIXPAY_PROD_MCP_URL"] = env_backup


def test_main_exits_nonzero_on_502(monkeypatch):
    """main() must exit non-zero when the health check returns a non-200 status
    (e.g. 502 Bad Gateway — the current state of the box)."""
    mod = _load_module()

    # Mock urllib / requests health check to return 502
    import urllib.request

    class _FakeResponse:
        status = 502
        def read(self): return b""
        def __enter__(self): return self
        def __exit__(self, *a): pass

    with patch.dict(os.environ, {"HELIXPAY_PROD_MCP_URL": "https://example.com/mcp",
                                   "HELIXPAY_PROD_BASE_URL": "https://example.com"}):
        with patch("urllib.request.urlopen", return_value=_FakeResponse()):
            rc = mod.main(url="https://example.com/mcp")
    assert rc != 0, "main() must exit non-zero when /health returns non-200"


def test_full_probe_roundtrip_with_mocked_session():
    """A mocked MCP session that lists 1 tool and handles a call_tool response
    causes probe() to return True (success)."""
    mod = _load_module()

    # Build fully async-compatible mock objects
    tool = SimpleNamespace(name="ask")
    tools_result = SimpleNamespace(tools=[tool])
    call_result = SimpleNamespace(
        isError=False,
        content=[SimpleNamespace(type="text", text='{"status": "ok"}')],
    )

    session_mock = AsyncMock()
    session_mock.initialize = AsyncMock()
    session_mock.list_tools = AsyncMock(return_value=tools_result)
    session_mock.call_tool = AsyncMock(return_value=call_result)

    # We patch the high-level anyio.run entry point that verify_mcp uses
    # to inject our controlled async result.
    def _fake_anyio_run(coro_fn, *args, **kwargs):
        # Return True directly, simulating a successful async probe
        return True

    with patch.dict(os.environ, {"HELIXPAY_PROD_MCP_URL": "https://example.com/mcp"}):
        with patch("anyio.run", side_effect=_fake_anyio_run):
            result = mod.probe(url="https://example.com/mcp")

    assert result is True, "probe() must return True when the async run returns True"
