---
status: living
last-reconciled: 2026-06-13
authoritative-for: [active-sprint, sprint-history]
---

# Progress

> **Note**: Archive to `PROGRESS_ARCHIVE_NNN.md` when this file exceeds 25 sprints.

## Active Sprint

**Current:** SP_031
**Started:** 2026-06-12
**Stage:** Complete — serving-path **production** hardening, landing on the SP_030 CI gate. Five
verified production smells paid down: I1 dev-gateway runs the project interpreter (`_project_python`)
→ retires the 15-entry bypass-log root cause; I2 six `assert row is not None` infra guards →
explicit `raise` (survive `python -O`); I3 corrected the "recursive CTE" docstrings (org subtree is
Python-side); I4 fresh per-`ask()` `resolve_entity` memo (honest scope: dedups variant lookups only;
true N+1 = a deferred frozen-contract `resolve_entities`); I5 `_org_root_id` f-string SQL → shared
`_as_of_filter` helper; I6/D1 audit→`db.audit_queries` layer-break accepted-and-documented
(read-only + census invariants). Plus I7 DB-free `ask()` branch coverage, I8 advisory combined
two-job coverage (`require_report` flip deferred until combined ≥80%; unit-half 85%), and I9 the 3
pre-existing xfailed db tests resolved (D3 stale org-`as_of` expectations rewritten to pin
undated-persists AND dated-IS-filtered; D4 live-detector guards the missing relation). 2 Stage-3
reviews + 1 plan-blind Stage-5 (SHIP). Local: mypy clean, 758 unit passed. DB-dependent edits
verified by the CI `integration` job. **Merge to main left for operator.**

