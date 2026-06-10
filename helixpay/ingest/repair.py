"""Layer-0 attribution repair (SP_019): re-attribute an ownerless company metric from the
metric itself to the corpus's primary entity (the company).

A dashboard card like ``"Q1 2026 Revenue (SGD) 14.2M"`` is extracted with the metric as the
*subject* (``subject_type="metric"``) rather than as a property of the company — which makes
the value unfindable as "HelixPay's revenue". This pure transform moves the metric into the
predicate and points the subject at the document's primary entity: the OAK+MEND domain-range
rule (a metric predicate's domain is an entity, never the metric itself).

Conservative by construction. It fires ONLY for a ``subject_type == "metric"`` whose subject
is a *known company metric* (period-qualifier aware, so the dashboard surface form
``"Q1 2026 Revenue"`` is recognised, not just bare ``"Revenue"``) and is a strict no-op
otherwise — so a regional/unknown metric (``"HelixPay Brasil revenue"`` → unknown key) is
never merged into the company, keeping the planted Brasil-vs-company values on distinct
subjects. A company name mis-typed ``metric`` (``"HelixPay"``) is also left untouched; that is
the seeded-roster snap's job (``resolve.resolve_mention``), not this transform's.

This module imports ``helixpay.seed.metric_vocab`` READ-ONLY (the in-memory vocab is the seed
source of truth) and never edits it; ``_strip_period`` mirrors
``repository._strip_period_qualifier`` locally so SP_010's seed files are untouched.
"""

from __future__ import annotations

import re
from typing import Callable

from helixpay.contracts import EntityType
from helixpay.ingest.extract.schemas import ClaimOut
from helixpay.seed.metric_vocab import METRIC_VOCAB, canonical_key

# Predicates whose DOMAIN is a project/product/repo, NOT the company. They are excluded from
# the repair gate so a non-company attribute the LLM mis-typed ``metric`` (whose aliases are
# common words like "launch"/"cutover"/"completion"/"top contributor") is never re-attributed
# to the company — that belongs to entity resolution, not this transform.
#   * ga_target / completion_target  — a project/initiative milestone (Project Confluence GA)
#   * top_contributor                — a repo/component attribute (helixpay/core's Q1 lead)
# Keep this in lock-step with METRIC_VOCAB: any new key whose subject is not the company MUST
# be listed here, or KNOWN_KEYS widens silently and repair_metric_subject mis-fires (SP_010
# Increment-2 Stage-3 CRITICAL).
_NON_COMPANY_KEYS: frozenset[str] = frozenset(
    {"ga_target", "completion_target", "top_contributor"}
)

# Canonical COMPANY metric keys (e.g. ``revenue``, ``nps``, ``arr``, ``headcount``). The
# in-memory ``METRIC_VOCAB`` is the source of truth that ``run_seed`` loads into the
# ``metric_vocab`` table; the milestone keys above are filtered out for the repair gate.
KNOWN_KEYS: frozenset[str] = frozenset(
    k for k, _, _ in METRIC_VOCAB if k not in _NON_COMPANY_KEYS
)

# Leading reporting-period qualifier — ``"Q1 2026"``, ``"H2"``, ``"FY"``, a bare year. Mirrors
# ``repository._strip_period_qualifier``; applied before vocab lookup so a period-qualified
# metric label still canonicalizes.
_PERIOD_TOKEN_RE = re.compile(r"^(?:q[1-4]|h[12]|fy|20\d{2})\b[\s\-/]*", re.IGNORECASE)

# The company's EntityType value. ``model_copy`` does not re-run pydantic validators, so this
# must be a real EntityType member — asserted at import (fail-fast) AND by a unit test.
_COMPANY_TYPE = EntityType.other.value
assert _COMPANY_TYPE in {t.value for t in EntityType}, "company subject_type must be a real EntityType"


def _strip_period(s: str) -> str:
    """Iteratively strip leading reporting-period tokens (``"Q1 2026 Revenue"`` → ``"Revenue"``)."""
    out = s.strip()
    while True:
        nxt = _PERIOD_TOKEN_RE.sub("", out, count=1).strip()
        if nxt == out:
            return out
        out = nxt


def is_known_metric(s: str) -> bool:
    """True iff ``s`` — after stripping a leading reporting-period qualifier — canonicalizes to
    a known company-metric key. Never raises; an empty/blank string returns ``False``."""
    if not s or not s.strip():
        return False
    stripped = _strip_period(s)
    if not stripped:  # a pure period token ("2026", "FY") strips to empty — not a metric
        return False
    return canonical_key(stripped) in KNOWN_KEYS


def repair_metric_subject(
    claim_out: ClaimOut,
    *,
    primary_entity: str,
    known_metric: Callable[[str], bool] = is_known_metric,
) -> ClaimOut:
    """Re-attribute a known-company-metric-as-subject claim to ``primary_entity``.

    No-op (returns the input unchanged) unless ``subject_type == "metric"`` AND the subject is
    a known company metric. On a hit, the metric becomes the predicate — keeping an existing
    predicate that *already* names a metric (downstream ``canonical_predicate`` strips its
    period/units), else moving the subject metric into the predicate slot — and the subject is
    set to ``primary_entity`` typed as the company (``other``).
    """
    if claim_out.subject_type != "metric":
        return claim_out
    if not known_metric(claim_out.subject):
        return claim_out
    predicate = claim_out.predicate if known_metric(claim_out.predicate) else claim_out.subject
    return claim_out.model_copy(
        update={
            "subject": primary_entity,
            "subject_type": _COMPANY_TYPE,
            "predicate": predicate,
        }
    )


__all__ = ["repair_metric_subject", "is_known_metric", "KNOWN_KEYS"]
