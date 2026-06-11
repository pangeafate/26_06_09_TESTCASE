---
sprint_id: SP_029
tier: Standard
features: [extraction-quality-audit]
user_stories:
  - "As the operator, after any ingest/replay I can run a read-only `python -m helixpay.audit` (or `make audit`) that judges what actually landed in the DB — provenance-chain integrity, grounding (evidence supports the value), resolution honesty (subject resolved or honestly NULL), predicate canonicalization — the integrity/precision census the 41-fact golden recall oracle structurally cannot give me, with planted known-answer traps that pinpoint which layer broke and a deterministic suspicious-oversampled sample to read by eye."
schema_touched: false
structure_touched: false
status: Complete
isolation: branch-only
branch: sprint/SP_028b-llm-adjudication
worktree: ""
agent_owner: "main (operator-directed: 'Land it now via SP_029-audit')"
dependencies: [SP_009, SP_017]
dev_dependencies: []
touches_paths:
  - helixpay/audit/__init__.py
  - helixpay/audit/__main__.py
  - helixpay/audit/invariants.py
  - helixpay/audit/models.py
  - helixpay/audit/report.py
  - helixpay/audit/run.py
  - helixpay/audit/sampling.py
  - helixpay/audit/traps.py
  - helixpay/db/audit_queries.py
  - test/unit/audit/test_invariants.py
  - test/unit/audit/test_sampling.py
  - test/unit/audit/test_traps.py
  - test/unit/audit/test_report.py
  - test/integration/db/test_audit.py
  - Makefile
  - CLAUDE.md
  - USER_STORIES.md
  - workspace/sprints/SP_029_audit.md
touches_checklist_items: [audit-restore-tests, audit-evidence-classification, audit-make-target, audit-live-baseline, audit-docs]
---

# SP_029: Land the extraction-quality audit subsystem

## Sprint Goal

Take over and land the parked, untracked `audit` subsystem (built since SP_017, deliberately
held out of tree by `f510ef3` "for its own reviewed sprint") through the full lifecycle. The
subsystem is a **read-only** ontology auditor (`python -m helixpay.audit`) that complements the
golden eval: the golden set certifies *recall of 41 known facts*; this certifies the *integrity of
everything that landed* — provenance chain, grounding, resolution honesty, predicate
canonicalization — over the whole corpus, with planted traps and a suspicious-oversampled manual
sample.

A 5-agent merge-gate-style assessment found the code correct, typed (`mypy` clean), layered
correctly (capability `helixpay/audit/` → infra `helixpay/db/audit_queries.py`), and read-only by
construction (driver-enforced read-only session, proven by an integration test). Two gaps block a
trustworthy landing, both addressed here.

## Technical Approach

1. **Restore the two dropped unit tests.** `test/unit/audit/test_traps.py` + `test_report.py` were
   committed by SP_017 (`9d28e6c`) then deleted by `f510ef3` to unblock CI when the module was
   uncommitted. Recover both from `9d28e6c` (`git show 9d28e6c:<path>`). Coverage goes 20 → 44 tests.

2. **Fix the evidence invariant's over-reporting (the live-baseline discovery).** Running the audit
   read-only against live `helixpay_full` (2347 claims) surfaced **322 ERROR-level evidence
   violations** — but classification shows the pipeline stores **case/whitespace-normalized**
   evidence, not byte-verbatim spans, so the exact-match check cries wolf:
   - of 215 "evidence not a verbatim substring": **13 case-only + 129 whitespace+case = 142 cosmetic**,
     **73 genuinely absent**.
   `check_evidence` (`invariants.py`) must **classify**, not lump:
   - byte-exact substring → clean;
   - matches only after `casefold` + whitespace-collapse → **WARN `evidence_not_verbatim`** (the span
     is right; provenance is non-byte-exact — a soft quality signal, the SP_009 verbatim-span intent
     deviating, not corruption); when cosmetic, the exact-offset check is moot and is not also ERRORed;
   - absent even normalized → **ERROR `evidence_not_in_chunk`** (real corruption);
   - when evidence IS verbatim but the stored offsets don't address it → keep **ERROR
     `offsets_mismatch_evidence`** (a genuine stale-offset bug).
   `is_suspicious` uses the same normalized check so the manual sample isn't dominated by cosmetic
   cases. This does NOT touch the extraction pipeline (the "evidence stored non-verbatim" observation
   is logged as a separate follow-up, possibly a paid re-record); it makes the AUDIT's numbers honest.

3. **Wire it.** Add a `make audit` target (`docker compose run --rm app python -m helixpay.audit`,
   mirroring `make demo`). It is advisory reporting, NOT a blocking CI gate (with 73 genuine + 142
   cosmetic findings on live data, a `--strict` gate would fail; `--strict` stays an opt-in flag).

