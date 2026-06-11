"""Blind scorer — how many human-found contradictions did the LIVE detector materialize?

The oracle (``test/golden/contradictions.yaml``) is a SCORING SET, never pipeline input. The
contradiction detector runs with zero knowledge of it. This module reads whatever contradiction
ROWS the detector wrote to a ``Repository`` and reports, per oracle item, whether a materialized
row independently satisfies it — it NEVER writes, and it is imported only by the eval harness /
tests, never by ``helixpay/`` (importing it from the pipeline would be the hardcoding this
measurement exists to guard against).

Matching is deliberately at the grain of "did the detector flag a conflict on this subject's
this attribute?":

  * When the subject RESOLVES to a roster entity, a row matches on
    ``subject_entity_id`` + canonical predicate (robust: it does not depend on the detector's
    exact value rendering, which the oracle paraphrases).
  * When the subject does NOT resolve (e.g. a minted bug ticket or a dual-type account), the
    match falls back to canonical predicate + BOTH oracle values being present in the row's
    evidence (the detector's ``note`` embeds both object_values) — value presence guards against
    a cross-subject false match when we cannot pin the subject.

A cross-predicate item (``predicate_b`` set, e.g. a solid AND dotted line to the same person)
matches if a row exists under either predicate — today none does, which is the honest miss.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict

from helixpay.contracts import Repository
from helixpay.ingest.normalize import normalize_value

_SEVERITIES = frozenset({"HIGH", "MEDIUM", "LOW"})

DEFAULT_ORACLE = (
    Path(__file__).resolve().parent.parent / "test" / "golden" / "contradictions.yaml"
)


class OracleContradiction(BaseModel):
    """One human-found conflict the detector is expected to materialize as a row."""

    model_config = ConfigDict(extra="forbid")

    id: str
    severity: str
    subject: str
    predicate: str
    predicate_b: Optional[str] = None
    value_a: str
    value_b: str
    source_a: str
    source_b: str
    expected: str = "surfaced"
    baseline_caught: bool = False
    root_cause: Optional[str] = None
    lever: Optional[str] = None
    note: Optional[str] = None

    @property
    def predicates(self) -> list[str]:
        return [self.predicate] + ([self.predicate_b] if self.predicate_b else [])


def load_oracle(path: Path | str = DEFAULT_ORACLE) -> list[OracleContradiction]:
    """Load and validate the contradiction oracle. A malformed entry fails loudly here."""
    data = yaml.safe_load(Path(path).read_text())
    return [OracleContradiction.model_validate(d) for d in data["contradictions"]]


@dataclass
class OracleVerdict:
    id: str
    severity: str
    caught: bool
    baseline_caught: bool
    detail: str = ""


@dataclass
class RecallReport:
    verdicts: list[OracleVerdict]

    @property
    def caught(self) -> int:
        return sum(1 for v in self.verdicts if v.caught)

    @property
    def total(self) -> int:
        return len(self.verdicts)

    @property
    def recall(self) -> float:
        return self.caught / self.total if self.total else 0.0

    @property
    def baseline(self) -> int:
        """Items known to be caught today — the ratchet floor the live score must not drop below."""
        return sum(1 for v in self.verdicts if v.baseline_caught)


# --------------------------------------------------------------------------- #
# Matching helpers                                                            #
# --------------------------------------------------------------------------- #
def _norm(s: str) -> str:
    text, _ = normalize_value(s)
    return text.casefold()


def _present(needle: str, haystack: str) -> bool:
    """Normalization-tolerant substring test (mirrors the eval matcher's text path)."""
    if needle.casefold() in haystack.casefold():
        return True
    n = _norm(needle)
    return bool(n) and n in _norm(haystack)


def _canon(repo: Repository, predicate: str) -> str:
    try:
        return repo.canonical_predicate(predicate)
    except Exception:  # noqa: BLE001 — canonical_predicate must never raise; be defensive anyway
        return predicate


def _evidence(row) -> str:
    """The detector's ``note`` embeds both object_values + as_of; fall back to predicate/kind."""
    return " ".join(p for p in (row.note, row.predicate, row.kind) if p)


def score(repo: Repository, oracle: list[OracleContradiction]) -> RecallReport:
    """Score the oracle against the contradiction rows the detector materialized in ``repo``."""
    verdicts: list[OracleVerdict] = []
    for item in oracle:
        want_preds = {_canon(repo, p) for p in item.predicates}
        subject = repo.resolve_entity(item.subject)
        subj_id = subject.id if subject is not None else None

        rows = [
            r
            for r in repo.get_contradictions(subj_id)
            if _canon(repo, r.predicate or "") in want_preds
        ]

        if subj_id is not None:
            # Subject pinned → a row on the right predicate is the conflict (value-agnostic,
            # so the paraphrased oracle value never causes a false miss).
            caught = bool(rows)
            detail = (
                f"row on {item.predicate!r} for entity {subj_id}"
                if caught
                else f"no materialized row on {item.predicate!r} for entity {subj_id}"
            )
        else:
            # Subject unresolved → require both values present to avoid a cross-subject match.
            caught = any(
                _present(item.value_a, _evidence(r)) and _present(item.value_b, _evidence(r))
                for r in rows
            )
            detail = (
                "matched on predicate + both values (subject unresolved)"
                if caught
                else "no materialized row carries both values (subject unresolved)"
            )

        verdicts.append(
            OracleVerdict(item.id, item.severity, caught, item.baseline_caught, detail)
        )
    return RecallReport(verdicts)


def format_report(report: RecallReport) -> str:
    """A human-readable scorecard for the CLI / test output."""
    lines = [
        f"Contradiction recall: {report.caught}/{report.total} "
        f"({report.recall:.0%})  [baseline floor {report.baseline}]",
        "",
    ]
    for v in sorted(report.verdicts, key=lambda x: (not x.caught, x.severity)):
        mark = "✓" if v.caught else "✗"
        base = " (baseline)" if v.baseline_caught else ""
        lines.append(f"  {mark} [{v.severity:<6}] {v.id}{base} — {v.detail}")
    return "\n".join(lines)


__all__ = [
    "OracleContradiction",
    "OracleVerdict",
    "RecallReport",
    "load_oracle",
    "score",
    "format_report",
    "DEFAULT_ORACLE",
]