SP_030 — serving-path test/CI hardening (Complete, **merged to main** via PR #4, merge `6bb36c4`).
A DB-free `gateway` job + an `integration` job running the db suite against pgvector. The real
`MCP dispatch → HelixQueryEngine → PostgresRepository` path now runs on every PR + gates deploy;
`HELIXPAY_REQUIRE_DB` kills silent skips. Exposed 3 pre-existing db failures (xfailed) → resolved in
SP_031.

<!-- NOTE: The **Current:** format is required by validate_sprint.py's active sprint detection. -->

SP_028b — LLM contradiction adjudication. `helixpay/ingest/adjudicate.py` +
`scripts/adjudicate_contradictions.py`: a post-ingest, single-writer clear-then-rewrite
pass (runs AFTER `recompute_contradictions.py`) that judges each subject's cluster with one
Opus(temp-0) call — DROPS same-fact-different-words lexical candidates (precision) and ADDS
cross-predicate claim pairs + solid-vs-dotted link pairs (recall), never resolving. Two
labeled blocks (CLAIM/LINK) so a claim↔link pair is structurally impossible; content-hash
cache keyed on `(model, PROMPT_VERSION, NORM_VERSION, member signatures)` with `source_uri`
excluded → re-sweep of an unchanged store is $0; verdict-absent falls back to the SP_028a
deterministic floor (`helixpay/ingest/dedup.py`). All code/unit/db tests are $0 (stub
client); paid Opus is the gated CLI only. `--model` override (Sonnet) + model in the cache
key. Plan: `workspace/sprints/SP_028b_llm_adjudication.md`.

Prior (contradiction precision line): SP_028a — deterministic precision sweep:
`scripts/recompute_contradictions.py` is the canonical single-writer clear-then-rewrite
post-ingest step (cardinality skip + value-pair dedup) — took live `helixpay_full` from
**266 → 115** at $0. SP_028 — plan + Stage-3 review (split into 028a/028b recommended).

Prior (recall + exposure line): SP_019 metric-subject attribution; SP_020 mint-time dedup
(removed the Açaí hardcode, fixed the class at mint); SP_021 structured image/chart
extraction (graded by source); SP_022/SP_023 MCP retrieval + graph/temporal tools (12 tools
on `ExposureEngine`); SP_024 drop-taxonomy gate; SP_025 coercion recovery (entity-collapse
guard); SP_027 de-leak extraction prompt + golden-leak guard.

Prior: SP_016 — Functional live system, gated deploy (Phase A complete; B/C operator-gated).
SP_011 — Provenance Persist (evidence spans + offsets, link `document_id`,
`detect_link_conflicts`, undated seeded reporting edges). SP_013 — eval rigor (Wilson CI,
macro recall, 3-class contradiction) + ingest compute-idempotency. SP_010 — recall fixes +
$0 replay tier + planted Confluence GA contradiction. SP_009 — provenance contracts/schema
v2 + shared `normalize` util. SP_008 — DEV_RULES Reinforcement. SP_001 — Phase 0 Gate.

## Phase 1 Integration

**Branch:** `merge/integration` (off `main` @ SP_008). The six worktree slices
(SP_002–SP_007) merged in dependency order. Two expected conflicts resolved:
`helixpay/ingest/__init__.py` (SP_002+SP_003 add/add → docstring union) and
`PROGRESS.md` (SP_004 → take-main). Real engine wired into the exposure startup
(`helixpay.api.app.wire_engine`, gated on `DATABASE_URL`). Runtime deps
consolidated into one `pyproject.toml` + `helixpay` console script + regenerated
`uv.lock` (DEV_REINFORCE F-2). **Integrated tree: 260 passed / 22 db-skipped,
mypy clean (52 files), 11/11 validators PASS, dev-gateway green via `.venv`.**
Deploy decoupled from full ingest (SP_016 Phase A): `deploy.sh` brings the
app live with the seeded backbone only; the full corpus (44 docs) loads via
`scripts/full_run.py` after the SP_015 gate opens. Phases B + C are
operator-gated (see `workspace/acceptance/SP016_live_verification.md`).

## Sprint History

### SP_024–028 merge gate + production deploy

- **Status**: Complete — **deployed to production main** (`b0d0c7f`)
- **Tier**: governance / release
- **Date**: 2026-06-11
- **Summary**: A 5-agent plan-blind evaluation cleared the SP_024–028b line for merge.
  Three merge-gate fixes: CLAUDE.md trimmed 25,077 → ~18,300 bytes (under the 20k hard limit;
  verbose gotchas archived full-fidelity to `workspace/CLAUDE_GOTCHAS.md`), the missing SP_026
  plan back-filled, and SP_028a's 2nd Stage-5 iteration recorded. `origin/main` had been a
  deliberate net-null SP_023 pin (`696e502` plan-doc checkpoint reverted by `858f539`);
  integrated via a non-destructive `-s ours` merge (nothing lost). CI Deploy-to-Production
  green, live `/health` 200. Deploy is code-only/$0: idempotent migrate (additive
  `links.raw_verb`) + re-seed, no paid ingest; the live 67 contradictions unchanged.

### SP_028b: LLM contradiction adjudication — paid refiner on the SP_028a sweep

- **Status**: Complete
- **Tier**: Foundational (2-iteration Stage-3 review)
- **Date**: 2026-06-11
- **Summary**: `helixpay/ingest/adjudicate.py` + `scripts/adjudicate_contradictions.py` — a
  post-ingest single-writer clear-then-rewrite pass (after `recompute_contradictions.py`)
  judging each subject's cluster with one Opus(temp-0) call: DROPS same-fact-different-words
  lexical candidates (precision), ADDS cross-predicate claim pairs + solid-vs-dotted link
  pairs (recall), never resolving (schema has no winner field). Two labeled blocks
  (CLAIM `C1..Cn` / LINK `L1..Lm`) make a claim↔link pair structurally impossible;
  signature-sorted members keep the index map stable across re-seed id churn. Content-hash
  cache keyed on `(model, PROMPT_VERSION, NORM_VERSION, member signatures)` with `source_uri`
  excluded → re-sweep of an unchanged store is $0. Verdict-absent → SP_028a deterministic
  floor (`helixpay/ingest/dedup.py`); present-but-empty is authoritative. `--model` override
  (Sonnet) with the model in the cache key; `MAX_CLUSTER_MEMBERS=40` (oversized subjects fall
  to the floor and are logged). Prompt uses only synthetic (year-2099) values so the SP_027
  leak guard stays green. All code/unit/db tests are $0 (stub client); paid Opus is the gated
  CLI only.
- **Deploy outcome (2026-06-11)**: ran the paid sweep with **Sonnet** (operator choice; model
  rides in the cache key) on live `helixpay_full` — **115 → 67 contradictions**, oracle recall
  **1/8 → 2/8** (cross-predicate `maria-santos-dual-line` caught; baseline floor preserved).
  Merged to production main at the SP_024–028 merge gate.

### SP_028a: deterministic contradiction precision sweep — 266 → 115 at $0

- **Status**: Complete
- **Tier**: Foundational
- **Date**: 2026-06-11
- **Summary**: `scripts/recompute_contradictions.py` — the canonical single-writer
  clear-then-rewrite post-ingest sweep that produces the deployed contradiction set (took
  live `helixpay_full` from **266 → 115** at $0). Two deterministic precision levers via a
  thin `_DedupWriter` (no change to `detect()`): (1) cardinality skip for predicates
  explicitly `set_valued` in `predicate_cardinality.py` (claims loop only; links keep their
  single-valued gate; unknown/functional/breakdown all KEEP); (2) value-pair dedup — one row
  per distinct normalized value-pair / to-entity pair. Normalizer sign-fix
  (`normalize.py` step 6b) so `-SGD 2.1M` parses like `SGD -2.1M`. SP_028 (parent) was the
  plan + Stage-3 review that recommended the 028a/028b split.

### SP_027: de-leak extraction prompt — synthetic examples + golden-leak guard

- **Status**: Complete
- **Tier**: Standard
- **Date**: 2026-06-11
- **Summary**: SP_019/021/026 prompt surgery had built few-shot examples from real graded
  corpus facts (15 golden bar-fact values + 3 graded subjects), coaching the extractor with
  answers it is later graded on (DEV_RULES §12). Replaced every example with synthetic,
  year-shifted (2027) subjects/values teaching the identical shape, and added
  `test/unit/ingest/test_prompts.py` — loads golden bar-fact values AND subjects, allowlists
  only `{HelixPay, HelixPay SEA, HelixPay Brasil}`, and word-boundary-scans every
  `prompts/*.md`. De-leak only affects FUTURE extractions; the existing `helixpay_full` DB /
  `.replay-cache` were recorded under the leaked prompt, so a paid re-record is needed to
  learn the true uncoached recall.

### SP_024 / SP_025: drop-taxonomy gate + coercion recovery

- **Status**: Complete — **deployed to production** at the SP_024–028 merge gate
- **Tier**: Standard (SP_024) / Foundational (SP_025)
- **Date**: 2026-06-11
- **Summary**: SP_024 — drop-taxonomy gate making extraction loss auditable. SP_025 —
  coercion recovery with a CRITICAL entity-collapse guard (recovers coercible items without
  silently merging distinct entities; additive nullable `links.raw_verb`, out of the natural
  key). Both Complete and plan-blind reviewed. The earlier deploy hold (concurrent-agent path
  collision + CLAUDE.md size limit) was lifted at the merge gate; the SP_025 schema is
  additive/nullable/out-of-key (safe on live `helixpay_full`) and the entity-collapse guard is
  bidirectionally test-pinned.

### SP_022 / SP_023: MCP retrieval + graph/temporal tools

- **Status**: Complete
- **Tier**: Foundational
- **Date**: 2026-06-11
- **Summary**: 12 MCP tools = 4 frozen `QueryEngine` + 8 optional on `ExposureEngine` /
  `HelixQueryEngine`, discovered by `_retrieval` `getattr` (additive, pure-read). SP_022 —
  `search` / `fetch` / `get_sources` / `list_entities` (provenance by chunk id, document-date
  `source_as_of`). SP_023 — `get_timeline` / `get_relationships` / `list_metrics` /
  `get_claims_by_predicate` (+`MetricVocab`; canonicalize-match in the db layer; `get_links`
  incoming via `to_entity_id`; `get_timeline` reuses `subject_id` with claim-period
  `source_as_of`).

### SP_021: structured image/chart extraction — graded by source

- **Status**: Complete
- **Tier**: Standard
- **Date**: 2026-06-11
- **Summary**: Image vision pass (`helixpay/ingest/loaders/image.py`) transcribes each chart series and its
  per-period values (actual vs plan); `extract_claims.md` maps a region series → one
  `revenue` claim per region/period (regions stay distinct, never collapsed onto HelixPay).
  An image-sourced golden fact is FOUND only if the satisfying claim carries the image
  `source_uri` — proving the image was extracted. `HelixPay SEA` is minted at ingest. The $0
  replay cache predates this prompt, so only a paid single-image re-extraction validates the
  image facts. `test/golden/facts.yaml` is the master oracle; smoke/sample subsets are
  generated, never hand-edited.

### SP_019 / SP_020: extraction attribution + mint-time entity resolution

- **Status**: Complete
- **Tier**: Standard
- **Date**: 2026-06-10 (SP_019) / 2026-06-11 (SP_020)
- **Summary**: SP_019 — `ingest/repair.py` re-attributes known company metrics to the seeded
  company before resolution (milestone predicates excluded, regional metrics left distinct);
  re-record raised golden recall 4/11 → 7/11 (64%). SP_020 — fixed the two-subject-type
  duplicate at MINT time (`resolve_mention` snaps an open-class mention to an existing
  same-name row when one side is the catch-all `other`), removing SP_010's per-account Açaí
  hardcode so the link resolves at ingest for every account with no seed.

### SP_018: RDD/SRP refactor — separate domain logic from I/O

- **Status**: Complete
- **Date**: 2026-06-10
- **Summary**: Behavior-preserving SRP split driven by a `/my-rdd-review` audit. Extracted
  pure domain logic out of three I/O-mixed hot spots into four new pure modules:
  `query/citations.py` (citation resolve/dedup/confidence, out of `synthesis.enforce_citations`),
  `ingest/extract/validate.py` + `glean.py` (per-item coerce/validate/loss-accounting and
  gleaning dedup, out of `ChunkExtractor`), and `ingest/assemble.py` (claim/link build +
  same-source supersession decision, out of `pipeline`). Also fixed `.validators.yml`
  `module_size.source_roots` (was `[src,scripts,skills]` — scanned nothing; now `[helixpay,
  scripts]`) so the GL-RDD size sensor actually scans the codebase. No contract/schema/DB
  change. Plan-blind review: no CRITICAL, no behavior change.
- **Tests added**: +40 (test_citations 12, test_glean 8, test_validate 6, test_assemble 14);
  560 unit passing, mypy clean, module-size sensor clean over 83 files.

### SP_002–SP_007: HelixPay Phase 1 six-agent fan-out

- **Status**: Complete (integrated on `merge/integration`)
- **Date**: 2026-06-10
- **Summary**: SP_002 source loaders (8 formats); SP_003 extraction/embedding/
  contradiction/resolution pipeline; SP_004 query+ask engine (cited, contradiction-
  surfacing); SP_005 exposure (FastAPI + streamable-HTTP MCP + CLI); SP_006 infra
  (Docker/compose/Makefile/deploy, live DNS+TLS); SP_007 eval/ground-truth harness.
- **Tests added**: 260 passing on the integrated tree (22 db-gated skips).

### SP_001: Phase 0 Gate

- **Status**: Complete
- **Date**: 2026-06-09
- **Summary**: Froze the shared substrate — contracts, schema, Repository, config,
  seed roster + metric_vocab, query fixture. Schema applies on pgvector pg16; seed
  loads 12 metrics / 63 entities / 99 links; mypy clean.
- **Tests added**: +38

### SP_016: Functional live system — gated deploy (Phase A)

- **Status**: Phase A code complete; Phases B+C pending operator smoke
- **Date**: 2026-06-10
- **Summary**: Deploy decoupled from full ingest; CI/CD deploy job wired;
  `verify_mcp.py` MCP verifier; `prod_seed.sh` production seed transfer;
  infra contract tests extended; meta-docs reconciled (Rule 16).
  Phases B (full run) + C (live eval) are operator-gated.
  Acceptance template: `workspace/acceptance/SP016_live_verification.md`.
- **Tests added**: +16 (infra contract extensions + test_verify_mcp + test_prod_seed)

### SP_008: DEV_RULES Reinforcement

- **Status**: Complete
- **Date**: 2026-06-09
- **Summary**: Implemented DEV_REINFORCE findings — status advisory, orphan-worktree
  WI-4, declared-deps field + validator + consolidation script, package-root
  scaffolding, env pin, integration-as-owned-phase.
- **Tests added**: +13 validator tests

<!-- Example:
### SP_130: Workout Tracking Foundation

- **Status**: Complete
- **Date**: 2026-03-28
- **Summary**: Exercise logging with 3-tier fuzzy matching, category-specific PR detection, muscle group recency suggestions with 48h cooldown
- **Tests added**: +208 new tests (5,867 total)

### SP_129: Knowledge Briefing Relevance Fix

- **Status**: Complete
- **Date**: 2026-03-25
- **Summary**: Added `expected_outcome` to `InitiativeItem`; fixed BM25 data truncation that caused empty knowledge sections in briefings
- **Tests added**: +7 new tests (5,659 total)

### SP_105: Thesis to Hypothesis Full Rename

- **Status**: Complete
- **Date**: 2026-01-10
- **Summary**: Renamed all thesis references to hypothesis across database tables, domain models, services, and tests
- **Tests added**: +0 (rename only)
-->
