"""Deterministic coercion of raw LLM extraction items to the frozen contracts (SP_014).

Applied to each raw dict **before** strict Pydantic validation so that the model's
natural emissions are normalised rather than silently dropped.  Precision is preserved
by dropping-on-ambiguity — we never guess.

Coerce rules (CLAUDE.md / SP_014 design):

as_of (both claims and relations):
  - Already YYYY-MM-DD and a real date → unchanged (no coercion tag emitted).
  - Quarter pattern (Q1–Q4 + 4-digit year, any order) → quarter-END ISO date.
    Q1→-03-31, Q2→-06-30, Q3→-09-30, Q4→-12-31.
  - Bare 4-digit year → <year>-12-31.
  - Anything else non-empty → drop (unparseable_as_of).
  - Missing / None → leave absent (no drop, no coercion).

subject_type (claims only):
  - Case-insensitive.  Valid set: person | team | customer | product | metric | other.
  - company / organization / org / subsidiary / business / firm / corporation → other.
  - Anything else (file/repository/ticket/project/…) → FALL BACK to `other` (SP_025),
    preserving the original in `raw_subject_type`; the claim's value is not dropped.
  - None / absent → leave absent (no drop).

link_type (relations only):
  - manages / manage → reports_to, INVERT from_entity/to_entity.
    (record "link_verb" and "link_invert")
  - managed by / is managed by / reports to / report to /
    reports into / reports_to → reports_to, no invert.
  - leads / lead / functional lead → dotted_line_to, INVERT from/to (superiority phrasing,
    like "manages"); dotted line / dotted-line / dotted line to / dotted-line to /
    dotted_line_to → dotted_line_to, no invert (already subordinate→superior phrasing).
    NOTE: "leads" is *functional* in the HelixPay org (org-chart.md:123) so it is always
    dotted_line_to, NEVER reports_to. SP_014 Stage-5 review corrected the direction: a
    superiority verb must invert (from=subordinate→to=superior) or it plants a backwards edge.
  - member of / member_of / part of / part_of / belongs to → member_of.
  - owns / own / owner of → owns.
  - mentions / mention / references → mentions.
  - Any other NON-EMPTY verb (contributor/employed_by/…) → FALL BACK to `mentions` (SP_025),
    preserving the original in `raw_verb`; the relation is not dropped.
  - Empty/whitespace verb, or None → drop (unmappable_enum): nothing to preserve.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

# Quarter-to-month-end map
_QUARTER_MONTH_END = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}

# Patterns for quarter detection: "Q1 2026", "2026 Q1", "Q1 FY2026"
_QUARTER_RE = re.compile(
    r"(?:Q([1-4])\s+(?:FY)?(\d{4})|(?:FY)?(\d{4})\s+Q([1-4]))",
    re.IGNORECASE,
)
_BARE_YEAR_RE = re.compile(r"^\s*(\d{4})\s*$")

# Valid subject_type values (lower-cased)
_VALID_SUBJECT_TYPES = {"person", "team", "customer", "product", "metric", "other"}

# Synonym → "other" (company-like nouns)
_SUBJECT_TYPE_SYNONYMS: dict[str, str] = {
    "company": "other",
    "organization": "other",
    "organisation": "other",
    "org": "other",
    "subsidiary": "other",
    "business": "other",
    "firm": "other",
    "corporation": "other",
}

# Link verb → (canonical_link_type, invert_direction)
# Normalise the raw verb to lower-strip before lookup.
_LINK_VERB_MAP: dict[str, tuple[str, bool]] = {
    # manages / manage — INVERT
    "manages":          ("reports_to", True),
    "manage":           ("reports_to", True),
    # reports_to variants — no invert
    "managed by":       ("reports_to", False),
    "is managed by":    ("reports_to", False),
    "reports to":       ("reports_to", False),
    "report to":        ("reports_to", False),
    "reports into":     ("reports_to", False),
    "reports_to":       ("reports_to", False),
    # leads / dotted-line → dotted_line_to.  The Stage-3 resolution ("only manages inverts")
    # is preserved in spirit — "leads" is NEVER a reports_to — but Stage-5 review (SP_014)
    # corrected the *direction*: a superiority-phrasing verb ("A leads B" → A is the functional
    # superior) must invert just like "manages", or it plants a BACKWARDS dotted_line_to edge
    # (the convention is from=subordinate → to=superior). So the split mirrors manages/managed-by:
    #   - superiority phrasing (leads / lead / functional lead) → dotted_line_to, INVERT
    #   - subordinate phrasing (dotted line to / dotted_line_to / bare dotted line) → no invert
    "leads":             ("dotted_line_to", True),
    "lead":              ("dotted_line_to", True),
    "functional lead":   ("dotted_line_to", True),
    "dotted line":       ("dotted_line_to", False),
    "dotted-line":       ("dotted_line_to", False),
    "dotted line to":    ("dotted_line_to", False),
    "dotted-line to":    ("dotted_line_to", False),
    "dotted_line_to":    ("dotted_line_to", False),
    # member_of variants — no invert
    "member of":        ("member_of", False),
    "member_of":        ("member_of", False),
    "part of":          ("member_of", False),
    "part_of":          ("member_of", False),
    "belongs to":       ("member_of", False),
    # owns — no invert
    "owns":             ("owns", False),
    "own":              ("owns", False),
    "owner of":         ("owns", False),
    # mentions — no invert
    "mentions":         ("mentions", False),
    "mention":          ("mentions", False),
    "references":       ("mentions", False),
}

# The set of already-canonical link types (used to skip recording "link_verb" coercion)
_CANONICAL_LINK_TYPES = {"reports_to", "dotted_line_to", "owns", "member_of", "mentions"}


@dataclass(frozen=True)
class Coerced:
    """Result of a coerce_item call.

    item        The normalised raw dict ready for Pydantic validation, or None (drop).
    coercions   Tags for each transformation applied, e.g. ("as_of", "link_verb").
    drop_reason "unmappable_enum" | "unparseable_as_of", or None if item is not None.
    """

    item: Optional[dict]
    coercions: tuple[str, ...] = ()
    drop_reason: Optional[str] = None


def _coerce_as_of(raw_as_of: Optional[str]) -> tuple[Optional[str], bool, bool]:
    """Return (normalised_value_or_None_if_absent, coerced: bool, drop: bool).

    drop=True means the as_of is present but unparseable — drop the whole item.
    coerced=True means the value was transformed and should be recorded.
    """
    if raw_as_of is None:
        return None, False, False  # absent → fine

    value = raw_as_of.strip()
    if not value:
        return None, False, False  # empty string → treat as absent

    # 1. Quarter pattern
    m = _QUARTER_RE.search(value)
    if m:
        # Ambiguity guard (Stage-5 L1): more than one quarter token in one value
        # (e.g. "Q1 2026 Q2 2026") is ambiguous — drop rather than silently pick the first.
        if len(_QUARTER_RE.findall(value)) > 1:
            return None, False, True
        if m.group(1) and m.group(2):
            q, yr = int(m.group(1)), int(m.group(2))
        else:
            q, yr = int(m.group(4)), int(m.group(3))
        iso = f"{yr}-{_QUARTER_MONTH_END[q]}"
        return iso, True, False

    # 2. Bare 4-digit year
    m2 = _BARE_YEAR_RE.match(value)
    if m2:
        yr = int(m2.group(1))
        return f"{yr}-12-31", True, False

    # 3. Already ISO YYYY-MM-DD?
    try:
        date.fromisoformat(value)
        return value, False, False  # valid ISO — no coercion needed
    except ValueError:
        pass

    # 4. Anything else — unparseable
    return None, False, True


def coerce_item(raw: dict, kind: str) -> Coerced:
    """Normalise a raw extraction dict before strict schema validation.

    kind must be "claim" or "relation".
    Returns a Coerced with item=None on drop.
    """
    item = dict(raw)  # shallow copy; we mutate below
    coercions: list[str] = []

    # ------------------------------------------------------------------ #
    # as_of — applies to both kinds
    # ------------------------------------------------------------------ #
    raw_as_of = item.get("as_of")
    normalised, coerced, drop = _coerce_as_of(raw_as_of)
    if drop:
        return Coerced(item=None, drop_reason="unparseable_as_of")
    if coerced:
        item["as_of"] = normalised
        coercions.append("as_of")
    elif normalised is None and raw_as_of is not None:
        # Was an empty string, treat as absent
        item.pop("as_of", None)

    # ------------------------------------------------------------------ #
    # Kind-specific coercions
    # ------------------------------------------------------------------ #
    if kind == "claim":
        # subject_type
        raw_st = item.get("subject_type")
        if raw_st is not None:
            lower_st = raw_st.strip().lower()
            if lower_st in _VALID_SUBJECT_TYPES:
                if lower_st != raw_st:
                    # Case normalisation
                    item["subject_type"] = lower_st
                    coercions.append("subject_type")
                # else: already correct — no coercion tag
            elif lower_st in _SUBJECT_TYPE_SYNONYMS:
                item["subject_type"] = _SUBJECT_TYPE_SYNONYMS[lower_st]
                coercions.append("subject_type")
            else:
                # SP_025: an unknown subject_type (file/repository/ticket/project/event/…) is
                # NOT dropped — it falls back to the existing `other` catch-all so the claim's
                # value survives. The catch-all exists for exactly this; dropping here was
                # discarding real signal (hot-file ranks, commit counts, ticket details, …).
                # The ORIGINAL type is preserved in `raw_subject_type` so the pipeline can tell
                # this FALLBACK `other` apart from a genuine type-unknown `other` and refuse to
                # snap it onto a same-name distinct entity (entity-collapse guard, SP_025 review).
                item["raw_subject_type"] = lower_st
                item["subject_type"] = "other"
                coercions.append("subject_type_fallback")

    elif kind == "relation":
        # link_type
        raw_verb = item.get("link_type")
        if raw_verb is None:
            return Coerced(item=None, coercions=tuple(coercions), drop_reason="unmappable_enum")
        lookup = raw_verb.strip().lower()
        if not lookup:
            # Empty/whitespace verb is a malformed emission, not an out-of-vocab relationship —
            # there is nothing to preserve, so drop it rather than mint a meaningless `mentions`
            # edge with raw_verb="" (SP_025 review).
            return Coerced(item=None, coercions=tuple(coercions), drop_reason="unmappable_enum")
        if lookup not in _LINK_VERB_MAP:
            # SP_025: an out-of-vocab verb (contributor/employed_by/manages_account/…) is NOT
            # dropped — it falls back to the generic `mentions` edge with the original verb
            # preserved as `raw_verb`, so the relation (and its semantics) survive for an agent
            # to read, instead of silently discarding ~half the extracted relational signal.
            item["link_type"] = "mentions"
            item["raw_verb"] = lookup
            coercions.append("link_fallback")
            return Coerced(item=item, coercions=tuple(coercions))
        canonical, invert = _LINK_VERB_MAP[lookup]
        if canonical != raw_verb:
            # Record link_verb coercion when the canonical type differs from the raw verb.
            # Skip if the raw verb was already the canonical string (e.g. "reports_to").
            if lookup not in _CANONICAL_LINK_TYPES or canonical != lookup:
                coercions.append("link_verb")
        item["link_type"] = canonical
        if invert:
            item["from_entity"], item["to_entity"] = item["to_entity"], item["from_entity"]
            coercions.append("link_invert")

    return Coerced(item=item, coercions=tuple(coercions))


__all__ = ["Coerced", "coerce_item"]