4. **Capture a live baseline** read-only against `helixpay_full` ($0 — DB read only, read-only
   session, no LLM/Voyage) into `workspace/acceptance/` for the record.

5. **Docs.** One condensed CLAUDE.md gotcha (audit is read-only; evidence stored non-verbatim →
   `evidence_not_verbatim` WARN vs `evidence_not_in_chunk` ERROR) with the full form in
   `workspace/CLAUDE_GOTCHAS.md`; a USER_STORIES entry.

## Testing Strategy (Rule 1 — failing test first)

New/updated unit tests in `test/unit/audit/test_invariants.py` (all $0, pure, no DB), RED before the
classification fix:
- evidence differing only by case → WARN `evidence_not_verbatim`, NOT ERROR;
- evidence differing only by collapsed whitespace → WARN `evidence_not_verbatim`;
- evidence genuinely absent (even normalized) → ERROR `evidence_not_in_chunk`;
- verbatim evidence + wrong offsets → ERROR `offsets_mismatch_evidence`;
- verbatim evidence + correct offsets → clean (no evidence violation);
- `is_suspicious` does not flag a cosmetic-normalized claim.
Plus the 2 restored test files (traps, report). Full audit suite + `uv run mypy helixpay/audit` green.
Integration test (`test/integration/db/test_audit.py`, db-marked) verifies the read-only session
rejects writes.

## Success Criteria

- `uv run pytest test/unit/audit` green (≈50 tests incl. restored + new); `mypy helixpay/audit` clean.
- Live read-only baseline run produces a report; `evidence_not_in_chunk` ERROR count drops from 186 to
  the genuine-absent residual (~73), with cosmetic cases reclassified to `evidence_not_verbatim` WARN.
- `make audit` runs end-to-end; full repo gate (`validators/run_all.py`) green.
- No production-runtime/schema change; the live serving path is untouched.

## Risk

- **Over-reclassification** — downgrading a real corruption to WARN. Mitigated: the normalized match
  requires the same characters in the same order (only case + whitespace folded), so a genuinely wrong
  span still falls to ERROR; tests pin both directions.
- **Shared `normalize_value` coupling** — `check_evidence`'s value check already uses it; the new
  span-normalization is a LOCAL helper (`casefold` + `" ".join(split())`), NOT a change to the shared
  `helixpay/ingest/normalize.py` (which has 8 callers incl. the eval matcher).

### Pre-Implementation Review

- **Iteration 1** (2026-06-12, architect-reviewer, plan) — APPROVE-WITH-CHANGES, 0 CRITICAL / 3 HIGH / 2 MEDIUM. Confirmed the reclassification is sound and *required*: the producer `helixpay/ingest/extract/grounding.py` `locate_span` already tolerates case/whitespace (exact + `\s+`/IGNORECASE paths, storing RAW offsets), so the audit's byte-exact check is stricter than the pipeline — realigning it is correct (cite grounding.locate_span). Required: (H) pin the helper to casefold+whitespace-ONLY, no looser than locate_span, + both-direction tests (`14.2M`↔`14.3M` stays ERROR); (H) gate the offset check inside the byte-exact branch so cosmetic claims don't double-ERROR, + a success metric for `offsets_mismatch_evidence` dropping; (M) update `report._sample_flags` in lockstep via a shared 3-way helper; (M) file the producer non-verbatim-evidence as a Rule-20 bug-log entry, not just a gotcha. Layer boundaries clean; advisory-not-gate correct; fetch_claim_rows-unbounded + trap-canonicalize-weaker noted as known limits. Files reviewed: helixpay/audit/invariants.py, helixpay/ingest/extract/grounding.py, helixpay/ingest/pipeline.py, helixpay/db/audit_queries.py, helixpay/audit/{report,traps,models}.py.
- **Iteration 2** (2026-06-12, code-reviewer, plan) — APPROVE-WITH-CHANGES, 2 CRITICAL / 3 HIGH / 6 WARN. Required before coding: (C) `report._sample_flags` (`report.py:20`) and (C) `is_suspicious` (`invariants.py:197`) both inline the byte-exact check and need actual code changes (not just tests); (H) preserve the `not rec.evidence` early-return guard (empty-string `"" in chunk` is always True); (H) structure as a THREE-WAY branch so the offset check only runs on the byte-exact path; add a cosmetic-match-with-valid-offsets → only-WARN test. Verified NO API drift — both restored tests (test_traps.py, test_report.py from 9d28e6c) pass as-is against today's modules; caveat: test_report.py's `..._flags_ungrounded...` test must move with `_sample_flags`. `make audit` should use `$(APP_RUN)`; `str.split()` collapses unicode ws correctly. Files reviewed: helixpay/audit/{invariants,report,traps,models,sampling}.py, test/unit/audit/test_invariants.py, Makefile, git 9d28e6c:test/unit/audit/{test_traps,test_report}.py.

