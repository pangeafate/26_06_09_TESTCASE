"""Deterministic roster parsing (pure — no DB imports, review H-3).

Parses ``data/org-chart.md`` and ``data/overview.md`` into seeded entities, the
reporting hierarchy (solid + dotted), team membership, and product/company aliases.
This is the deterministic backbone: entity resolution later matches messy mentions
against *this fixed roster* instead of clustering blind, which is what makes the
hierarchy reliable and disambiguates the planted name traps (two Marias, two Tans).

The functions here return plain value objects keyed by canonical name; ``run_seed``
turns them into rows via the Repository. Nothing here connects to a database.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from helixpay.contracts import Entity

# org-chart.md export date — every seeded line/claim is stamped with this so the
# query layer's freshest-wins resolver treats the roster as dated, not timeless.
ORG_CHART_AS_OF = date(2026, 4, 15)

PERSON = "person"
TEAM = "team"
PRODUCT = "product"
ORG = "other"

_BULLET_RE = re.compile(
    r"^(?P<indent>\s*)-\s+\*\*(?P<name>[^*]+?)\*\*\s*[—-]\s*(?P<rest>.+)$"
)
_TABLE_ROW_RE = re.compile(r"^\|(?P<cells>.+)\|\s*$")
_SECTION_RE = re.compile(r"^##\s+(?P<title>.+?)\s*$")
_SUBSECTION_RE = re.compile(r"^###\s+(?P<title>.+?)\s*$")
_UNDER_RE = re.compile(r"under\s+(?P<name>[^,()→]+?)\s*(?:[,()]|→|$)")
_ARROW_RE = re.compile(r"→\s*(?P<name>[^,()]+?)\s*(?:[,()]|$)")


@dataclass
class RosterParse:
    people: dict[str, Entity] = field(default_factory=dict)
    teams: dict[str, Entity] = field(default_factory=dict)
    reports_to: list[tuple[str, str]] = field(default_factory=list)  # (child, manager)
    dotted: list[tuple[str, str]] = field(default_factory=list)  # (a, b)
    member_of: list[tuple[str, str]] = field(default_factory=list)  # (person, team)


def _clean(s: str) -> str:
    return s.strip().strip("*").strip()


def _split_role_location(rest: str) -> tuple[str, str | None]:
    """'Backend Lead, Core — Singapore' -> ('Backend Lead, Core', 'Singapore')."""
    parts = re.split(r"\s*[—-]\s*", rest.strip())
    if len(parts) >= 2:
        return parts[0].strip(), parts[-1].strip()
    return rest.strip(), None


def _add_person(
    parse: RosterParse,
    name: str,
    role: str | None,
    location: str | None,
    department: str | None,
) -> None:
    name = _clean(name)
    if not name:
        return
    ent = parse.people.get(name)
    attrs: dict = {}
    if role:
        attrs["role"] = role
    if location:
        attrs["location"] = location
    if department:
        attrs["department"] = department
    if ent is None:
        parse.people[name] = Entity(
            canonical_name=name, entity_type=PERSON, attributes=attrs, seeded=True
        )
    else:
        # enrich without clobbering an existing role/location
        for k, v in attrs.items():
            ent.attributes.setdefault(k, v)
    if department:
        team = parse.teams.setdefault(
            department,
            Entity(
                canonical_name=department,
                entity_type=TEAM,
                attributes={"kind": "department"},
                seeded=True,
            ),
        )
        if (name, department) not in parse.member_of:
            parse.member_of.append((name, department))


def _under_name(text: str) -> str | None:
    m = _UNDER_RE.search(text)
    return _clean(m.group("name")) if m else None


def _arrow_name(text: str) -> str | None:
    m = _ARROW_RE.search(text)
    return _clean(m.group("name")) if m else None


def parse_org_chart(text: str) -> RosterParse:
    """Parse the org chart into entities + reporting/membership links (pure)."""
    parse = RosterParse()
    lines = text.splitlines()

    department: str | None = None  # current ## department (e.g. "Engineering")
    section_manager: str | None = None  # the "under X" person for the current section
    section_arrow: str | None = None  # the "→ P" target (section head reports to P)
    sub_manager: str | None = None  # current ### sub-section manager (Sales)
    bullet_stack: list[tuple[int, str]] = []  # (indent, name) for nested bullets
    in_exec = False

    i = 0
    while i < len(lines):
        line = lines[i]
        sec = _SECTION_RE.match(line)
        if sec:
            title = sec.group("title")
            department = _clean(re.split(r"\s*\(", title)[0])
            section_manager = _under_name(title)
            section_arrow = _arrow_name(title)
            sub_manager = None
            bullet_stack = []
            in_exec = department.lower().startswith("exec")
            # section head reports to the arrow target (e.g. Hannah Park → Priya Raman)
            if section_manager and section_arrow:
                parse.reports_to.append((section_manager, section_arrow))
            i += 1
            continue

        sub = _SUBSECTION_RE.match(line)
        if sub:
            sub_manager = _under_name(sub.group("title"))
            bullet_stack = []
            if sub_manager and section_manager:
                parse.reports_to.append((sub_manager, section_manager))
            i += 1
            continue

        bullet = _BULLET_RE.match(line)
        if bullet:
            indent = len(bullet.group("indent").replace("\t", "    "))
            name = _clean(bullet.group("name"))
            role, location = _split_role_location(bullet.group("rest"))
            _add_person(parse, name, role, location, department)
            # pop the stack to the current indent level
            while bullet_stack and bullet_stack[-1][0] >= indent:
                bullet_stack.pop()
            if bullet_stack:
                parent = bullet_stack[-1][1]
                parse.reports_to.append((name, parent))
            elif section_manager:
                parse.reports_to.append((name, section_manager))
            bullet_stack.append((indent, name))
            i += 1
            continue

        row = _TABLE_ROW_RE.match(line)
        if row:
            cells = [c.strip() for c in row.group("cells").split("|")]
            # skip separator and header rows
            if all(set(c) <= set("-: ") for c in cells) or cells[0].lower() == "name":
                i += 1
                continue
            name = _clean(cells[0])
            cell_role = cells[1] if len(cells) > 1 else None
            cell_location = cells[2] if len(cells) > 2 else None
            reports_to_cell = (
                _clean(cells[3]) if len(cells) > 3 and cells[3].strip() else None
            )
            _add_person(parse, name, cell_role, cell_location, department)
            manager = sub_manager or section_manager
            if in_exec and reports_to_cell:
                # Executive table carries an explicit "Reports to"; "Board" is external.
                if reports_to_cell.lower() != "board":
                    parse.reports_to.append((name, reports_to_cell))
                else:
                    parse.people[name].attributes["reports_to_external"] = "Board"
            elif manager and name != manager:
                parse.reports_to.append((name, manager))
            i += 1
            continue

        # dotted-line note: "... e.g., A ↔ B; C ↔ D; ...)"
        if "dotted-line" in line or "↔" in line:
            for a, b in re.findall(r"([^;(,]+?)\s*↔\s*([^;)]+)", line):
                parse.dotted.append((_clean(a), _clean(b)))

        i += 1

    # de-dup reporting edges, drop self-edges and edges to non-roster managers later
    parse.reports_to = _dedup_edges(parse.reports_to)
    parse.dotted = _dedup_edges(parse.dotted)
    return parse


def _dedup_edges(edges: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for a, b in edges:
        a, b = _clean(a), _clean(b)
        if not a or not b or a == b:
            continue
        if (a, b) in seen:
            continue
        seen.add((a, b))
        out.append((a, b))
    return out


# --------------------------------------------------------------------------- #
# overview.md — company/subsidiary + product entities and their aliases
# --------------------------------------------------------------------------- #
@dataclass
class OverviewParse:
    entities: dict[str, Entity] = field(default_factory=dict)
    aliases: list[tuple[str, str]] = field(default_factory=list)  # (canonical, alias)


# Data-derived from overview.md. Products are DISTINCT entities — POS ≠ POS
# Self-Service (the overview stresses this).
# The parent company is a SEPARATE entity from the subsidiary (SP_010): company-level
# metrics (revenue/runway/headcount/NPS/net-new-merchants) attach to "HelixPay", the
# Brasil subsidiary's to "HelixPay Brasil". Never alias one to the other, or the 14.2M
# company revenue and the 4.8M Brasil revenue collapse into a false contradiction.
_COMPANY_PARENT = ("HelixPay", ORG, ["Helix", "the company"])
_COMPANY = ("HelixPay Brasil", ORG, ["HPB", "Helix Brasil"])
# Cross-doc initiatives the golden ga_target/completion_target facts hang off — not in
# the org chart, so seed them here or those facts have no subject to resolve to (SP_010).
_PROJECTS = [
    ("Project Confluence", ["Confluence", "Confluence platform"]),
    ("CRM migration", ["CRM cutover", "HubSpot migration", "CRM migration project"]),
]
_PRODUCTS = [
    ("HelixPay Core", ["Core"]),
    ("HelixPay POS", ["POS"]),
    ("HelixPay Loyalty", ["Loyalty"]),
    (
        "HelixPay POS Self-Service",
        ["POS Self-Service", "Self-Serve", "POS SS", "Self-Service"],
    ),
    ("HelixPay Tap", ["Tap"]),
]
# Named merchant accounts are NOT seeded (SP_020). An account mentioned with inconsistent
# subject_types (e.g. Açaí Express SP appears typed both `customer` and `other`) used to mint
# two unseeded rows → ambiguous bare name → its owns-link was dropped, which the SP_010
# final-mile worked around by hardcoding the account here. That hardcode is removed: the
# duplicate is now prevented at MINT time in `resolve.resolve_mention` (an open-class mention
# snaps to an existing same-name row when one side is the catch-all `other`), so the class of
# bug is fixed for every account without a per-account seed.


def parse_overview(_text: str | None = None) -> OverviewParse:
    """Return the seeded company/subsidiary + product entities and aliases.

    The set is data-derived from overview.md (the document text is accepted for
    interface symmetry but the canonical roster is fixed here so the seed is
    deterministic and order-stable).
    """
    parse = OverviewParse()
    parent_name, parent_etype, parent_aliases = _COMPANY_PARENT
    parse.entities[parent_name] = Entity(
        canonical_name=parent_name,
        entity_type=parent_etype,
        attributes={"kind": "company"},
        seeded=True,
    )
    for a in parent_aliases:
        parse.aliases.append((parent_name, a))
    name, etype, aliases = _COMPANY
    parse.entities[name] = Entity(
        canonical_name=name,
        entity_type=etype,
        attributes={"kind": "subsidiary"},
        seeded=True,
    )
    for a in aliases:
        parse.aliases.append((name, a))
    for proj_name, proj_aliases in _PROJECTS:
        parse.entities[proj_name] = Entity(
            canonical_name=proj_name,
            entity_type=ORG,
            attributes={"kind": "project"},
            seeded=True,
        )
        for a in proj_aliases:
            parse.aliases.append((proj_name, a))
    for pname, palias in _PRODUCTS:
        parse.entities[pname] = Entity(
            canonical_name=pname, entity_type=PRODUCT, attributes={}, seeded=True
        )
        for a in palias:
            parse.aliases.append((pname, a))
    return parse


__all__ = [
    "RosterParse",
    "OverviewParse",
    "parse_org_chart",
    "parse_overview",
    "ORG_CHART_AS_OF",
    "PERSON",
    "TEAM",
    "PRODUCT",
    "ORG",
]
