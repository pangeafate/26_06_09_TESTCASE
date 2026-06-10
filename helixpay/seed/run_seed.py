"""Seed the deterministic backbone into Postgres (idempotent).

Run as a module:  python -m helixpay.seed.run_seed [--data-dir data] [--no-fixture]

Loads: metric_vocab → roster entities (people/teams) + product/company entities
and aliases → reporting hierarchy (reports_to / dotted_line_to) + team membership
→ the query fixture. Everything is written through the Repository; re-running is a
no-op on already-seeded rows.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

import psycopg

from helixpay.config import MissingEnvError
from helixpay.contracts import Link
from helixpay.db.repository import PostgresRepository
from helixpay.seed.fixtures import load_fixture
from helixpay.seed.metric_vocab import METRIC_VOCAB
from helixpay.seed.roster import ORG_CHART_AS_OF, parse_org_chart, parse_overview

log = logging.getLogger("helixpay.seed")


def seed_all(repo: PostgresRepository, data_dir: Path, with_fixture: bool = True) -> dict:
    """Seed everything; returns a small summary dict for logging/tests."""
    # 1) controlled metric vocabulary
    for key, display, aliases in METRIC_VOCAB:
        repo.upsert_metric(key, display, aliases)

    # 2) roster + overview entities
    roster = parse_org_chart((data_dir / "org-chart.md").read_text(encoding="utf-8"))
    overview = parse_overview((data_dir / "overview.md").read_text(encoding="utf-8"))

    name_to_id: dict[str, int] = {}
    for ent in (*roster.people.values(), *roster.teams.values(), *overview.entities.values()):
        name_to_id[ent.canonical_name] = repo.upsert_entity(ent)

    # 3) aliases (HPB/Helix Brasil, POS Self-Service synonyms, …)
    for canonical, alias in overview.aliases:
        if canonical in name_to_id:
            repo.add_alias(name_to_id[canonical], alias)

    # 4) reporting hierarchy (solid + dotted) and team membership.
    # SP_011: reporting edges are seeded **undated** (as_of=None) so the cited edge that
    # extraction produces from org-chart.md (stamped with the export date ORG_CHART_AS_OF)
    # does NOT collide with the seeded one on the links natural key (which keys on
    # COALESCE(as_of, …)). The seeded edge stays the deterministic org-tree backbone; the
    # extracted twin coexists and supplies the source_chunk_id (closing the no-provenance
    # hole) — corroborate, not replace. member_of keeps the export stamp (not corroborated
    # by extraction here).
    links = 0
    for child, manager in roster.reports_to:
        if child in name_to_id and manager in name_to_id:
            repo.add_link(Link(from_entity_id=name_to_id[child], to_entity_id=name_to_id[manager],
                               link_type="reports_to", as_of=None, confidence=1.0))
            links += 1
    for a, b in roster.dotted:
        if a in name_to_id and b in name_to_id:
            repo.add_link(Link(from_entity_id=name_to_id[a], to_entity_id=name_to_id[b],
                               link_type="dotted_line_to", as_of=None, confidence=0.8))
            links += 1
    for person, team in roster.member_of:
        if person in name_to_id and team in name_to_id:
            repo.add_link(Link(from_entity_id=name_to_id[person], to_entity_id=name_to_id[team],
                               link_type="member_of", as_of=ORG_CHART_AS_OF))
            links += 1

    summary: dict[str, object] = {
        "metrics": len(METRIC_VOCAB),
        "entities": len(name_to_id),
        "people": len(roster.people),
        "teams": len(roster.teams),
        "links": links,
    }
    if with_fixture:
        summary["fixture"] = load_fixture(repo)
    return summary


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Seed the HelixPay deterministic backbone.")
    parser.add_argument("--data-dir", default="data", help="directory holding org-chart.md / overview.md")
    parser.add_argument("--no-fixture", action="store_true", help="skip the query fixture rows")
    args = parser.parse_args(argv)

    try:
        repo = PostgresRepository.from_url()
    except (MissingEnvError, psycopg.Error) as exc:
        log.error("could not connect: %s", exc.__class__.__name__)
        return 1
    try:
        summary = seed_all(repo, Path(args.data_dir), with_fixture=not args.no_fixture)
    except FileNotFoundError as exc:
        log.error("seed source missing: %s", exc)
        return 2
    finally:
        repo.conn.close()
    log.info(
        "seeded: %(metrics)s metrics, %(entities)s entities (%(people)s people, %(teams)s teams), %(links)s links",
        summary,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
