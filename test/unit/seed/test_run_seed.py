"""Seed wiring (SP_011): reporting edges are emitted ``as_of=None`` so the cited
extracted org-chart edge no longer dedupes away against the seeded one.

The seed roster stays the deterministic org-tree backbone — it is *kept*, not removed —
but its ``reports_to``/``dotted_line_to`` edges drop the ``ORG_CHART_AS_OF`` stamp that
collided with extraction on the links natural key. ``member_of`` is unchanged.

Pure unit test: ``seed_all`` is driven against an in-memory fake repo over the real
``data/`` roster (no DB, no fixture).
"""

from __future__ import annotations

from pathlib import Path

from helixpay.contracts import Link
from helixpay.seed.roster import ORG_CHART_AS_OF
from helixpay.seed.run_seed import seed_all


class FakeSeedRepo:
    """Records entities + links; ignores metrics/aliases (not under test)."""

    def __init__(self) -> None:
        self.names: dict[str, int] = {}
        self.links: list[Link] = []
        self._next = 1

    def upsert_metric(self, *_args, **_kwargs) -> None:
        return None

    def upsert_entity(self, e) -> int:
        if e.canonical_name in self.names:
            return self.names[e.canonical_name]
        eid = self._next
        self._next += 1
        self.names[e.canonical_name] = eid
        return eid

    def add_alias(self, *_args, **_kwargs) -> None:
        return None

    def add_link(self, link: Link) -> None:
        self.links.append(link)


def _seed() -> FakeSeedRepo:
    repo = FakeSeedRepo()
    seed_all(repo, Path("data"), with_fixture=False)
    return repo


def test_reporting_edges_are_seeded_undated():
    repo = _seed()
    reports = [l for l in repo.links if l.link_type == "reports_to"]
    dotted = [l for l in repo.links if l.link_type == "dotted_line_to"]
    assert reports, "expected seeded reports_to edges"
    assert all(l.as_of is None for l in reports), "reports_to must be undated (no collision)"
    assert all(l.as_of is None for l in dotted), "dotted_line_to must be undated too"


def test_member_of_edges_stay_dated():
    # member_of is not a reporting edge and is not corroborated by extraction here, so it
    # keeps the org-chart export stamp (unchanged behavior).
    repo = _seed()
    member = [l for l in repo.links if l.link_type == "member_of"]
    assert member, "expected seeded member_of edges"
    assert all(l.as_of == ORG_CHART_AS_OF for l in member)


def test_golden_daniel_reports_to_arjun_still_seeded():
    # the deterministic backbone is retained — the golden hierarchy fact resolves.
    repo = _seed()
    daniel = repo.names.get("Daniel Tan")
    arjun = repo.names.get("Arjun Kapoor")
    assert daniel is not None and arjun is not None
    assert any(
        l.from_entity_id == daniel and l.to_entity_id == arjun and l.link_type == "reports_to"
        for l in repo.links
    )
