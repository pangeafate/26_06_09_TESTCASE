"""Roster parsing — pure-function tests on inline fixtures, plus a `smoke` test
over the real data/ file. The unit tests own the parse logic; the smoke test
guards the actual seed source."""

from __future__ import annotations

from pathlib import Path

import pytest

from helixpay.seed.roster import parse_org_chart, parse_overview

INLINE = """\
# org chart

## Executive

| Name        | Role            | Location  | Reports to |
|-------------|-----------------|-----------|------------|
| Ann Lead    | CEO             | SG        | Board      |
| Bob Two     | COO             | SG        | Ann Lead   |

## Engineering (under Bob Two, COO)

- **Cara Dev** — VP Engineering — SG
  - **Dan Eng** — Backend Lead — SG
    - 7 engineers

## Sales (under Bob Two, COO)

### SEA — under Eve Sea (Sales Manager)

| Name      | Role         | Location |
|-----------|--------------|----------|
| Eve Sea   | Sales Mgr    | SG       |
| Finn Rep  | AE           | SG       |

---

- Functional leads dotted-line (e.g., Eve Sea ↔ Cara Dev)
"""


def _rt(parse):
    return {child: mgr for child, mgr in parse.reports_to}


def test_inline_exec_board_is_external_not_a_link():
    p = parse_org_chart(INLINE)
    assert "Ann Lead" in p.people
    assert p.people["Ann Lead"].attributes.get("reports_to_external") == "Board"
    assert _rt(p).get("Ann Lead") is None  # no link to "Board"
    assert _rt(p).get("Bob Two") == "Ann Lead"


def test_inline_nested_bullets_use_indentation():
    p = parse_org_chart(INLINE)
    rt = _rt(p)
    assert rt["Cara Dev"] == "Bob Two"  # top bullet -> section manager
    assert rt["Dan Eng"] == "Cara Dev"  # nested -> bullet parent
    assert "7 engineers" not in p.people  # count bullets are not people


def test_inline_subsection_manager_and_members():
    p = parse_org_chart(INLINE)
    rt = _rt(p)
    assert rt["Eve Sea"] == "Bob Two"  # sub-manager -> section manager
    assert rt["Finn Rep"] == "Eve Sea"  # table member -> sub-manager


def test_inline_dotted_line_pair():
    p = parse_org_chart(INLINE)
    assert ("Eve Sea", "Cara Dev") in p.dotted


def test_overview_products_distinct_and_aliased():
    ov = parse_overview("")
    assert "HelixPay POS" in ov.entities
    assert "HelixPay POS Self-Service" in ov.entities  # distinct from POS
    alias_map = {(c, a) for c, a in ov.aliases}
    assert ("HelixPay Brasil", "HPB") in alias_map
    assert ("HelixPay Brasil", "Helix Brasil") in alias_map
    assert ("HelixPay POS Self-Service", "POS SS") in alias_map


def test_overview_seeds_helixpay_parent_distinct_from_brasil():
    # SP_010: the parent company is a SEPARATE entity from the subsidiary — never an
    # alias of it — so 14.2M company revenue and 4.8M Brasil revenue never collide.
    ov = parse_overview("")
    assert "HelixPay" in ov.entities and "HelixPay Brasil" in ov.entities
    assert ov.entities["HelixPay"].entity_type == "other"
    alias_map = {(c, a) for c, a in ov.aliases}
    assert ("HelixPay Brasil", "HelixPay") not in alias_map
    assert ("HelixPay", "HelixPay Brasil") not in alias_map


def test_overview_seeds_project_entities_for_target_facts():
    # SP_010: ga_target / completion_target facts have no roster subject without these.
    ov = parse_overview("")
    assert "Project Confluence" in ov.entities and "CRM migration" in ov.entities
    assert ov.entities["Project Confluence"].entity_type == "other"
    assert ov.entities["CRM migration"].entity_type == "other"
    alias_map = {(c, a) for c, a in ov.aliases}
    assert ("Project Confluence", "Confluence") in alias_map


def test_overview_does_not_seed_named_merchant_accounts():
    # SP_020: named merchant accounts are NOT seeded — the dual-type-mint duplicate they used to
    # cause is now prevented at mint time in resolve.resolve_mention. Açaí Express SP must NOT be
    # in the seeded roster (the hardcode is removed).
    ov = parse_overview("")
    assert "Açaí Express SP" not in ov.entities
    assert all("Açaí" not in c for c in ov.entities)


# --------------------------------------------------------------------------- #
# smoke over the real data/ file (excluded from the fast unit suite)
# --------------------------------------------------------------------------- #
DATA = Path(__file__).resolve().parents[2].parent / "data"


@pytest.mark.smoke
def test_real_org_chart_name_traps_and_chain():
    p = parse_org_chart((DATA / "org-chart.md").read_text(encoding="utf-8"))
    rt = _rt(p)
    # name traps resolve to distinct entities with distinct managers
    assert "Maria Santos" in p.people and "Maria Silva" in p.people
    assert rt["Maria Santos"] == "Marco Bianchi"
    assert rt["Maria Silva"] == "Sofia Almeida"
    assert "Daniel Tan" in p.people and "Tan Wei Ming" in p.people
    # reporting chain
    assert rt["Sara Wijaya"] == "Daniel Tan"
    assert rt["Daniel Tan"] == "Arjun Kapoor"
    assert rt["Arjun Kapoor"] == "Wei Chen"
    assert p.people["Wei Chen"].attributes.get("reports_to_external") == "Board"
    assert 40 <= len(p.people) <= 60
