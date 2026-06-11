"""Full contradiction recompute — the single-writer precision sweep (SP_028a; $0, no LLM).

The CANONICAL post-ingest contradiction step. ``contradict.detect`` is additive (it writes new
rows but never retracts a pair), so persisted rows drift after a comparator change. This sweep
re-derives the whole set from live claims/links under a clear-then-rewrite, single-writer model —
so the ``UNIQUE(claim_a_id, claim_b_id)`` table can never see two competing writers.

SP_028a adds two deterministic precision levers (no LLM, no API calls, idempotent):

  1. **cardinality skip** — a ``(subject, predicate)`` claim group whose predicate is explicitly
     ``set_valued`` (``predicate_cardinality``) is skipped: multiplicity is legitimate there
     (many pain points), so two values are not a disagreement. Applied to the CLAIM loop ONLY;
     the link loop keeps ``detect_link_conflicts``'s own ``_SINGLE_VALUED_LINK_TYPES`` gate.
  2. **value-pair dedup** — within a group, only ONE contradiction per distinct value-pair is
     kept (86 ``ga_target`` rows = one June-vs-Q3 story × many source combinations). The
     representative still cites two real claims with provenance, so the conflict + its sources
     survive; only redundant source-combinations are dropped. Implemented as a thin writer
     wrapper so ``detect`` / ``detect_link_conflicts`` are UNCHANGED.

Run after ingest, before snapshot + deploy. Inline ingest-time ``detect`` still writes raw rows;
this sweep is the source of truth.
"""

from __future__ import annotations

import argparse
import sys
from typing import Hashable, cast

from helixpay.contracts import Contradiction, Repository
from helixpay.db.repository import PostgresRepository
from helixpay.ingest.contradict import detect, detect_link_conflicts
from helixpay.ingest.normalize import normalize_value
from helixpay.ingest.predicate_cardinality import should_skip_predicate


class _DedupWriter:
    """Wraps a repo, intercepting ``add_contradiction`` to keep one row per distinct value-pair.

    ``keymap`` maps a claim id OR link id to its dedup-key component (a claim's normalized value
    text, or a link's ``to_entity_id``). Every other repo call proxies through unchanged, so
    ``detect``/``detect_link_conflicts`` behave exactly as against the real repo."""

    def __init__(self, repo: object, keymap: dict[int, Hashable]) -> None:
        self._repo = repo
        self._keymap = keymap
        self._seen: set[frozenset[Hashable]] = set()
        self.written = 0
        self.dropped = 0

    def __getattr__(self, name: str) -> object:  # proxy get_claims/get_links/get_contradictions/…
        return getattr(self._repo, name)

    def add_contradiction(self, c: Contradiction) -> None:
        if c.claim_a_id is not None and c.claim_b_id is not None:
            pair = (c.claim_a_id, c.claim_b_id)
        elif c.link_a_id is not None and c.link_b_id is not None:
            pair = (c.link_a_id, c.link_b_id)
        else:  # pragma: no cover - a contradiction always has one pair populated
            self._repo.add_contradiction(c)  # type: ignore[attr-defined]
            self.written += 1
            return
        key = frozenset({self._keymap.get(pair[0], pair[0]), self._keymap.get(pair[1], pair[1])})
        if key in self._seen:
            self.dropped += 1
            return  # redundant source-combination of an already-recorded conflict
        self._seen.add(key)
        self._repo.add_contradiction(c)  # type: ignore[attr-defined]
        self.written += 1


def recompute(repo: PostgresRepository) -> dict[str, int]:
    """Clear and re-derive every contradiction with the SP_028a precision levers. Idempotent."""
    before = len(repo.get_contradictions())
    cleared = repo.clear_contradictions()

    claim_groups = repo.distinct_claim_groups()
    written = skipped = 0
    for subject_id, predicate in claim_groups:
        if should_skip_predicate(predicate):
            skipped += 1
            continue  # set_valued — multiplicity is legitimate, not a conflict
        claims = repo.get_claims(subject_id, predicate)
        keymap: dict[int, Hashable] = {
            c.id: normalize_value(c.object_value)[0] for c in claims if c.id is not None
        }
        w = _DedupWriter(repo, keymap)
        detect(cast(Repository, w), subject_id, predicate)
        written += w.written

    link_groups = repo.distinct_link_groups()
    link_written = 0
    for from_entity_id, link_type in link_groups:
        links = repo.get_links(link_type, from_entity_id)
        tomap: dict[int, Hashable] = {ln.id: ln.to_entity_id for ln in links if ln.id is not None}
        w = _DedupWriter(repo, tomap)
        detect_link_conflicts(cast(Repository, w), from_entity_id, link_type)
        link_written += w.written

    after = len(repo.get_contradictions())
    return {
        "before": before,
        "cleared": cleared,
        "claim_groups": len(claim_groups),
        "skipped_set_valued": skipped,
        "link_groups": len(link_groups),
        "claim_contradictions": written,
        "link_contradictions": link_written,
        "after": after,
    }


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description="Recompute all contradictions (SP_028a sweep).").parse_args(argv)
    repo = PostgresRepository.from_url()
    stats = recompute(repo)
    for k, v in stats.items():
        print(f"{k:24} {v}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
