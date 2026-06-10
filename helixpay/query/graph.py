"""Graph / structured reads — org chart and entity detail.

Thin reasoning over the ``Repository``'s recursive-CTE org subtree and claim/link
reads. ``org_chart`` enriches each node's ``role`` opportunistically by resolving
the node's canonical name (review arch-H2 — roles live in ``entity.attributes``
and are reachable through ``resolve_entity`` without a new Protocol method).

Contract friction (flagged, not forked): ``EntityDetail.aliases`` cannot be
populated through the frozen Protocol — there is no ``get_aliases(entity_id)`` and
raw SQL is confined to ``helixpay.db``. We return ``aliases: []`` and recommend
adding the read. ``get_links`` also has no ``from_entity_id`` filter, so entity
links are filtered in Python (fine at this scale; a filter is the perf upgrade).
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Optional

from helixpay.contracts import EntityDetail, OrgNode

if TYPE_CHECKING:
    from helixpay.contracts import Repository


def _enrich_roles(repo: "Repository", node: OrgNode) -> None:
    name = node.get("name")
    if name:
        ent = repo.resolve_entity(name, entity_type="person")
        if ent is not None:
            role = ent.attributes.get("role")
            if role:
                node["role"] = role
    for child in node.get("children", []):
        _enrich_roles(repo, child)


def org_chart(repo: "Repository", as_of: Optional[date] = None) -> OrgNode:
    """The reporting hierarchy (freshest if ``as_of`` omitted), roles enriched."""
    tree = repo.get_org_subtree(root_id=None, as_of=as_of)
    _enrich_roles(repo, tree)
    return tree


def entity_detail(repo: "Repository", name: str) -> EntityDetail:
    """Entity + its claims + its links. ``aliases`` is ``[]`` (Protocol friction)."""
    ent = repo.resolve_entity(name)
    if ent is None or ent.id is None:
        return EntityDetail(entity={}, aliases=[], claims=[], links=[])
    claims = repo.get_claims(ent.id)
    links = [
        link
        for link in repo.get_links()
        if link.from_entity_id == ent.id or link.to_entity_id == ent.id
    ]
    return EntityDetail(
        entity=ent.model_dump(),
        aliases=[],
        claims=[c.model_dump() for c in claims],
        links=[link.model_dump() for link in links],
    )


__all__ = ["org_chart", "entity_detail"]
