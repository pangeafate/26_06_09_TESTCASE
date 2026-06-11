---
sprint_id: SP_024
tier: Standard
features: []
user_stories:
  - "As the operator running the one paid full extraction, the sanctioned `scripts/full_run.py` gate must be openable when extraction is genuinely complete — so a cleanly-extracted corpus that merely declined to assert hypothetical/ungrounded statements reaches 9/9 PASS, instead of every doc being forced to INCOMPLETE forever by benign drops."
schema_touched: false
structure_touched: false
status: In Progress
isolation: branch-only
branch: sprint/SP_024-drop-taxonomy-gate
worktree: ""
agent_owner: "main (operator-directed)"
dependencies: [SP_014, SP_015, SP_016]
dev_dependencies: []
touches_paths:
  - helixpay/ingest/extract/ledger.py
  - eval/smoke/check_smoke.py
  - test/unit/ingest/test_ledger.py
  - test/unit/ingest/test_extractor.py
  - test/unit/eval/test_check_smoke.py
  - test/unit/eval/test_ledger_seam.py
  - workspace/sprints/SP_024_drop_taxonomy_gate.md
  - CLAUDE.md
touches_checklist_items: [ledger-lossy-drops, verdict-lossy-gating]
---

# SP_024: drop-taxonomy split — benign drops must not freeze the proof gate

## Sprint Goal

The SP_015 completeness verdict (`eval/smoke/check_smoke.py:doc_verdict`) forced any document
with `items_dropped > 0` to **INCOMPLETE**, and `scripts/full_run.py` only permits the paid
full extraction when every smoke doc is **PASS**. But the extraction loss ledger counts five
drop reasons under one `items_dropped` total, and two of them — `hypothetical` (a conditional/
future statement correctly NOT asserted) and `ungrounded` (a claim unsupported by source text,
correctly dropped to preserve faithfulness) — are the system working *as designed* and are
present on essentially every real document. So `items_dropped == 0` was structurally
unreachable: the sanctioned gate could **never** emit 9/9 PASS, even at full golden recall.
`SP015_proof.md` acknowledged this ("INCOMPLETE … the gate stays shut … by design") but the
machine gate offered no path to accept reviewed-benign drops.

Fix: split the drop taxonomy. Only **lossy** drops (genuine signal the pipeline could not
faithfully represent: `validation_error`, `unmappable_enum`, `unparseable_as_of`) gate the
proof. Intentional non-assertions do not.

## Scope & boundaries

- IN: classify drop reasons in `LossLedger`; expose `lossy_drops` from `probe()` (additive
  key; `items_dropped` retained as the all-reasons total for observability); gate
  `doc_verdict` completeness on `lossy_drops`, surface benign drops as informational only.
- OUT: no change to extraction behaviour, the drop *reasons* themselves, the embedding/golden
  signals, or `full_run.py`/`prod_seed.sh`. `empty_extractions`/`truncated_calls` still FAIL
  (silent loss is always blocking).

## Design

- `LOSSY_DROP_REASONS` / `INTENTIONAL_DROP_REASONS` taxonomy in `ledger.py`. `DocLoss.lossy_drops`
  = drops whose reason is **not** intentional (fail-safe: an unrecognised future reason counts
  as lossy → can only raise severity, never silently PASS).
- `probe()` adds `lossy_drops` (the gating subset). Original three keys unchanged.
- `doc_verdict`: completeness branch gates on `lossy_drops`; a pre-SP_024 ledger lacking the
  key falls back to the total (conservative — an un-split ledger cannot prove its drops benign).
  Benign drops append an informational reason but never downgrade the verdict.

## Testing Strategy

TDD. New/updated unit tests pin: probe four-key shape + lossy-only counting; benign-only drops
PASS; lossy drops INCOMPLETE; back-compat fallback; the lossy>total defensive clamp; the real
`LossLedger → ledger_probe_from → doc_verdict` seam for both benign-PASS and lossy-INCOMPLETE.

## Success Criteria

- Full unit suite + mypy green. (Result: 635 passed, 1 skipped; mypy clean over 71 files.)
- No path lets a genuinely lossy/empty/truncated doc silently PASS (verified by plan-blind review).
- The smoke proof, re-recorded with current code, reaches the expected verdict on benign-only docs.

## Reviews

- Stage-5 plan-blind code review (independent, code+tests only): no CRITICAL/HIGH. One MEDIUM
  (stale class docstring) and one LOW (untested lossy>total clamp) — both addressed. Reviewer
  confirmed the fail-safe direction and that no lossy/empty/truncated doc can reach PASS.

## Documentation & Deploy

- CLAUDE.md gotcha appended (drop taxonomy / gate semantics).
- Eval/dev-tooling change; not part of the production serving path. No prod deploy required for
  the fix itself; it unblocks the separately-gated paid full extraction.
