# SP_021 — Structured image extraction: run finding & evidence

**Sprint:** SP_021 (lift the image caption-only scope cut → structured chart extraction; grade the
chart datapoints). **DB:** `helixpay_smoke` (name only, never a DSN — §7). **Date:** 2026-06-11.

## $0 / unit state (no API) — DONE

- 639 unit tests pass, 38 DB-skips, `mypy helixpay` clean. New: loader structured-caption
  passthrough + as_of-from-header + the M1 first-ISO regression test; two prompt-presence guards
  (`solid`/`dashed` line-style + a **negative** numeric assertion that the Charts section leaks no
  corpus numbers).
- Golden: two image-sourced recall-bar facts added to the **master** `test/golden/facts.yaml` and
  the smoke subset **regenerated** via `build_smoke` (14 facts; `image-brasil-revenue-q1-2026`,
  `image-sea-revenue-q1-2026` present). Guard relaxed to allow graded datapoints while pinning the
  caption fact to `recall_bar:false`.
- Stage-3 (architect + code-reviewer) and Stage-5 (code-reviewer) reviews recorded in the sprint
  plan; all CRITICAL/HIGH/MEDIUM findings adopted.

## PAID acceptance (behavioral closure, Rule 21) — PENDING operator approval

The $0 replay cache predates this prompt, so it reports both image facts MISSING (expected). The
real proof is a **single-image** Sonnet vision re-extraction of `revenue-trend-q1-2026.jpeg`:

```bash
# (operator-approved) re-extract just the one image into helixpay_smoke through the LIVE code,
# PYTHONPATH=/app so the edited loader/prompt run (see the CLAUDE.md harness gotcha), then grade.
# Fill in below after the run:
```

Expected / to record:
- `image-brasil-revenue-q1-2026` **FOUND** (gating anchor; value+source+as_of) — must-pass.
- `image-sea-revenue-q1-2026` verdict **reported** (fidelity probe; a `9.40`/`9.3` read MISSES under
  normalize_value — record as a normalization blind spot, not re-rigged).
- Exactly **one** `HelixPay SEA` entity row (minted, not seeded; distinct from `HelixPay`/`HelixPay Brasil`).
- Both Brasil claims coexist (interview + image), no spurious contradiction on (`HelixPay Brasil`, `revenue`).
- No regression on the prior recall-bar facts.

_Result: TBD (awaiting operator go-ahead for the paid call)._
