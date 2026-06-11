"""Extraction-quality audit (read-only).

Judges what actually landed in the DB after an ingest/replay — the complement to the
golden eval (``eval/run.py``):

* the golden set certifies **recall** (did we capture the facts that exist);
* this audit measures the properties sampling-by-eye can't —  **grounding**
  (evidence supports the value), **provenance integrity** (claim → chunk → document),
  **resolution honesty** (subject resolved or honestly NULL), **predicate
  canonicalization** — plus the planted known-answer **traps** (the Confluence GA
  contradiction must surface; revenue must NOT; the two Marias stay distinct).

Read-only by construction (``helixpay.db.audit_queries`` opens the session read-only),
so an audit can never mutate the corpus it inspects.
"""

from __future__ import annotations

from helixpay.audit.models import (
    AuditReport,
    ClaimRecord,
    Severity,
    TrapResult,
    Violation,
)
from helixpay.audit.run import run_audit

__all__ = [
    "AuditReport",
    "ClaimRecord",
    "Severity",
    "TrapResult",
    "Violation",
    "run_audit",
]
