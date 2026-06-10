"""HelixPay CLI — ``helixpay ask "..."`` and ``helixpay ingest ./data``.

``ask`` is a thin adapter over the active ``QueryEngine`` (``helixpay.api.engine``): it
prints the answer, its as_of-stamped citations, and any surfaced contradiction. ``ingest``
delegates to Agent 2's ``helixpay.ingest.pipeline.run`` — imported **lazily** (only inside
the subcommand) so the rest of the CLI works before the ingest pipeline lands. Ingestion is
never reimplemented here.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from helixpay.api.engine import get_engine


def _print_answer(question: str) -> int:
    bundle = get_engine().ask(question)
    out = sys.stdout
    out.write(bundle.answer.rstrip() + "\n")

    if bundle.citations:
        out.write("\nCitations:\n")
        for c in bundle.citations:
            stamp = f" (as_of {c.as_of.isoformat()})" if c.as_of else " (as_of unknown)"
            snippet = f" — {c.snippet}" if c.snippet else ""
            out.write(f"  • {c.source_uri}{stamp}{snippet}\n")

    # Contradictions are surfaced, never hidden — print the section even when empty.
    if bundle.contradictions:
        out.write("\nContradictions:\n")
        for ct in bundle.contradictions:
            label = ct.predicate or "(unspecified predicate)"
            note = f" — {ct.note}" if ct.note else ""
            out.write(f"  ⚠ {label} [{ct.kind or 'conflict'}]{note}\n")
    else:
        out.write("\nContradictions: none surfaced.\n")

    # confidence is always a float (defaults to 0.0); print it unconditionally so a
    # genuine low/zero-confidence signal is never silently hidden.
    out.write(f"\nconfidence: {bundle.confidence:.2f}\n")
    return 0


def _run_ingest(path: str) -> int:
    # Lazy import via importlib: ingestion belongs to Agent 2. Resolving it dynamically
    # (rather than a static `from helixpay.ingest...`) keeps the CLI — and the type check —
    # decoupled from a module that does not exist until Agent 2 lands.
    import importlib

    try:
        pipeline = importlib.import_module("helixpay.ingest.pipeline")
    except ImportError as exc:  # pragma: no cover - exercised once the pipeline lands
        sys.stderr.write(
            "ingest pipeline is not available yet "
            f"(helixpay.ingest.pipeline.run): {exc}\n"
        )
        return 2
    try:
        result = pipeline.run(path)
    except Exception as exc:  # surface a structured error, not a raw traceback
        sys.stderr.write(f"ingest failed for {path!r}: {type(exc).__name__}: {exc}\n")
        return 1
    sys.stdout.write(f"ingest complete: {result}\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="helixpay", description="HelixPay ontology CLI.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ask = sub.add_parser("ask", help="Ask a grounded, cited question.")
    p_ask.add_argument("question", help="The question to ask.")

    p_ingest = sub.add_parser("ingest", help="Ingest a data directory into the ontology.")
    p_ingest.add_argument("path", help="Path to the data directory (e.g. ./data).")

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "ask":
        return _print_answer(args.question)
    if args.command == "ingest":
        return _run_ingest(args.path)
    return 1  # pragma: no cover - argparse enforces a valid subcommand


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
