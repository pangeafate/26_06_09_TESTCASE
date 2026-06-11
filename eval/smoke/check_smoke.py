"""The per-document proving bar for the one-per-type smoke loop (SP_015).

Three signals per doc, combined into one verdict (PASS / INCOMPLETE / FAIL):

  * **correctness (golden):** every golden fact pinned to the doc is FOUND at 100%
    golden-precision — via ``eval.run.check_extraction`` (Level 1 ONLY; this module never
    touches the paid ``ask()`` / answer surface);
  * **completeness (ledger):** the doc's extraction lost nothing silently — no empty/truncated
    chunk; drops, if any, are flagged for human explanation. Read through a pluggable
    ``ledger_probe`` (SP_014's loss ledger). **Absent ledger => INCOMPLETE, never PASS.**
  * **embedding ($0):** the doc's persisted chunks carry a real (non-null, non-zero-norm)
    1024-dim vector — via a pluggable ``embedding_probe`` (a ``helixpay.db`` audit query, kept
    out of this layer so no raw SQL lives outside ``helixpay/db/``).

The DB-backed ``check()`` is exercised by the operator/db-gated proving run; the verdict
aggregation, the INCOMPLETE-never-PASS rule, and the corpus fingerprint are pure and unit
tested. ``check()`` emits a machine JSON result that ``scripts/full_run.py`` re-derives the
gate from (so the gate never trusts a human-typed flag).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable, Mapping, Optional

# Level-1 extraction grader ONLY. The answer-level graders (and eval.run.run(), which reach
# the paid Opus answer path) are deliberately NOT imported here — asserted by a unit test
# that greps this file for that surface.
from eval.run import check_extraction
from eval.smoke.manifest import SOURCE_URIS

# verdict severity: FAIL (worst) > INCOMPLETE > PASS (best).
_SEVERITY = {"PASS": 0, "INCOMPLETE": 1, "FAIL": 2}

LedgerProbe = Callable[[str], Optional[Mapping[str, int]]]
EmbeddingProbe = Callable[[str], Optional[bool]]


def _worst(a: str, b: str) -> str:
    return a if _SEVERITY[a] >= _SEVERITY[b] else b


def doc_verdict(
    source_uri: str,
    golden_found: int,
    golden_total: int,
    golden_precision: Optional[float],
    ledger_entry: Optional[Mapping[str, int]],
    embedding_ok: Optional[bool],
) -> dict:
    """Combine the three signals for one doc. Pure — no IO. FAIL dominates INCOMPLETE."""
    status = "PASS"
    reasons: list[str] = []

    # correctness
    if golden_total > 0 and golden_found < golden_total:
        status = _worst(status, "FAIL")
        reasons.append(f"golden {golden_found}/{golden_total} found")
    if golden_precision is not None and golden_precision < 1.0:
        status = _worst(status, "FAIL")
        reasons.append(f"golden precision {golden_precision:.2f} < 1.0")

    # completeness (absent ledger is a loud INCOMPLETE — never a silent pass)
    if ledger_entry is None:
        status = _worst(status, "INCOMPLETE")
        reasons.append("completeness unverified (no loss ledger; needs SP_014)")
    else:
        total_dropped = ledger_entry.get("items_dropped", 0)
        # SP_024: only LOSSY drops (schema/grounding losses) gate the proof. Intentional
        # non-assertions (hypothetical/ungrounded) are the faithfulness contract working and
        # must not block PASS — else items_dropped==0 is unreachable and every doc is
        # INCOMPLETE forever. A pre-SP_024 ledger has no "lossy_drops" key → fall back to the
        # total (conservative: an un-split ledger can't prove its drops were benign).
        lossy = ledger_entry.get("lossy_drops")
        if lossy is None:
            lossy = total_dropped
        benign = max(total_dropped - lossy, 0)
        if ledger_entry.get("empty_extractions", 0) > 0 or ledger_entry.get("truncated_calls", 0) > 0:
            status = _worst(status, "FAIL")
            reasons.append("silent loss: empty/truncated extraction")
        elif lossy > 0:
            status = _worst(status, "INCOMPLETE")
            reasons.append(f"{lossy} lossy item(s) dropped (schema/grounding) — needs human explanation")
        if benign > 0:
            # informational only — does NOT change the verdict (intentional non-assertion).
            reasons.append(f"{benign} intentional drop(s) (hypothetical/ungrounded) — expected, not blocking")

    # embedding ($0)
    if embedding_ok is False:
        status = _worst(status, "FAIL")
        reasons.append("persisted embedding missing or zero-norm")
    elif embedding_ok is None:
        status = _worst(status, "INCOMPLETE")
        reasons.append("embedding unverified (no probe)")

    return {
        "source_uri": source_uri,
        "verdict": status,
        "reasons": reasons,
        "golden": {"found": golden_found, "total": golden_total, "precision": golden_precision},
    }


def corpus_fingerprint(root: Path, uris: list[str]) -> dict[str, str]:
    """sha256 of each doc's bytes, keyed by source_uri. The gate recomputes this to reject a
    stale/edited proof. Reads file bytes only — no secrets touched."""
    root = Path(root)
    out: dict[str, str] = {}
    for uri in uris:
        out[uri] = hashlib.sha256((root / uri).read_bytes()).hexdigest()
    return out


def ledger_probe_from(ledger) -> LedgerProbe:
    """Adapt SP_014's loss ledger into the per-URI ``LedgerProbe`` ``check()`` expects.

    The seam between SP_014 and SP_015: ``LossLedger.probe()`` is zero-arg and returns the
    whole ``{uri: {empty_extractions, truncated_calls, items_dropped}}`` table; ``check()``
    calls ``ledger_probe(uri)`` per doc. This bridges the two. Accepts either a ``LossLedger``
    (anything exposing ``probe()``) or an already-materialised probe dict.

    A URI the ledger never recorded returns ``None`` — which ``doc_verdict`` treats as
    completeness-unverified (INCOMPLETE, never a silent PASS), exactly the desired behaviour
    for a doc that produced no extraction call at all.
    """
    table = ledger.probe() if hasattr(ledger, "probe") else dict(ledger)

    def _probe(uri: str) -> Optional[Mapping[str, int]]:
        return table.get(uri)

    return _probe


def embedding_probe_from(mapping: Mapping[str, bool]) -> EmbeddingProbe:
    """Adapt a precomputed ``{uri: has_real_embedding}`` map into an ``EmbeddingProbe``.

    The real operator probe is a ``helixpay.db`` audit query (no raw SQL leaks into this
    layer); this adapter is for wiring a materialised result (e.g. from that audit query) or
    a test fixture. An unseen URI returns ``None`` (embedding-unverified → INCOMPLETE)."""
    table = dict(mapping)

    def _probe(uri: str) -> Optional[bool]:
        return table.get(uri)

    return _probe


def check(
    repo,
    golden,
    *,
    source_root: Path,
    uris: list[str] = SOURCE_URIS,
    ledger_probe: Optional[LedgerProbe] = None,
    embedding_probe: Optional[EmbeddingProbe] = None,
) -> dict:
    """DB-backed proving run (operator/db-gated). Level-1 golden + pluggable ledger/embedding
    probes. Returns a machine result dict the gate re-derives from. Makes **no** paid call:
    only ``check_extraction`` (DB reads) plus the injected probes."""
    report = check_extraction(repo, golden)
    by_id = {f.id: f.source_uri for f in golden.facts}

    # group golden verdicts by the doc they belong to.
    per_doc: dict[str, dict[str, int]] = {u: {"found": 0, "attempted": 0, "total": 0} for u in uris}
    for v in report.verdicts:
        uri = by_id.get(v.fact_id)
        if uri not in per_doc:
            continue
        per_doc[uri]["total"] += 1
        if v.verdict.value == "FOUND":
            per_doc[uri]["found"] += 1
            per_doc[uri]["attempted"] += 1
        elif v.verdict.value == "MISMATCH":
            per_doc[uri]["attempted"] += 1

    docs: dict[str, dict] = {}
    for uri in uris:
        g = per_doc[uri]
        precision = (g["found"] / g["attempted"]) if g["attempted"] else None
        ledger_entry = ledger_probe(uri) if ledger_probe else None
        embedding_ok = embedding_probe(uri) if embedding_probe else None
        docs[uri] = doc_verdict(uri, g["found"], g["total"], precision, ledger_entry, embedding_ok)

    passed = sum(1 for d in docs.values() if d["verdict"] == "PASS")
    return {
        "sprint": "SP_015",
        "passed": passed,
        "total": len(uris),
        "all_green": passed == len(uris),
        "docs": docs,
        "fingerprint": corpus_fingerprint(source_root, uris),
    }


def write_result(result: dict, path: Path) -> None:
    """Persist the machine result (the gate's input). Contains verdicts + doc hashes only —
    never a DATABASE_URL, key, or connection string (CLAUDE.md §7)."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
