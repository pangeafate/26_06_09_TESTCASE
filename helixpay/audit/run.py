"""Orchestrate the extraction audit and the ``python -m helixpay.audit`` CLI.

Run AFTER a (replay or live) ingest:

    uv run python -m helixpay.audit                 # full text report
    uv run python -m helixpay.audit --strict        # exit 1 on any ERROR invariant or failed trap
    uv run python -m helixpay.audit --sample 40 --seed 7
    uv run python -m helixpay.audit --json           # machine-readable summary

Reads the DB only (no LLM keys); the session is opened read-only, so the audit can
never mutate the corpus. Requires ``DATABASE_URL`` (``helixpay.config.database_url``).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

from helixpay.audit.invariants import is_suspicious, run_invariants
from helixpay.audit.models import AuditReport, ClaimRecord
from helixpay.audit.report import format_report, report_to_dict
from helixpay.audit.sampling import stratified_sample
from helixpay.audit.traps import build_trap_context, run_traps

# LAYER EXCEPTION (SP_031 I6/D1 — accepted & documented, not a code change):
# the audit subsystem reaches `helixpay.db.audit_queries` directly, bypassing the frozen
# `Repository` Protocol. In-bounds ONLY under two invariants: (1) READ-ONLY (the session is
# opened read-only; the audit never mutates the corpus), and (2) CENSUS / INTROSPECTION, not
# domain serving (count(*), schema-column checks, raw fact rows the frozen Repository
# deliberately does not expose). Adding census reads to the frozen Protocol would fork it for
# a one-off consumer (propose-don't-fork). A future `audit_queries` call that mutates, or
# serves a domain read, is OUT of bounds — route it through `Repository` instead.
from helixpay.db import audit_queries


def run_audit(conn, *, sample_size: int = 25, seed: int = 1729) -> AuditReport:
    """Build the full report from an open (ideally read-only) connection."""
    evidence_present = audit_queries.has_evidence_columns(conn)
    counts = audit_queries.table_counts(conn)
    claim_rows = audit_queries.fetch_claim_rows(conn, evidence_present=evidence_present)
    records = [
        ClaimRecord.from_row(r, evidence_present=evidence_present) for r in claim_rows
    ]

    violations = run_invariants(records)
    sample = stratified_sample(
        records, k=sample_size, seed=seed, suspicious=is_suspicious
    )

    ctx = build_trap_context(
        claim_rows=claim_rows,
        contradiction_rows=audit_queries.fetch_contradiction_rows(conn),
        entity_rows=audit_queries.fetch_entity_rows(conn),
        vocab_rows=audit_queries.fetch_vocab_rows(conn),
    )
    traps = run_traps(ctx)

    return AuditReport(
        total_claims=len(records),
        counts=counts,
        violations=violations,
        sample=sample,
        traps=traps,
        evidence_columns_present=evidence_present,
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="helixpay.audit", description="Read-only extraction-quality audit."
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=25,
        help="claims to surface for manual review (default 25)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=1729,
        help="sampling seed (reproducible; default 1729)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 on any ERROR invariant or failed trap",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit a JSON summary instead of the text report",
    )
    args = parser.parse_args(argv)

    # Import here so --help works without DATABASE_URL set.
    from helixpay.config import database_url

    with audit_queries.read_only_connection(database_url()) as conn:
        report = run_audit(conn, sample_size=args.sample, seed=args.seed)

    if args.json:
        print(json.dumps(report_to_dict(report), indent=2, default=str))
    else:
        print(format_report(report))

    if args.strict and not report.clean():
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["run_audit", "main"]
