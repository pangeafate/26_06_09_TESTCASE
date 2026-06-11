"""Build the curated 'smoke' subset corpus + its ground truth (a fast testing sample).

WHY: the full corpus takes ~1h of paid extraction. This carves out a *curated* subset
that deliberately preserves every planted trap (the cross-document contradictions, the
two-Marias / two-Tans name traps, the org hierarchy, the honest-oracle revenue agreement)
so the subset eval still measures what matters — a random 10% would contain none of the
multi-document contradictions and be blind to the project's core behavior.

WHAT IT DOES (deterministic, no network, no DB):
  * copies each manifest doc into ``eval/sample/data/<same subpath>`` so connector globs
    and ``source_uri`` match the real corpus exactly (run with root=``data`` from this dir);
  * FILTERS the existing verified golden set (``test/golden/facts.yaml`` +
    ``eval/questions.yaml``) down to the subset — facts whose ``source_uri`` is in the
    manifest, contradictions whose sides survive (corroborating sources trimmed), and
    questions whose golden refs survive — into ``eval/sample/{facts,questions}.yaml``.

The subset ground truth is therefore a *traceable subset* of the human-authored oracle,
never re-labeled. Re-run this whenever the golden set grows (e.g. SP_013).

USAGE:  uv run python eval/sample/build_sample.py        # regenerate the sample
"""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

# Repo root is two levels up from eval/sample/.
ROOT = Path(__file__).resolve().parents[2]
GOLDEN_FACTS = ROOT / "test" / "golden" / "facts.yaml"
QUESTIONS = ROOT / "eval" / "questions.yaml"
SAMPLE_DIR = ROOT / "eval" / "sample"
SAMPLE_DATA = SAMPLE_DIR / "data"

# The curated subset: (source_uri, why it's in). Trap coverage drives the size — it lands
# at ~11 docs (~27%), not 10%, because the planted contradictions are multi-source BY
# DESIGN and need their document pairs present to be surfaced + attributed.
MANIFEST: list[tuple[str, str]] = [
    (
        "data/all-hands-2026-04-15.md",
        "Confluence GA = end-June (side A); NPS-62 framing; CEO priorities",
    ),
    (
        "data/board-deck-q1-2026.pdf",
        "Confluence GA = end-Q3 (side B); revenue 14.2M; NPS-47",
    ),
    (
        "data/q1-2026-results.pdf",
        "revenue 14.2M; net-new-merchants 412 (honest-oracle revenue agreement)",
    ),
    (
        "data/dashboards/april-2026-kpi-dashboard.html",
        "revenue 14.2M + NPS-47 (number AND as-of); dashboard side of nps-framing",
    ),
    (
        "data/board-update-2026-04-22.md",
        "Confluence Q3 corroboration; NPS honest-framing; CEO priorities",
    ),
    (
        "data/interviews/leadership/Daniel_Tan.md",
        "Confluence ~Sep corroboration; Daniel->Arjun hierarchy; 'Tan' name trap",
    ),
    (
        "data/org-chart.md",
        "Daniel->Arjun->Wei + Sara->Daniel reporting lines; headcount 274",
    ),
    (
        "data/email/cosmos-hotels-debrief.md",
        "Marcus Lee owns Cosmos (customer ownership)",
    ),
    (
        "data/email/customer-acai-express-thread.md",
        "Maria Santos owns Acai (two-Marias, side A)",
    ),
    (
        "data/interviews/sales/maria-silva.md",
        "Maria Silva Brasil revenue 4.8M (two-Marias, side B)",
    ),
    (
        "data/code/contributors-analysis-q1-2026.md",
        "Sara Wijaya top contributor; 'Daniel Tan' vs 'Tan Wei Ming' (two-Tans)",
    ),
]


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _dump(obj: object, path: Path, header: str) -> None:
    with path.open("w", encoding="utf-8") as fh:
        fh.write(header)
        yaml.safe_dump(obj, fh, sort_keys=False, allow_unicode=True, width=100)


def main() -> int:
    subset = {uri for uri, _ in MANIFEST}

    # 1) Copy docs, preserving their data/-relative subpath so source_uri + globs match.
    if SAMPLE_DATA.exists():
        shutil.rmtree(SAMPLE_DATA)
    for uri, _why in MANIFEST:
        src = ROOT / uri
        if not src.exists():
            raise SystemExit(f"manifest doc missing from corpus: {uri}")
        dst = SAMPLE_DIR / uri  # eval/sample/data/<subpath>
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    # 2) Filter the golden facts by source_uri (verbatim entries — no re-labeling).
    golden = _load(GOLDEN_FACTS)
    kept_facts = [f for f in golden.get("facts", []) if f.get("source_uri") in subset]
    kept_ids = {f["id"] for f in kept_facts}
    dropped_facts = [
        f["id"] for f in golden.get("facts", []) if f["id"] not in kept_ids
    ]

    # Contradictions: keep when claim_a survives (claim_b may be null); trim corroborators.
    kept_contras = []
    for c in golden.get("contradictions", []):
        if c.get("claim_a") in kept_ids:
            c = dict(c)
            c["corroborating_sources"] = [
                s for s in c.get("corroborating_sources", []) if s in subset
            ]
            kept_contras.append(c)

    # 3) Filter questions: keep golden_refs that survive; keep the question if it still has
    #    support (>=1 surviving ref, or it's an open cross-doc synthesis with none).
    questions = _load(QUESTIONS)
    kept_q = []
    for q in questions.get("questions", []):
        refs = q.get("golden_refs") or []
        surviving = [r for r in refs if r in kept_ids]
        if refs and not surviving:
            continue  # all its evidence dropped out of the subset
        q = dict(q)
        q["golden_refs"] = surviving
        kept_q.append(q)

    # 4) Write the subset oracle.
    fact_header = (
        "# AUTO-GENERATED by eval/sample/build_sample.py — a curated SUBSET of\n"
        "# test/golden/facts.yaml (do not hand-edit; re-run the builder). Entries are\n"
        "# verbatim from the golden oracle, filtered to the sample corpus.\n"
    )
    q_header = (
        "# AUTO-GENERATED by eval/sample/build_sample.py — a curated SUBSET of\n"
        "# eval/questions.yaml; golden_refs trimmed to facts present in the sample.\n"
    )
    _dump(
        {"facts": kept_facts, "contradictions": kept_contras},
        SAMPLE_DIR / "facts.yaml",
        fact_header,
    )
    _dump({"questions": kept_q}, SAMPLE_DIR / "questions.yaml", q_header)

    # 5) Report (so the human can eyeball trap coverage).
    print(f"sample corpus: {len(MANIFEST)} docs -> {SAMPLE_DATA}")
    print(
        f"facts kept:    {len(kept_facts)}/{len(golden.get('facts', []))}  (dropped: {', '.join(dropped_facts) or 'none'})"
    )
    print(
        f"contradictions kept: {len(kept_contras)} ({', '.join(c['id'] for c in kept_contras)})"
    )
    print(f"questions kept: {len(kept_q)}/{len(questions.get('questions', []))}")
    for q in kept_q:
        print(f"  - {q['id']}: refs={q['golden_refs']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