### Post-Implementation Review

- **Iteration 1** (2026-06-12, code-reviewer, plan-blind, code+tests only) — SHIP-WITH-FIXES, 0 CRITICAL / 0 HIGH, 1 MEDIUM (test_report.py lacked a test for the `non-verbatim` rendering branch — added `test_format_report_flags_non_verbatim_evidence_in_sample`) + 3 LOW (NBSP fold, empty-string comment, test-readability). Verified: the three-way classification sound, the anti-laundering property holds (`14.2M`≠`14.3M` stays ERROR), the offset check unreachable for normalized/absent, the byte-exact migration complete across all 3 call sites, no regression to the other invariants/rollup. 53→54 tests, mypy clean. Files reviewed: helixpay/audit/{invariants,report}.py, test/unit/audit/{test_invariants,test_report}.py, helixpay/db/audit_queries.py, Makefile.
- **Iteration 2** (2026-06-12, architect-reviewer, plan-blind) — APPROVE, all findings LOW/MEDIUM non-blocking. Confirmed the WARN reclassification against the producer (`pipeline.py:259` persists the model quote; `grounding.locate_span` stores case/ws-tolerant raw offsets); layer boundaries clean (capability→shared→infra; `audit_queries` imports nothing from `audit`); `evidence_grounding` correctly centralized in invariants.py (no import cycle); read-only by construction (integration-test-proven). MEDIUM (carried as documented tech-debt): the producer DISCARDS the non-verbatim signal (`grade()` returns GRADE_EXACT for case/ws deviations, no confidence penalty, no `grounding_grade` column) — the advisory audit's `evidence_not_verbatim` WARN is its only durable surfacing; added the cross-reference comment in `_normalize_span`. Files reviewed: helixpay/audit/{invariants,report}.py, helixpay/ingest/extract/{grounding,extractor}.py, helixpay/ingest/pipeline.py, helixpay/db/audit_queries.py.

## Known limitations (honest, by design)

- **Traps are fixture-calibrated.** On the full corpus `no_false_revenue_contradiction` is INFORMATIONAL (real regional/quarterly/plan-vs-actual revenue conflicts legitimately exist — SP_028a/b precision territory, not a pipeline bug); the trap self-documents this. GA + two-Marias traps hold on both fixture and full corpus.
- **Producer non-verbatim evidence (tech-debt, follow-up).** `helixpay/ingest/pipeline.py` persists the model's evidence quote (not the located raw span) and `locate_span` tolerates case/whitespace while storing raw offsets, so ~136 live claims have non-byte-verbatim evidence that the producer's `grade()` does NOT penalize and no column records. The audit's `evidence_not_verbatim` WARN is the only signal. Closing the loop (store the grade, or re-slice the matched raw span back into `evidence` so storage is byte-verbatim) is a future pipeline sprint, gated behind a paid re-record.
- **`fetch_claim_rows` materializes the full claims table** (bounded corpus OK; add a cursor for 100k+).

## Progress

- **Stage 1–2** 2026-06-12 — took over the parked subsystem; restored the 2 dropped tests (44 pass);
  ran it read-only against live `helixpay_full` and discovered the evidence over-reporting (322 ERROR
  → cosmetic vs genuine). Plan written; Stage-3 reviewed (architect + code, APPROVE-WITH-CHANGES, all
  folded).
- **Stage 4 (TDD)** 2026-06-12 — shared 3-way `evidence_grounding` classifier; `check_evidence`
  three-way branch (offset check gated to the byte-exact path); `is_suspicious` + `report._sample_flags`
  migrated to the same helper; 10 new tests RED→GREEN. 54 unit pass, mypy clean.
- **Live validation** — re-ran read-only against `helixpay_full` (2347 claims): ERRORs **322 → 50**
  (genuine `evidence_not_in_chunk` only), `offsets_mismatch_evidence` **136 → 0** (were all cosmetic),
  new `evidence_not_verbatim` **136 WARN**; baseline saved to
  `workspace/acceptance/SP029_audit_baseline_helixpay_full.json`. $0 (DB read only).
- **Stage 5** 2026-06-12 — 2 plan-blind iterations (code-reviewer SHIP-WITH-FIXES, architect APPROVE);
  MEDIUM test + cross-ref comment applied.
- **Stage 6 (docs)** — `make audit` target; CLAUDE.md gotcha (+ full in CLAUDE_GOTCHAS.md); USER_STORIES.
