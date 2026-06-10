"""Entity resolution — roster-first, ambiguity-safe (CLAUDE.md §7).

Mentions resolve against the **seeded roster** via ``Repository.resolve_entity`` (which
matches seeded entities first and returns ``None`` for an ambiguous bare name with no
resolving context — never a silent pick). This module adds the ingest-side wrapper:

* **Normalization variants** — Unicode NFKD accent folding + honorific stripping +
  whitespace collapse, tried in addition to the raw mention, so an accented mention can
  still match a folded roster entry (and vice-versa) without forking the repo's matcher.
* **Disambiguation context** — built from the document's ``source_uri`` using keys that
  actually exist as seeded ``attributes`` (``department`` primarily; the two Marias share a
  location, so only department separates them). Path tokens like ``customer_success`` are
  normalized to the seeded form ``"Customer Success"`` because the repo's context filter is
  a naive substring match that cannot bridge the underscore.
* **Safe creation** — a mention that doesn't resolve creates a new ``seeded=False`` entity
  **only** for open-class types (default ``{customer}``). A person/team that doesn't resolve
  is dropped + logged, so the two Marias never gain a silent third "Maria".
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Optional

from helixpay.contracts import Entity, Repository

log = logging.getLogger("helixpay.ingest.resolve")

# Open-class types we are willing to mint new entities for. **person** and **team** are
# governed by the seeded roster, so an unresolved mention of those is dropped, not created
# (this is the two-Marias / two-Tans guard). customer/metric/product/other are open-class:
# customers come from emails, metric subjects and the parent company ("HelixPay") aren't all
# seeded, so minting them is correct rather than dropping the fact.
DEFAULT_CREATABLE_TYPES = frozenset({"customer", "metric", "product", "other"})

_HONORIFICS = {"mr", "mrs", "ms", "miss", "dr", "prof", "sir", "madam"}

# source_uri path token -> seeded department/attribute value (exact seeded strings so the
# repo's substring context filter matches). Derived from the data/ directory layout.
_PATH_DEPARTMENT = {
    "customer_success": "Customer Success",
    "cs": "Customer Success",
    "engineering": "Engineering",
    "eng": "Engineering",
    "sales": "Sales",
    "leadership": "Executive",
    "finance": "Finance",
    "marketing": "Marketing",
    "people": "People",
    "it": "IT",
    "product__pos_self_service": "Product",
    "product": "Product",
}


def fold_name(name: str) -> str:
    """Accent-fold, strip honorifics, collapse whitespace; preserve word case.

    ``"Dr. João  Pereira"`` -> ``"Joao Pereira"``.
    """
    decomposed = unicodedata.normalize("NFKD", name)
    no_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    tokens = re.split(r"\s+", no_accents.strip())
    kept = [t for t in tokens if t.strip(".").lower() not in _HONORIFICS]
    return " ".join(kept).strip()


def context_from_source_uri(source_uri: str, author: Optional[str] = None) -> dict:
    """Derive a disambiguation context from a document path. Only keys that exist as seeded
    entity attributes are emitted (``department``); unknown path tokens yield ``{}`` so the
    repo's filter is never fed a key that can only mislead."""
    ctx: dict = {}
    for raw in re.split(r"[/\\]", source_uri.lower()):
        token = raw.strip()
        if token in _PATH_DEPARTMENT:
            ctx["department"] = _PATH_DEPARTMENT[token]
            break
    return ctx


def resolve_mention(
    repo: Repository,
    name: str,
    *,
    entity_type: Optional[str] = None,
    context: Optional[dict] = None,
    allow_create_types: frozenset[str] = DEFAULT_CREATABLE_TYPES,
) -> Optional[int]:
    """Resolve a mention to an entity id (roster-first). Returns ``None`` when the mention
    is ambiguous-without-context or unresolved-and-not-creatable — never a silent pick."""
    name = name.strip()
    if not name:
        return None

    folded = fold_name(name)
    variants = _dedup([name, folded])
    for variant in variants:
        ent = repo.resolve_entity(variant, entity_type, context)
        if ent is not None and ent.id is not None:
            return ent.id

    if not folded:
        # an honorific-only / punctuation-only mention ("Dr.") is not a real entity
        return None

    if entity_type in allow_create_types:
        # Layer 2 (SP_019): seeded-roster snap BEFORE minting. A typed resolve missing does NOT
        # mean the mention is new — a company/entity name mis-typed (e.g. "HelixPay" tagged
        # ``metric``) misses the type filter and would mint a duplicate. Try a TYPE-AGNOSTIC
        # resolve and snap to an existing **seeded** roster row instead. Snap only to a seeded
        # entity (never another minted row) and only when the resolve is unambiguous —
        # ``resolve_entity`` returns ``None`` for the two-Marias / two-Tans bare-name trap, so
        # the snap can never bridge two distinct seeded entities. Running it only on the mint
        # path (not for a non-creatable person/team miss, which is dropped) avoids a second DB
        # round-trip and any cross-type bridge. (iText2KG / ReLiK pattern.)
        # Invariant assumed: no two seeded entities share a canonical name across types.
        for variant in variants:
            ent = repo.resolve_entity(variant, None, context)
            if ent is not None and ent.id is not None and ent.seeded:
                return ent.id
        new_id = repo.upsert_entity(Entity(canonical_name=name, entity_type=entity_type, seeded=False))
        log.info("created new entity", extra={"name": name, "entity_type": entity_type, "created": True})
        return new_id

    log.info(
        "unresolved mention dropped (not creating)",
        extra={"name": name, "entity_type": entity_type, "had_context": bool(context)},
    )
    return None


def _dedup(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it and it not in seen:
            seen.add(it)
            out.append(it)
    return out


__all__ = ["resolve_mention", "context_from_source_uri", "fold_name", "DEFAULT_CREATABLE_TYPES"]
