"""Full contradiction recompute over an existing ontology (SP_026 — $0, no LLM).

``contradict.detect`` is additive: it writes new contradiction rows but never retracts a
pair that no longer holds. So after a change to the shared value comparator
(``helixpay.ingest.normalize`` — e.g. the SP_026 annotation-parenthetical fix), the
persisted contradiction rows are stale: false positives that the new comparator no longer
flags remain in the table. This tool re-derives the whole set from the live claims/links:

  clear all contradictions → re-run ``detect`` over every (subject, predicate) group and
  ``detect_link_conflicts`` over every (from_entity, link_type) group.

It is pure-read of the corpus (no extraction, no embeddings, no API calls) and idempotent:
running it twice yields the same rows. Use it after a comparator change, before snapshot +
deploy, to ship corrected contradictions without paying for a re-extraction.
"""

from __future__ import annotations

import argparse
import sys

from helixpay.db.repository import PostgresRepository
from helixpay.ingest.contradict import detect, detect_link_conflicts


def recompute(repo: PostgresRepository) -> dict[str, int]:
    """Clear and re-derive every contradiction. Returns a small stats dict."""
    before = len(repo.get_contradictions())
    cleared = repo.clear_contradictions()

    claim_groups = repo.distinct_claim_groups()
    written = 0
    for subject_id, predicate in claim_groups:
        written += detect(repo, subject_id, predicate)

    link_groups = repo.distinct_link_groups()
    link_written = 0
    for from_entity_id, link_type in link_groups:
        link_written += detect_link_conflicts(repo, from_entity_id, link_type)

    after = len(repo.get_contradictions())
    return {
        "before": before,
        "cleared": cleared,
        "claim_groups": len(claim_groups),
        "link_groups": len(link_groups),
        "claim_contradictions": written,
        "link_contradictions": link_written,
        "after": after,
    }


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description="Recompute all contradictions (SP_026).").parse_args(argv)
    repo = PostgresRepository.from_url()
    stats = recompute(repo)
    for k, v in stats.items():
        print(f"{k:24} {v}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
