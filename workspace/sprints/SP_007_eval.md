---
sprint_id: SP_007
tier: Standard
features: [eval-harness, golden-ground-truth, adversarial-verifier]
user_stories: []
schema_touched: false
structure_touched: false
status: In Progress
isolation: git-worktree
branch: sprint/SP_007-eval
worktree: .claude/worktrees/SP_007
agent_owner: "Agent 6 (Eval & Ground-Truth, author-independent)"
touches_paths:
  - eval/**
  - test/golden/**
  - .claude/agents/verifier.md
touches_checklist_items: [eval-golden-facts, eval-questions, eval-harness, eval-verifier-refine]
fix_type: ""
---

# SP_007: Eval & Ground-Truth — the author-independent oracle

## Sprint Goal

Author the **golden ground-truth set** and the **two-level eval harness** for the HelixPay
ontology build, derived **only** from the raw `data/` and the frozen `contracts/` — never
from any build slice's output. Deliver: `test/golden/facts.yaml` (a dozen-plus by-eye facts,
≥1 per source format, including the real planted contradiction), `eval/questions.yaml` (the
deep-question set from SPEC §8 with per-question `checks:`), `eval/run.py` (the harness that
reports extraction precision/recall over the golden set and per-question answer pass/fail +
latency), and a refined `.claude/agents/verifier.md`. Because I wrote neither the extraction
nor the query code, this set is an honest oracle and I am the legitimate author-independent
grader for the adversarial stage (SPEC §8). The `/goal` condition must be **evaluable from
the harness output**.

## Current State

- The Phase 0 gate is frozen on `main`: `contracts/**` (models + 4 Protocols), `db/**`
  (`PostgresRepository`, `schema.sql`, `migrate.py`), `config.py`, `seed/**` (roster,
  `metric_vocab`, query fixture), `CLAUDE.md` §7, and a `.claude/agents/verifier.md` **stub**.
- Build Agents 1–5 are running in parallel worktrees; their code is **not** available to me
  and must not be read while authoring ground truth.
- No `eval/` directory and no `test/golden/` directory exist yet.
- The gate's query **fixture** (`helixpay/seed/fixtures.py`) plants a *synthetic* Q1-revenue
  conflict (dashboard 14.2M vs board-deck **13.9M**) so Agent 3 has a live contradiction row.
  **That 13.9M value does not exist in the raw `data/`** — see the critical finding below.

## Desired End State

- `test/golden/facts.yaml` — ≥12 facts verified by eye from the raw files, ≥1 per format
  (md, pdf, html, slack, email, code, interview; image at caption-level only), each a
  `(subject, predicate, value, as_of, source_uri)` row, typed `claim` or `link`, plus the
  real planted contradiction captured as **two** coexisting claims with both sources + as-ofs.
- `eval/questions.yaml` — the SPEC §8 deep questions, each with `checks:` that exercise one
  failure mode (hierarchy + freshest as_of; contradiction surfaced + attributed; cross-document
  synthesis with multiple citations; dashboards-vs-board-deck disagreement; customers + owners
  via entity resolution + alias handling). Every check that asserts provenance requires
  `cites_source`, and `states_as_of` where staleness is in play.
- `eval/run.py` — a typed, documented harness that:
  1. **Extraction check** — for each golden fact, asserts a matching claim/link exists in the
     Repository with the right `source_uri` + `as_of`; reports **recall** and a golden-set
     **precision** over the set, with a per-fact FOUND/MISMATCH/MISSING verdict.
  2. **Answer check** — runs each question through `QueryEngine.ask()` (resolved lazily by
     Protocol at run time, injectable for tests) and asserts its `checks`; reports per-question
     pass/fail + latency, and whether ≥1 answer surfaced a real contradiction.
  Runs end-to-end and prints a report from which the `/goal` condition is decidable; exits
  non-zero when the recall bar is missed, an answer check fails, or no contradiction surfaces.
- `.claude/agents/verifier.md` — refined from the stub with the per-slice adversarial checklist,
  the two-level autotest definition, the golden-set recall bar, and the corrected contradiction.
- `eval/README.md` — documents the harness, the recall bar, precision/recall definitions, and
  the honest-oracle finding about the real vs synthetic contradiction.

## What We're NOT Doing

- **Not** reading or importing Agents 1–5's code while authoring ground truth — every golden
  fact is derived from the raw `data/` and the frozen contracts only. The harness resolves the
  concrete `QueryEngine`/`Repository` by Protocol at run time (integration), not by reading code.
- **Not** editing other agents' files. Findings from the adversarial pass (Phase B) go to the
  fixer as a ranked list; I do not patch extraction or query code.
- **Not** deep figure/number extraction from JPEGs — image facts are caption-level only (SPEC
  §11 scope cut), so an image golden fact is marked `recall_bar: false` (informational) and
  excluded from the recall denominator, to avoid penalizing a deliberately scoped-out capability.
- **Not** editing `helixpay/contracts/**`, `CLAUDE.md`, `pyproject.toml [dependencies]`, or any
  meta-doc (orchestrator-owned at integration). New deps listed under `## Dependencies`.

## Technical Approach

1. **Ground truth (`test/golden/facts.yaml`), by eye from raw files.** Spread ≥1 fact per
   format and cover every failure mode the questions test:
   - **md (overview):** `HelixPay`, `runway`, `~18 months`, as_of 2026-04-22 → `data/overview.md`.
   - **md (all-hands):** the *public* Confluence stance — `Project Confluence`, `ga_target`,
     `end of June 2026`, as_of 2026-04-15 → `data/all-hands-2026-04-15.md`.
   - **pdf (results):** `HelixPay`, `revenue`, `SGD 14.2M`, as_of 2026-03-31 →
     `data/q1-2026-results.pdf`; plus `net_new_merchants` 412.
   - **html (dashboard, number + as-of):** `HelixPay`, `revenue`, `14.2M`, as_of 2026-03-31,
     dashboard exported 2026-04-21 → `data/dashboards/april-2026-kpi-dashboard.html`; plus
     `nps` 47.
   - **slack:** Sofia — Pipedrive off / HubSpot for everyone `end of June`, as_of 2026-04-15 →
     `data/chat/sales-floor-april.md`.
   - **email (customer ownership):** `Cosmos Hotels` `owned_by` `Marcus Lee` (Enterprise AE),
     as_of 2026-03-14 → `data/email/cosmos-hotels-debrief.md`; `Açaí Express SP` relationship
     owner `Maria Santos`, as_of 2026-04-14 → `data/email/customer-acai-express-thread.md`.
   - **code:** `helixpay/core` top contributor `Sara Wijaya` (89 commits Q1), as_of 2026-03-31
     → `data/code/contributors-analysis-q1-2026.md`.
   - **interview (Q&A):** `HelixPay Brasil`, `revenue`, `SGD 4.8M`, as_of 2026-03-31 →
     `data/interviews/sales/maria-silva.md` (also confirms Maria Silva ≠ Maria Santos).
   - **org-chart link:** `Daniel Tan` `reports_to` `Arjun Kapoor`, as_of 2026-04-15 →
     `data/org-chart.md`; `Sara Wijaya` `reports_to` `Daniel Tan`.
   - **image (caption-level, informational):** revenue-trend chart title / source line →
     `data/images/revenue-trend-q1-2026.jpeg` (`recall_bar: false`).
   - **The real planted contradiction (temporal / source_disagreement):** Confluence GA date —
     **June / end-Q2** publicly (all-hands 2026-04-15) vs **end-Q3 / ~Sep 30** internally
     (Daniel Tan interview 2026-04-10, weekly review 2026-04-21, board update 2026-04-22, board
     deck 2026-05-12). Captured as two coexisting claims on `(Project Confluence, ga_target)`.
2. **Deep questions (`eval/questions.yaml`).** The five SPEC §8 questions verbatim in intent,
   each with `checks:` drawn from a fixed vocabulary the harness understands:
   `cites_source`, `states_as_of`, `resolves_hierarchy`, `uses_freshest_as_of`,
   `surfaces_contradiction`, `attributes_each_side`, `cross_document_synthesis`,
   `cites_multiple_sources`, `entity_resolution`, `alias_handling`. Add the Confluence-timeline
   question so the *real* contradiction is exercised (not only the dashboards-vs-board-deck one,
   which the raw data does **not** support on revenue).
3. **Harness (`eval/run.py`), against the contracts.** Pure functions over the Protocols:
   - `load_golden(path)` / `load_questions(path)` → typed records (pydantic over the YAML).
   - `check_extraction(repo, golden)` → resolves each fact's subject via
     `repo.resolve_entity(name, context=…)`, canonicalizes the predicate via
     `repo.canonical_predicate`, reads `repo.get_claims`/`repo.get_links`, and matches value +
     `as_of` + `source_uri` (via `repo.get_sources`). Verdict per fact; **recall** =
     FOUND/|bar facts|, **precision** = FOUND/(FOUND+MISMATCH).
   - `check_answers(engine, questions)` → drives `engine.ask(q)` and evaluates each `check`
     against the returned `AnswerBundle` (citations non-empty + `as_of` present; contradictions
     non-empty for surface checks; multi-source for synthesis). Records latency per question.
   - `build_engine(repo)` lazily imports the concrete `QueryEngine` at run time (integration);
     tests inject a stub engine, so authoring stays code-independent of Agent 3.
   - `main()` prints the two-level report and returns an exit code encoding the `/goal` verdict.
   - No raw SQL (everything via `Repository`); secrets from env (`PostgresRepository.from_url()`);
     DB path is `db`-gated and degrades to a YAML-shape + injected-engine smoke when unset.
4. **Verifier refinement.** Extend `.claude/agents/verifier.md` with the per-slice checklist,
   the two-level autotest, the recall bar, and the corrected real-contradiction note.

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `test/golden/facts.yaml` | Create | Golden ground truth, by eye, ≥1/format + real contradiction |
| `test/golden/test_golden.py` | Create | Validate facts.yaml shape/coverage + questions.yaml shape (TDD red first) |
| `eval/__init__.py` | Create | Package marker |
| `eval/questions.yaml` | Create | Deep-question set with `checks:` (SPEC §8) |
| `eval/run.py` | Create | Two-level autotest harness against the contracts |
| `eval/models.py` | Create | Typed records (GoldenFact, Question, reports) over the YAML |
| `test/golden/test_harness.py` | Create | Harness unit tests vs an injected stub engine + fake repo (no DB) |
| `eval/README.md` | Create | Harness docs, recall bar, precision/recall defs, oracle finding |
| `.claude/agents/verifier.md` | Modify | Refine the gate stub (per-slice checklist, autotest, bar) |

## Testing Strategy

Following `practices/GL-TDD.md`, red→green per unit (the harness is itself test infrastructure,
so its own tests assert the *grader* behaves correctly — a wrong oracle is worse than none):

1. **Golden shape** (`test_golden.py`, no DB) — assert every fact has the five required keys +
   `source_uri` resolves to an existing file under `data/`; ≥1 fact per format on the recall
   bar; the contradiction pair is present with two distinct sources + as-ofs; every `as_of`
   parses as a date; `questions.yaml` checks are all from the known vocabulary.
2. **Harness logic** (`test_harness.py`, no DB) — a `FakeRepo` returning canned claims/links and
   a `StubEngine` returning canned `AnswerBundle`s drive `check_extraction`/`check_answers`:
   - a matching claim → FOUND; a wrong value/as_of → MISMATCH; nothing → MISSING.
   - recall/precision computed correctly on a mixed set.
   - `cites_source` fails on empty citations; `states_as_of` fails when `as_of` missing;
     `surfaces_contradiction` passes only when `contradictions` non-empty.
   - exit-code logic: green only when recall ≥ bar AND all answer checks pass AND ≥1 contradiction.
3. **Integration smoke** (`db`-marked) — against a migrated+seeded DB, `check_extraction` runs
   without error and the fixture contradiction surfaces through an injected identity engine;
   skipped when `DATABASE_URL` is unset (reuses `test/conftest.py`).

## Success Criteria

- [ ] `test/golden/facts.yaml` has ≥12 bar facts, ≥1 per format, each `(subject, predicate,
      value, as_of, source_uri)`, every `source_uri` an existing `data/` file
- [ ] The real planted contradiction (Confluence GA June vs end-Q3) is captured as two
      coexisting claims with both sources + as-ofs
- [ ] `eval/questions.yaml` lists the SPEC §8 questions, each with `checks:` from the known vocab
- [ ] `eval/run.py` runs end-to-end, prints extraction precision/recall + per-question pass/fail
      with latency, and returns a `/goal` exit code
- [ ] Harness is contract-only (Protocols), no raw SQL, secrets from env, DB-gated, engine injectable
- [ ] `test_golden.py` + `test_harness.py` green with no DB; `db`-marked smoke green under Postgres
- [ ] `.claude/agents/verifier.md` refined; recall bar stated in `eval/README.md`
- [ ] All existing validators/tests still pass

### Doc Reconciliation Checklist

Complete at Stage 6 (Documentation). Tick each meta-doc whose subject this sprint touched.

- [ ] `FEATURE_LIST.md` — eval harness + golden set marked (orchestrator reconciles at integration)
- [ ] `PROJECT_ROADMAP.md` — Agent 6 / verification milestone status
- [ ] `last-reconciled` bumped on each touched meta-doc (orchestrator)
- [ ] `python3 validators/validate_doc_reality.py .` returns 0
- [ ] `python3 validators/validate_doc_freshness.py .` returns 0

## Dependencies

No new runtime dependencies. Uses `pyyaml` and `pydantic` (already pinned in `pyproject.toml`)
and the stdlib. `pytest`/`mypy` (dev) already present.

## Collision Check

`touches_paths` (`eval/**`, `test/golden/**`, `.claude/agents/verifier.md`) are disjoint from
every other active sprint (SPEC §6 ownership table). The only shared touchpoint is
`.claude/agents/verifier.md`, which the Phase 0 gate (SP_001) **created as a stub** and which the
fan-out brief explicitly assigns to me for **refinement**; the gate is committed and inactive, so
there is no live writer. Isolation is `git-worktree` on `sprint/SP_007-eval`. No
`touches_checklist_items` overlap with any in-progress sprint.

## Prior-Art & Bug-Log Check

No prior `eval/` harness or `test/golden/` set exists (greps clean). No bug-log entries relate to
the eval harness. Prior art reused: the frozen `contracts/` Protocols (driven, never redefined),
`test/conftest.py` (`db` mark + `db_url`/`pg_repo` fixtures), and `PostgresRepository.from_url()`.

## Priority Justification

Agent 6 is the highest-leverage quality defense in the build (SPEC §8): the author-independent
oracle that decides whether the system meets `/goal`. It runs off the critical path (alongside the
build) and grades at integration, so it costs no critical-path time while being the single
strongest guard against a half-built system being passed off as done.

## Review Log

### Pre-Implementation Review

- **Iteration 1** (2026-06-09): architect-reviewer (independent, plan + raw `data/` + contracts) found 1 CRITICAL, 2 HIGH, 2 MEDIUM, 1 LOW. Files reviewed: workspace/sprints/SP_007_eval.md, HELIXPAY_BUILD_SPEC.md §8, helixpay/contracts/query.py, helixpay/contracts/repository.py, helixpay/seed/fixtures.py, data/all-hands-2026-04-15.md, data/board-deck-q1-2026.pdf, data/dashboards/april-2026-kpi-dashboard.html.
- **Iteration 2** (2026-06-09): code-reviewer (independent, plan + harness design) found 0 CRITICAL, 2 HIGH, 3 MEDIUM, 2 LOW. Files reviewed: workspace/sprints/SP_007_eval.md, helixpay/contracts/models.py, helixpay/contracts/repository.py, helixpay/seed/run_seed.py, test/conftest.py, helixpay/seed/metric_vocab.py.

**Resolution — All CRITICAL and HIGH addressed:**

1. **C1 (golden contradiction would be unfindable — wrong oracle).** The SPEC §8 example and the
   gate fixture assume a Q1 **revenue** conflict (dashboard 14.2M vs board-deck 13.9M). Inspection
   of the raw files shows revenue is **14.2M in every source** (results PDF, dashboard, board deck,
   overview, all-hands); the 13.9M is synthetic fixture data. A golden contradiction keyed on
   revenue would make recall un-meetable and the oracle dishonest. **Fix:** key the golden
   contradiction on the **real** planted conflict — the Confluence GA date (June/end-Q2 publicly
   vs end-Q3/September internally), which four independent dated sources support and the board deck
   itself flags. Documented as a top-line finding in `eval/README.md` and the delivery report;
   filed for the fixer as the synthetic fixture conflict should be relabeled, not graded.
2. **H1 (harness importing Agent 3 breaks author-independence).** Importing `helixpay.query` at
   author time would couple the oracle to the gradee. **Fix:** `build_engine` resolves the concrete
   `QueryEngine` lazily at run time and tests inject a `StubEngine`; the harness codes only against
   the `QueryEngine`/`Repository` Protocols.
3. **H2 (image golden fact would unfairly fail recall).** Deep JPEG extraction is a SPEC §11 scope
   cut (caption-level only). **Fix:** image facts carry `recall_bar: false` and are excluded from
   the recall denominator; still reported, informational.

**Deferred (MEDIUM/LOW, non-blocking, tracked):**
- M1 — value matching must be normalization-tolerant (currency/whitespace/`SGD 14.2M` vs `14.2M`):
  implement a `normalize_value` shared by extraction-check matching; covered by a harness test.
- M2 — `as_of` tolerance: golden `as_of` is the **fact's** effective date; a claim whose `as_of`
  is the document/export date may differ. Match on the fact `as_of` but accept the document date as
  a documented fallback; note in README.
- M3 — precision over a golden set is non-standard; define it explicitly (FOUND/(FOUND+MISMATCH))
  and label it "golden-set precision" in output so it isn't read as corpus precision.
- L1 — questions.yaml `checks` vocabulary must be closed and asserted by `test_golden.py` so a typo
  can't silently no-op a check.
- L2 — latency is wall-clock per `ask()`; note it's indicative, not a benchmark.

### Post-Implementation Review

- **Iteration 1** (2026-06-09): code-reviewer (plan-blind, changed code + tests only) found 0 CRITICAL, 1 HIGH, 3 MEDIUM, 2 LOW. Files reviewed: eval/run.py, eval/models.py, test/golden/test_harness.py, test/golden/test_golden.py, test/golden/test_integration.py, test/golden/facts.yaml, eval/questions.yaml.
- **Iteration 2** (2026-06-09): self-review with runtime evidence (live harness run on a seeded pgvector container + injected stub engine; pytest 29 green; mypy eval clean) found 0 CRITICAL/HIGH, 1 MEDIUM, 1 LOW. Files reviewed: eval/run.py, test/golden/test_harness.py.

**Resolution — All CRITICAL and HIGH addressed:**
1. **H-1 (duplicate id could silently mask a fact/question — a wrong oracle).**
   `load_golden`/`load_questions` now raise on a duplicate fact/question id
   (`_assert_unique_ids`); regression test `test_fact_and_question_ids_unique`. A dup id
   would otherwise let two facts share a slot and under-count recall undetectably.

**Resolution — MEDIUM/LOW (addressed or accepted with rationale):**
- M-1 (value-match tolerance: spaced vs compact magnitudes, e.g. `14.2 m` vs `14.2m`):
  fixed `normalize_value` with a magnitude-collapse regex; parametrized test covers
  `SGD 14.2M`/`$14.2 million`/`R$22.0M`. (`"18 months"` vs `"18 mo"` remains a documented
  tolerance gap — acceptable; it reflects an extraction value choice, not an oracle bug.)
- M-2 (`uses_freshest_as_of` is a heuristic — the bundle alone can't prove the answer
  *preferred* the latest): documented in `eval/README.md`; gated only alongside
  `states_as_of` + `as_of_coverage`, so it cannot pass on a bundle with no dates.
- M-3 (mypy `var-annotated` on `_assert_unique_ids`): annotated `seen`/`dups`; mypy clean.
- L-1 (`entity_resolution`/`alias_handling` are coarse — citation presence): intentional;
  the hard alias/resolution test lives in extraction recall (the email `owns` links + the
  two-Marias trap), not in the answer-bundle shape. `alias_handling` is soft (reported,
  not gated). Documented.
- L-2 (latency is indicative wall-clock per `ask()`, not a benchmark): noted in README.

**Runtime evidence captured:** live `eval.run` against the seeded-but-un-ingested fixture
DB reports all 15 bar facts MISSING with precise reasons (e.g. "subject 'HelixPay'
unresolved"), and the stub engine that surfaces a contradiction everywhere correctly FAILS
the two `no_false_contradiction` questions — confirming the honest-oracle guard works. This
also surfaced a real **HIGH finding for the fixer/gate** (filed in `eval/README.md`, not
patched here per author-independence): no `HelixPay` company entity is seeded, so
company-level metric facts are MISSING until extraction creates it or the gate seeds it.
