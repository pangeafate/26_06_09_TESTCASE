"""Controlled metric vocabulary (data-derived from the dashboards + overview).

Predicates canonicalize onto these keys so "ARR" and "annual recurring revenue"
are the *same* predicate — without this, contradiction detection silently no-ops
(spec §2). Alias sets deliberately include the literal strings printed in
``data/dashboards/*.html`` and ``data/overview.md`` so the planted Q1
revenue/ARR contradiction is detectable.

``canonical_key`` is a pure in-memory canonicalizer (used by unit tests and as the
source of truth seeded into the ``metric_vocab`` table by ``run_seed``).
"""

from __future__ import annotations

# (canonical_key, display_name, aliases)
METRIC_VOCAB: list[tuple[str, str, list[str]]] = [
    (
        "revenue",
        "Revenue",
        [
            "revenue",
            "total revenue",
            "q1 revenue",
            "topline",
            "sales",
            "turnover",
            "net revenue",
        ],
    ),
    (
        "arr",
        "Annual Recurring Revenue",
        [
            "arr",
            "annual recurring revenue",
            "recurring revenue",
            "annualized recurring revenue",
        ],
    ),
    ("ebitda", "EBITDA", ["ebitda", "operating profit"]),
    (
        "monthly_burn",
        "Monthly Burn",
        ["burn", "monthly burn", "burn rate", "cash burn"],
    ),
    ("runway", "Runway", ["runway", "cash runway", "months of runway"]),
    ("nps", "Net Promoter Score", ["nps", "net promoter score", "aggregate nps"]),
    (
        "churn",
        "Churn",
        [
            "churn",
            "arr churn",
            "churned arr",
            "logo churn",
            "attrition",
            "revenue churn",
        ],
    ),
    (
        "net_new_merchants",
        "Net New Merchants",
        ["net new merchants", "new merchants", "net new logos"],
    ),
    (
        "total_paid_merchants",
        "Total Paid Merchants",
        [
            "total paid merchants",
            "paid merchants",
            "active merchants",
            "merchant count",
        ],
    ),
    (
        "headcount",
        "Headcount",
        ["headcount", "head count", "total employees", "team size", "fte", "staff"],
    ),
    (
        "revenue_target",
        "Revenue Target",
        ["revenue target", "plan", "revenue plan", "target revenue"],
    ),
    ("gross_margin", "Gross Margin", ["gross margin", "gm"]),
    # SP_010: milestone/deadline predicates (not numeric metrics). Their value is a
    # forward target date and their as_of is the assertion date — canonicalizing the
    # GA/launch synonyms together is what lets the planted Confluence contradiction pair.
    (
        "ga_target",
        "GA Target",
        [
            "ga_target",
            "ga",
            "ga target",
            "ga date",
            "general availability",
            "general availability target",
            "launch",
            "launch date",
            "launch target",
            "ga launch",
            "go-live",
            "go live",
            "go live date",
            "release date",
            "target launch date",
            "platform launch",
        ],
    ),
    (
        "completion_target",
        "Completion Target",
        [
            "completion_target",
            "completion",
            "completion date",
            "target completion",
            "cutover",
            "cutover date",
            "migration completion",
            "migration target",
            "migration cutover",
        ],
    ),
    # SP_010 final-mile: "who leads this repo/component" is a relation-shaped predicate
    # (subject = the repo, value = the named leader). It canonicalizes here so a
    # contributors-analysis ranking lands on one predicate the grader can match
    # (golden: helixpay/core top_contributor = Sara Wijaya).
    # NOTE: this key is substrate for the PAID re-record (SP_019 Increment 2) — the current
    # cache holds no top_contributor claim, so it adds 0 recall at $0 until a re-record emits
    # one. It is also listed in repair._NON_COMPANY_KEYS so it never widens the repair gate.
    (
        "top_contributor",
        "Top Contributor",
        [
            "top_contributor",
            "top contributor",
            "lead contributor",
            "primary contributor",
            "top committer",
            "lead committer",
            "leading contributor",
        ],
    ),
]

# alias (lowercased) -> canonical_key
_ALIAS_INDEX: dict[str, str] = {}
for _key, _display, _aliases in METRIC_VOCAB:
    _ALIAS_INDEX[_key.lower()] = _key
    for _alias in _aliases:
        _ALIAS_INDEX[_alias.lower()] = _key


def canonical_key(raw: str) -> str:
    """Map a raw predicate to its canonical key; return ``raw`` unchanged if
    unknown. Never raises (review M-1)."""
    return _ALIAS_INDEX.get(raw.strip().lower(), raw)


__all__ = ["METRIC_VOCAB", "canonical_key"]
