"""The hard-rule guard for the one PAID full extraction (SP_015).

`scripts/full_run.py` is the *sanctioned* entry to a 44-doc `record ./data`. It refuses
unless it can **re-derive** the proof (never trust a human-typed flag) AND confirm the live
deployment:

  1. **Proven** — `check_smoke`'s machine JSON reports 9/9 PASS, and the doc content hashes
     in it still match the live corpus (a stale or hand-edited proof fails the recompute).
  2. **Deployed** — a real streamable-HTTP MCP round-trip to the production endpoint
     succeeds (not `/health`, which always 200s; not stdio).

On refusal it exits non-zero **before** importing or constructing anything paid
(`replay`/`AnthropicClient` are imported lazily, only on the permit branch), so a refused
run costs nothing.

IMPORTANT (advisory, not enforcing — see SP_015 Hand-off fork): `make ingest`,
`make ingest-record`, `python -m helixpay.ingest.replay record ./data`, and
`deploy/deploy.sh` reach the paid extractor WITHOUT this guard. Closing those doors needs a
config-level authorization chokepoint (production substrate; deferred). Until then this guard
is the sanctioned-but-bypassable path; the rule is held by discipline + the SP_016 deploy
decoupling.

Secrets: never logs a URL with credentials or a DSN (CLAUDE.md §7) — host only on failure.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlsplit

# Pure, paid-free helper — safe to import at module load (no DB/net/LLM).
from eval.smoke.check_smoke import corpus_fingerprint
from eval.smoke.manifest import SOURCE_URIS

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROOF = ROOT / "workspace" / "acceptance" / "SP015_smoke_result.json"


def gate(
    proof_path: Path,
    corpus_root: Path,
    mcp_check: Callable[[], bool],
    uris: list[str] = SOURCE_URIS,
) -> tuple[bool, str]:
    """Re-derive the gate. Returns (permit, reason). No paid construction on any path."""
    proof_path = Path(proof_path)
    if not proof_path.exists():
        return False, f"refuse: no machine proof at {proof_path.name} (run check_smoke first)"
    try:
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return False, "refuse: proof unreadable / not valid JSON"

    docs = proof.get("docs", {})
    for uri in uris:
        entry = docs.get(uri)
        if not entry or entry.get("verdict") != "PASS":
            state = entry.get("verdict") if entry else "absent"
            return False, f"refuse: {uri} is {state}, not PASS (a typed flag does not pass it)"

    if proof.get("fingerprint") != corpus_fingerprint(corpus_root, uris):
        return False, "refuse: corpus changed since the proof (content hash mismatch — stale proof)"

    # NOTE: we deliberately re-derive from per-doc verdicts + hashes above; the proof's own
    # `all_green` field is never trusted. A `mcp_check` that raises is a refusal, not a crash.
    try:
        mcp_ok = mcp_check()
    except Exception as exc:  # noqa: BLE001 — a failing probe is a refusal, never a traceback
        return False, f"refuse: MCP check raised {type(exc).__name__} (deploy half of the gate)"
    if not mcp_ok:
        return False, "refuse: production MCP endpoint not reachable (deploy half of the gate)"

    return True, "ok: proven (9/9, hashes match) and deployed (MCP round-trip)"


def _default_mcp_check() -> bool:
    """Real streamable-HTTP MCP round-trip against HELIXPAY_PROD_MCP_URL. Rejects stdio /
    non-HTTPS; logs host only on failure (never the full URL or any DSN)."""
    url = os.environ.get("HELIXPAY_PROD_MCP_URL")
    if not url or not url.startswith("https://"):
        print("refuse: HELIXPAY_PROD_MCP_URL unset or not https://", file=sys.stderr)
        return False
    host = urlsplit(url).hostname or "<host>"
    try:
        # Lazy import — keeps the refusal path free of the MCP client dependency.
        import anyio
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        async def _probe() -> bool:
            async with streamablehttp_client(url) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    return len(tools.tools) > 0

        return bool(anyio.run(_probe))
    except Exception as exc:  # noqa: BLE001 — never surface a DSN/credential-bearing message
        print(f"refuse: MCP round-trip to {host} failed ({type(exc).__name__})", file=sys.stderr)
        return False


def _default_record_runner() -> None:
    """Run the one governed full extraction. Imported lazily so a refused run never
    constructs the paid client (`replay`/`AnthropicClient`)."""
    from helixpay.ingest.replay import main as replay_main

    replay_main(["record", "./data", "--cache-dir", "./.replay-cache"])


def main(
    argv: Optional[list[str]] = None,
    *,
    record_runner: Optional[Callable[[], None]] = None,
    mcp_check: Optional[Callable[[], bool]] = None,
    uris: list[str] = SOURCE_URIS,
) -> int:
    parser = argparse.ArgumentParser(description="Governed full extraction (SP_015 gate).")
    parser.add_argument("--proof", default=str(DEFAULT_PROOF))
    parser.add_argument("--corpus-root", default=str(ROOT))
    args = parser.parse_args(argv)

    permit, reason = gate(
        Path(args.proof),
        Path(args.corpus_root),
        mcp_check or _default_mcp_check,
        uris,
    )
    print(reason, file=sys.stderr)
    if not permit:
        return 2  # refused — nothing paid imported or constructed.

    (record_runner or _default_record_runner)()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
