"""MCP agent-reachability verifier (SP_016).

Asserts:
  1. https://<host>/health returns 200.
  2. A streamable-HTTP MCP session to /mcp initialises successfully.
  3. list_tools returns >= 1 tool (this initialize + list IS the round-trip — see probe()).
     A blind call_tool is intentionally NOT made (the first tool may be paid `ask`).

Transport: ALWAYS streamable-HTTP (never stdio — stdio is local-only and breaks
the live URL, per CLAUDE.md gotchas).

URL source (in priority order):
  * ``--url`` CLI argument
  * ``HELIXPAY_PROD_MCP_URL`` env var (e.g. https://helixpay.serverado.app/mcp)

On success exits 0.  On any failure exits non-zero (this is a real gate, not a
log line — scripts/full_run.py treats a non-True return from its mcp_check as a
refusal).

Secret discipline: logs the HOSTNAME only on failure, never the full URL (which
may contain path components or embedded credentials).

Usage:
    python scripts/verify_mcp.py
    python scripts/verify_mcp.py --url https://helixpay.serverado.app/mcp
    python scripts/verify_mcp.py --url https://helixpay.serverado.app/mcp --base-url https://helixpay.serverado.app
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.request
import urllib.error
from urllib.parse import urlsplit


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

def _check_health(base_url: str) -> bool:
    """GET <base_url>/health.  Returns True iff 200. Logs host only on failure."""
    health_url = base_url.rstrip("/") + "/health"
    host = urlsplit(base_url).hostname or "<host>"
    try:
        with urllib.request.urlopen(health_url, timeout=15) as resp:  # noqa: S310
            if resp.status == 200:
                return True
            print(
                f"verify_mcp: /health at {host} returned {resp.status} (expected 200)",
                file=sys.stderr,
            )
            return False
    except urllib.error.HTTPError as exc:
        print(
            f"verify_mcp: /health at {host} failed with HTTP {exc.code}",
            file=sys.stderr,
        )
        return False
    except Exception as exc:  # noqa: BLE001
        print(
            f"verify_mcp: /health at {host} unreachable ({type(exc).__name__})",
            file=sys.stderr,
        )
        return False


# ---------------------------------------------------------------------------
# MCP streamable-HTTP probe
# ---------------------------------------------------------------------------

def probe(url: str) -> bool:
    """Open a streamable-HTTP MCP session, list tools (>=1), call the first tool.

    Returns True on success, False on any failure.  Logs host only on failure.
    NEVER uses stdio transport — streamable-HTTP is the required transport for
    the live URL.

    This function is unit-testable: callers may patch ``anyio.run`` to inject a
    mock result without touching the network.
    """
    host = urlsplit(url).hostname or "<host>"

    async def _run_probe() -> bool:
        # Lazy import: keeps the refusal path free of the MCP client dep at module load.
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        # streamablehttp_client — the only sanctioned transport for a remote URL.
        # stdio_client is intentionally NOT imported (it is local-process-only and
        # breaks the live URL story).
        async with streamablehttp_client(url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools_result = await session.list_tools()
                # A successful initialize + list_tools IS the round-trip: it exercises the
                # full streamable-HTTP transport + MCP session layer and proves an external
                # agent can discover the tools. We deliberately do NOT call an arbitrary first
                # tool (Stage-5 M1): the first registered tool may be `ask` (paid Opus), so a
                # blind call_tool({}) could bill on every gate run or false-negative on a tool
                # that requires args. The real tool exercise is the Phase-C live answer gate.
                return bool(tools_result.tools)

    try:
        import anyio
        return bool(anyio.run(_run_probe))
    except Exception as exc:  # noqa: BLE001 — never surface a URL/DSN-bearing message
        print(
            f"verify_mcp: MCP round-trip to {host} failed ({type(exc).__name__})",
            file=sys.stderr,
        )
        return False


# ---------------------------------------------------------------------------
# main() — orchestrates health + MCP probe and returns an exit code
# ---------------------------------------------------------------------------

def main(
    url: str | None = None,
    base_url: str | None = None,
) -> int:
    """Entry point. Returns exit code (0 = ok, non-zero = gate failed).

    Parameters
    ----------
    url:
        Explicit MCP URL override (used by tests and ``--url`` CLI arg).
        Falls back to ``HELIXPAY_PROD_MCP_URL`` env var.
    base_url:
        Explicit base URL for the /health check.  Derived from *url* if omitted.
    """
    # Resolve MCP URL
    mcp_url = url or os.environ.get("HELIXPAY_PROD_MCP_URL")
    if not mcp_url:
        print(
            "verify_mcp: HELIXPAY_PROD_MCP_URL is unset and --url was not provided. "
            "Set it to e.g. https://helixpay.serverado.app/mcp",
            file=sys.stderr,
        )
        return 1

    # Enforce HTTPS — stdio and plain HTTP are both disallowed for the live endpoint.
    if not mcp_url.startswith("https://"):
        print(
            f"verify_mcp: URL must be https:// (got {mcp_url[:12]!r}...). "
            "Plain http:// and stdio are not acceptable for the production endpoint.",
            file=sys.stderr,
        )
        return 1

    # Derive base_url from the MCP URL if not supplied explicitly.
    if not base_url:
        parsed = urlsplit(mcp_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
    elif not base_url.startswith("https://"):
        print(
            f"verify_mcp: base-url must be https:// (got {base_url[:12]!r}...)",
            file=sys.stderr,
        )
        return 1

    host = urlsplit(mcp_url).hostname or "<host>"
    print(f"verify_mcp: checking {host} ...", file=sys.stderr)

    # Step 1: health check
    print(f"  [1/2] GET {host}/health ...", file=sys.stderr)
    if not _check_health(base_url):
        print(
            f"verify_mcp: FAIL — /health at {host} did not return 200. "
            "Is the app running? (deploy/deploy.sh first)",
            file=sys.stderr,
        )
        return 1

    # Step 2: MCP streamable-HTTP round-trip
    print(f"  [2/2] MCP streamable-HTTP round-trip at {host}/mcp ...", file=sys.stderr)
    if not probe(url=mcp_url):
        print(
            f"verify_mcp: FAIL — MCP session to {host} did not complete successfully. "
            "Check that the app is up and /mcp is reachable over HTTPS.",
            file=sys.stderr,
        )
        return 1

    print(
        f"verify_mcp: OK — {host}/health is 200 and MCP round-trip succeeded.",
        file=sys.stderr,
    )
    return 0


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _cli() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify the live HelixPay MCP endpoint is reachable via streamable-HTTP. "
            "Exits 0 on success, non-zero on any failure."
        )
    )
    parser.add_argument(
        "--url",
        default=None,
        help="MCP URL (default: $HELIXPAY_PROD_MCP_URL). Must be https://.",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        dest="base_url",
        help="Base URL for the /health check (default: derived from --url).",
    )
    args = parser.parse_args()
    return main(url=args.url, base_url=args.base_url)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
