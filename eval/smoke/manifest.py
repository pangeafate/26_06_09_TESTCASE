"""The one-document-per-type smoke manifest (SP_015) — the single source of truth.

Exactly one document per content archetype present in ``data/``. Each pick is
*golden-bearing* (has >=1 fact in ``test/golden/facts.yaml``) so the cheap golden+ledger
bar can actually score it. ``source_uri`` is the ``data/``-relative path **verbatim**, so it
matches the golden refs once the builder copies the doc under ``eval/smoke/data/``.

Intra-type-variance caveat (carried into the proof artifact): one doc proves the *type*,
not every *instance* — images (4 very different ones) and dashboards (3 layouts) have the
widest spread. The full run's loss ledger is the backstop that catches an unrepresented
instance loudly rather than silently.
"""

from __future__ import annotations

# (archetype, source_uri, why). One entry per type; no archetype or source_uri repeats.
MANIFEST: list[tuple[str, str, str]] = [
    ("overview", "data/overview.md",
     "company-level metrics; the baseline plain-markdown shape"),
    ("pdf", "data/board-deck-q1-2026.pdf",
     "revenue 14.2M, NPS 47, Confluence end-Q3 (contradiction side); the PDF path"),
    ("dashboard", "data/dashboards/april-2026-kpi-dashboard.html",
     "revenue + NPS with an explicit as-of date; dense HTML (Defect-A trigger)"),
    ("email", "data/email/customer-acai-express-thread.md",
     "Maria Santos owns Acai (ownership link; two-Marias side A)"),
    ("interview", "data/interviews/sales/maria-silva.md",
     "Maria Silva Brasil revenue 4.8M (two-Marias side B; name disambiguation)"),
    ("org_chart", "data/org-chart.md",
     "Daniel->Arjun->Wei, Sara->Daniel (link direction), headcount 274; dense"),
    ("code", "data/code/contributors-analysis-q1-2026.md",
     "Sara Wijaya top contributor; Daniel Tan vs Tan Wei Ming (two-Tans)"),
    ("chat", "data/chat/sales-floor-april.md",
     "golden-bearing chat log; informal multi-speaker shape"),
    ("image", "data/images/revenue-trend-q1-2026.jpeg",
     "vision-caption extraction; the image fidelity-loss path"),
]

ARCHETYPES: list[str] = [arch for arch, _uri, _why in MANIFEST]
SOURCE_URIS: list[str] = [uri for _arch, uri, _why in MANIFEST]
