"""Evidence-span grounding gate (faithfulness, spec §8 / research §2).

Grades whether a claim's value is restorable from the verbatim ``evidence`` span the model
cited, and whether that span is locatable in the source chunk. The design is deliberately
**narrowed** from the textbook "require a contiguous span for the whole triple" gate, which
false-drops the dashboard facts this project exists to surface: a dashboard prints the value
(``14.2M``), its label (``Q1 2026 Revenue``), and its as-of date in *separate* DOM nodes, so
no single span carries the whole triple. We therefore grade only:

* **value restorability** — the claimed ``object_value`` (numeric, via the same
  ``normalize_value`` the contradiction detector uses, or text fallback) appears in the span;
* **span locality** — the span is found in the chunk (whitespace/case-tolerant, with a
  token-overlap fallback for light paraphrase).

``as_of`` is **not** graded (it is document-level and sourced from ``doc.as_of`` downstream).
The grade is used to *flag and penalize confidence*, never to drop — dropping would cost the
recall the Eval agent measures.
"""

from __future__ import annotations

import math
import re

from helixpay.ingest.contradict import normalize_value
from helixpay.ingest.extract.schemas import ClaimOut

# Number candidates inside a span: optional sign (incl. unicode minus), digits/commas/dot,
# optional magnitude suffix, optional percent. The leading lookbehind stops a digit embedded
# in a token ("Q1", "version2.1") from being read as a standalone number — mirrors the
# whole-string discipline of contradict._PURE_NUM_RE.
_NUM_CANDIDATE = re.compile(r"(?<![A-Za-z\d])[−-]?\d[\d,]*\.?\d*\s*[kmb]?\s*%?", re.IGNORECASE)

_SPAN_OVERLAP_THRESHOLD = 0.6  # token-overlap floor for accepting a paraphrased span

GRADE_EXACT = "exact"
GRADE_VALUE_ONLY = "value_only"
GRADE_UNGROUNDED = "ungrounded"


def _norm_text(s: str) -> str:
    # casefold, fold the unicode minus, and collapse any run of non-alphanumerics to a
    # single space so "end-of-Q3" matches "end of Q3" (punctuation-insensitive). The numeric
    # path does not use this — it normalizes values via normalize_value separately.
    return re.sub(r"[^a-z0-9]+", " ", s.casefold().replace("−", "-")).strip()


def _span_in_chunk(evidence: str, chunk_text: str) -> bool:
    e, c = _norm_text(evidence), _norm_text(chunk_text)
    if e and e in c:
        return True
    tokens = set(e.split())
    if not tokens:
        return False
    overlap = len(tokens & set(c.split())) / len(tokens)
    return overlap >= _SPAN_OVERLAP_THRESHOLD


def _value_in_span(object_value: str, evidence: str) -> bool:
    _, claim_num = normalize_value(object_value)
    if claim_num is not None:
        for m in _NUM_CANDIDATE.finditer(evidence):
            _, cand_num = normalize_value(m.group())
            if cand_num is not None and math.isclose(claim_num, cand_num, rel_tol=1e-9, abs_tol=1e-9):
                return True
        return False
    # text fallback for non-numeric values (statuses, titles, org facts)
    ov = _norm_text(object_value)
    return bool(ov) and ov in _norm_text(evidence)


def grade(claim: ClaimOut, chunk_text: str) -> str:
    """Return ``"exact"`` (span + value grounded), ``"value_only"`` (value grounded, span
    paraphrased — still trustworthy), or ``"ungrounded"`` (no evidence, or the value is not
    restorable from it — a fabrication signal)."""
    if not claim.evidence or not claim.evidence.strip():
        return GRADE_UNGROUNDED
    value_ok = claim.object_value is None or _value_in_span(claim.object_value, claim.evidence)
    if not value_ok:
        return GRADE_UNGROUNDED
    return GRADE_EXACT if _span_in_chunk(claim.evidence, chunk_text) else GRADE_VALUE_ONLY


__all__ = ["grade", "GRADE_EXACT", "GRADE_VALUE_ONLY", "GRADE_UNGROUNDED"]
