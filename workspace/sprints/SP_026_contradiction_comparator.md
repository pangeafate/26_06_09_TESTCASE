---
sprint_id: SP_026
tier: Standard
features: []
user_stories:
  - "As the operator, false-positive contradictions where the number agrees but a parenthetical annotation differs stop being reported (the comparator strips letter-bearing annotation parens in the numeric path only, never the text copy, never digit-only accounting negatives), AND dense deal/CRM tables stop silently dropping their extractions to an empty result because the extraction token ceiling was doubled — without losing a single real conflict or real claim."
schema_touched: false
structure_touched: false
status: Complete
isolation: shared-tree
branch: sprint/SP_023-graph-temporal-tools
worktree: ""
agent_owner: "main (operator-directed; concurrent sibling line)"
dependencies: [SP_009]
dev_dependencies: []
touches_paths:
  - helixpay/ingest/normalize.py
  - helixpay/ingest/extract/llm.py
  - helixpay/db/repository.py
  - prompts/extract_claims.md
  - scripts/recompute_contradictions.py
  - scripts/rerecord_one.py
  - scripts/diag_extract_one.py
  - test/unit/ingest/test_normalize.py
  - research/contradiction-recall-and-extraction-delta.md
  - workspace/sprints/SP_026_contradiction_comparator.md
touches_checklist_items: [normalize-annotation-paren, extract-maxtokens-bump, crm-deal-prompt-section, repo-contradiction-maintenance-helpers, recompute-sweep-cli, recall-delta-report]
---

# SP_026: Contradiction comparator + extraction robustness

> **GOVERNANCE NOTE (back-filled at the SP_024–028 merge gate, 2026-06-11).** This sprint was
> implemented by a concurrent sibling line in commit `62e6906` **without a persisted Stage-2 plan
> or a recorded Stage-5 plan-blind review** (DEV_RULES §10/§9). This file is an honest **as-built**
> record reconstructed from the commit and from `research/contradiction-recall-and-extraction-delta.md`;
> the independent plan-blind review was performed retroactively at the merge gate (see
> Post-Implementation Review). The work is already live (since 2026-06-10) and SP_028a/SP_028b build
> on it. Recorded here so the lifecycle ledger is complete, not to imply the original process was
> followed.

## Sprint Goal

Two precision/robustness fixes to the ingest path, plus eval/diagnostic tooling:

1. **Comparator precision** — the contradiction normalizer treated "same number, different
   parenthetical annotation" (e.g. `SGD 14.2M (audited)` vs `SGD 14.2M (preliminary)`) as a
   conflict. Strip letter-bearing annotation parens in the **numeric path only** (the text copy is
   untouched; digit-only accounting negatives like `(2.1)` are deliberately preserved).
2. **Extraction robustness** — dense deal/CRM tables overran the extraction `_MAX_TOKENS` (8192) and
   returned empty, silently dropping every claim in the chunk. Raise to 16384 (pay-per-generated
   token → no added cost on small chunks).
3. **Tooling** — `scripts/recompute_contradictions.py` (re-derive all contradictions $0 after a
   comparator change — later superseded/extended by SP_028a's single-writer sweep),
   `rerecord_one.py` (single-doc paid re-record), `diag_extract_one.py`; a sales-pipeline/CRM
   deal-snapshot section in `extract_claims.md`; off-Protocol maintenance reads on the repository
   (`clear_contradictions` / `distinct_claim_groups` / `distinct_link_groups`).

## Technical Approach

- `helixpay/ingest/normalize.py` — `_ANNOTATION_PAREN` regex applied in the numeric branch; text
  copy preserved; shared substrate so scoped narrowly (8 callers incl. the eval matcher).
- `helixpay/ingest/extract/llm.py` — `_MAX_TOKENS = 16384`.
- `helixpay/db/repository.py` — three additive maintenance helpers (not on the frozen `Repository`
  Protocol; pure-read + one maintenance DELETE), consumed by the recompute CLI.
- `prompts/extract_claims.md` — CRM deal-snapshot section (a deal's recorded state is an asserted
  fact, not a hypothetical to skip).

## Testing Strategy

TDD on the comparator change: `test/unit/ingest/test_normalize.py` adds 6 tests — annotation drop,
text-preservation, same-number/different-annotation non-conflict, real-disagreement survives,
planted-revenue-conflict survives, accounting-negative not stripped. All $0 (no DB/API).

## Success Criteria

- Annotation-only differences no longer register as contradictions; real disagreements still do.
- Dense-chunk extractions no longer truncate to empty.
- `uv run pytest test/unit/ingest -k "normalize"` green; no regression in the contradiction suite.

## Acceptance

Verified at the merge gate: `uv run pytest test/unit/ingest -k "normalize or annotation or conflict or extract"`
→ **78 passed**. Live-consistent at HEAD (`_ANNOTATION_PAREN` in `normalize.py`, `_MAX_TOKENS=16384`).

### Pre-Implementation Review

- **Iteration 1** — severity N/A: **NOT performed at implementation time** (governance gap — no
  Stage-2 plan on disk before code). Design rationale was captured post-hoc in
  `research/contradiction-recall-and-extraction-delta.md` (recall metrics + root-cause taxonomy).
  Reviewer: none (recorded honestly). Files reviewed: none.

### Post-Implementation Review

- **Iteration 1** (2026-06-11, general-purpose, plan-blind, code+tests only, at the SP_024–028 merge
  gate) — severity 0 CRITICAL / 0 HIGH; verdict SHIP-WITH-NITS. Confirmed the annotation-paren strip
  is numeric-path-only (accounting negatives preserved), the 6 new tests cover the behavior (78
  passed), and the change is shared substrate correctly scoped. Nits: missing original plan (closed
  by this file); the `raw_verb` INSERT in `62e6906` predates its `ALTER TABLE` column in `bac2f0f`
  → that commit is not independently bisectable against the DB (harmless at HEAD where both coexist).
  Files reviewed: helixpay/ingest/normalize.py, helixpay/ingest/extract/llm.py,
  helixpay/db/repository.py, prompts/extract_claims.md, test/unit/ingest/test_normalize.py.

## Progress

- **Implemented** 2026-06-10 (commit `62e6906`), deployed live the same line; SP_028a/SP_028b build
  on the comparator + recompute CLI.
- **Back-filled** 2026-06-11 at the SP_024–028 merge gate: this plan + the merge-gate plan-blind
  review above + a condensed CLAUDE.md gotcha (full form in `workspace/CLAUDE_GOTCHAS.md`).
