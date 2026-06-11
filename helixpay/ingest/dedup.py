"""The value-pair dedup writer — shared substrate for the contradiction precision sweeps.

A thin ``Repository`` wrapper that intercepts ``add_contradiction`` to keep ONE row per distinct
value-pair (claims) or to-entity pair (links), collapsing the pairwise inflation a naive
``detect`` produces (e.g. 3 "June" × 2 "Q3" ga_target claims → 6 identical conflicts → 1 row).
Every other repo call proxies through unchanged, so ``detect``/``detect_link_conflicts`` behave
exactly as against the real repo and stay UNMODIFIED.

Lives in the ingest (shared-logic) layer so both the SP_028a deterministic sweep
(``scripts/recompute_contradictions.py``) and the SP_028b LLM-adjudication floor
(``helixpay/ingest/adjudicate.py``) import the SAME implementation — they cannot drift
(SP_028b Stage-5 finding). Tooling importing shared logic is the allowed dependency direction.
"""

from __future__ import annotations

from typing import Hashable

from helixpay.contracts import Contradiction


class DedupWriter:
    """Wraps ``repo``; keeps one contradiction per distinct value-pair.

    ``keymap`` maps a claim id OR link id to its dedup-key component (a claim's normalized value
    text, or a link's ``to_entity_id``). An id absent from ``keymap`` falls back to the id itself,
    so an unmapped pair is never silently merged."""

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


__all__ = ["DedupWriter"]
