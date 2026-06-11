# CLAUDE.md — HelixPay Ontology (Primary Rulebook)

This is the **primary rulebook** for the HelixPay Ontology build. It is loaded on
every session. It has two parts:

1. **Governance** (below) — the DEV_RULES seven-stage lifecycle, wired in before
   development. These rules are mandatory and govern every slice of the build.
   `AGENTS.md` is the coding-agent adapter over the same methodology; on any
   overlap, follow the **stricter** rule.
2. **HelixPay Project Conventions** (bottom section) — stack, ontology rules, and
   gotchas. **Authored at the gate (Phase 0)** per `HELIXPAY_BUILD_SPEC.md` §7,
   before any extraction code is written. Until the gate runs, the placeholder
   stands.

Build orchestration (the gate + five build agents + the Eval/ground-truth agent,
worktree isolation, adversarial verification, `/goal` finish) is specified in
`HELIXPAY_BUILD_SPEC.md`. That spec and this rulebook are complementary: the spec
says *what to build and in what order*; this rulebook says *how every agent must
work while building it*.

Practice details live in `practices/GL-*.md`; validators in `validators/`;
lifecycle scripts in `scripts/`. Read the relevant `practices/GL-*.md` and any
skill's `SKILL.md` before first use.

---


This is a project-neutral rulebook for self-developing coding agents. It is
intended to be copied into a repository and tightened with project-specific
deployment, security, and domain rules.

Every rule is mandatory unless a higher-priority instruction explicitly says
otherwise.

---

## Operating Model

The agent works in seven stages:

1. Task recognition
2. Sprint planning
3. Plan review
4. Implementation
5. Post-implementation review
6. Documentation
7. Deployment and delivery

An eighth behavioral-closure stage applies to operator-observable bug fixes.

Do not skip lifecycle gates. A direct user request changes priority; it does
not remove validators, collision checks, review requirements, documentation
updates, or deployment verification.

---

## Tiers

Tiers adjust review effort; they never relax safety rules.

- `Precedent-Clone`: repeats a recently completed sprint with the same write
  path, data shape, failure modes, tier, and file structure.
- `Micro`: one to three small, additive items on a precedented path.
- `Standard`: four to ten items or one new runtime seam.
- `Foundational`: substrate, authorization, cross-tenant, schema, or
  high-blast-radius work.

Batch only when every item shares the same write path, data shape, failure
mode, and tier.

If Stage 3 review expands `touches_paths` by more than 50 percent or adds
unlisted files, stop and split or re-plan.

---

## Core Rules

### 1. Test-Driven Development

No production code before a failing test. Follow `practices/GL-TDD.md`.

### 2. Documentation-First Design

Document interfaces before implementing them. Split modules when complexity,
imports, parameters, or responsibilities exceed the thresholds in
`practices/GL-RDD.md`.

### 3. Error Handling and Logging

Use structured severity, category, and exit-code conventions. Never swallow
exceptions and never log secrets. See `practices/GL-ERROR-LOGGING.md`.

### 4. Layer Boundaries

Dependencies flow inward:

Capabilities -> shared logic -> models

Infrastructure remains standalone. Models do not import capabilities, and
shared logic does not depend on infrastructure adapters.

### 5. Context Isolation

Quality review must be independent. Builders do not rubber-stamp their own
work. Stage 5 reviewers see only code and tests, never the plan.

Any `CRITICAL` finding must be verified against runtime or test evidence
before accepting or dismissing it.

### 6. Pre-Feature Discipline

Before planning a feature:

- Check active sprint claims.
- Check the sprint inbox.
- Search the roadmap and existing code for prior art.
- Reuse existing substrate where it fits.
- Search the bug log for related failures.

Sprint plans must include `touches_paths` and `touches_checklist_items`.
Checklist overlap blocks parallel work. Path overlap requires coordination.

When sprints run in parallel, declare an `isolation` mode (`read-only`,
`shared-tree`, `branch-only`, or `git-worktree`) per
`practices/GL-PARALLEL-ISOLATION.md`. Strict-tier code sprints that share the
main working tree and overlap on paths must move to a dedicated worktree or
branch; `validators/validate_worktree_isolation.py` enforces this.

### 7. Documentation Reconciliation

Update only the meta-docs whose subject changed. Reconcile sprint frontmatter
before doc validators. Do not hand-bump untouched docs.

### 8. Plan Review

Run architect and code review over the plan before implementation. The review
iteration floor scales with `tier` per the authoritative table in
`practices/GL-SELF-CRITIQUE.md`: Standard and Foundational work requires at
least two iterations; `Micro` work may use one, but that lone iteration must
name its independent reviewer (`Reviewer:` annotation). Hard-stop at iteration
five if `CRITICAL` or `HIGH` findings remain.

### 9. Post-Implementation Review

Run plan-blind review over changed code and tests after tests pass and before
documentation/deployment. Fix blocking findings and rerun tests.

### 10. Sprint Plan Persistence

Plans live on disk before implementation. After context loss, re-read the plan
before resuming.

### 11. CI/CD-First Deployment

Deploy through version control and CI by default. Direct host access is
emergency-only or read-only reconnaissance unless the project rulebook names a
specific exception.

After pushing to a deployment branch, watch CI and deployment checks until the
pushed commit is either verified or an actionable blocker is known.

### 12. Version-Controlled Workspace

If a workspace artifact matters, keep it in git: memory, rulebooks, validator
config, sprint plans, progress, and documentation.

### 13. Pre-Deploy Validation

Run the local development gateway before pushing or deployment. A failing
gateway step blocks delivery. Use individual validators only as diagnostics.

### 14. External Tool Isolation

Use dedicated sub-agents or isolated contexts for high-noise external tool
work. Keep the main implementation context focused.

### 15. Self-Improvement Scope

No approval is needed for workspace documentation, validator configuration, or
development-tooling clarifications. Production code, schema, external
integrations, and new capabilities require the full lifecycle.

### 16. Deploy Gate

Stage 6 documentation comes before Stage 7 deployment. Do not deploy what has
not been documented and reconciled.

### 17. Critical-Path Priority

Operator-observable bugs in the primary user workflow pre-empt lower-priority
governance, polish, and cleanup work unless the operator explicitly overrides.

### 18. Skill Design

Skills are system-level contracts consumed by agents. Tool handlers must not
branch on string-literal caller identity. Prefer schema-generic substrate and
data-driven authorization policy over per-agent or per-table tool forks.

### 19. Scenario-First Dispatch Changes

Dispatch-affecting changes require matching scenario coverage or an auditable
bypass.

### 20. Bug Log Discipline

Before work that could repeat known failures, search the bug log, cite matches
or explicit no-match, deduplicate new bugs, and update lifecycle state during
documentation.

### 21. Behavioral Closure

A sprint with `fix_type` is not complete until the original operator symptom
has been replayed against the deployed or approved test system, or explicitly
recorded as pending operator smoke with exact steps.

---

## Required Commands

Common gates:

```bash
python3 scripts/dev-gateway.py . --stage manual
python3 validators/validate_sprint.py . --gate pre-impl
python3 scripts/reconcile-sprint-frontmatter.py .
python3 validators/validate_doc_reality.py .
python3 validators/validate_doc_freshness.py .
python3 validators/run_all.py .
```

Active-claim scan:

```bash
find workspace/sprints -name 'SP_*.md' -exec sh -c \
  'for f do if grep -q "status: In Progress" "$f"; then echo "--- $f ---"; grep -E "touches_paths|touches_checklist_items" "$f"; fi; done' sh {} +
```

---

## Commit Discipline

- Stage explicit paths only.
- Commit plans before code for non-trivial work.
- Keep commits within declared `touches_paths`.
- Record any hook bypass with a reason.
- Never use sweep staging or destructive working-tree cleanup while other
  agents may have untracked work.

---

## HelixPay Project Conventions (authored at the gate — SPEC §7)

> Authored by the Phase 0 gate (SP_001) after freezing the substrate. These bind
> every build agent. On overlap with the governance rules above, the stricter rule
> wins.

### Stack & commands
- Python 3.12+ (3.13 in the local toolchain), `uv` for envs/installs. Postgres +
  `pgvector` (image `pgvector/pgvector:pg16`). FastAPI. MCP Python SDK over
  **streamable-HTTP** (never stdio — stdio is local-only and breaks the live URL).
- `make up | ingest | demo | test | fmt` (Makefile is Agent 5's deliverable). Until
  it lands: `uv run python -m helixpay.db.migrate` applies the schema and
  `uv run python -m helixpay.seed.run_seed` loads the deterministic backbone.
- Tests live under `test/unit/**` and `test/integration/**`. DB tests are marked
  `db` and auto-skip unless `DATABASE_URL` is set. Run `uv run pytest test` and
  `uv run mypy helixpay` before any PR.

### Conventions
- **Cross-module types live in `helixpay/contracts/` and are never redefined
  locally.** Import them: `from helixpay.contracts import Claim, Repository, …`.
  The four Protocols (`SourceConnector`, `Repository`, `QueryEngine`) + models are
  **frozen** — propose a contract change, don't fork the type.
- **All DB access goes through `Repository`. No raw SQL outside `helixpay/db/`.**
  The one implementation is `helixpay.db.repository.PostgresRepository`.
- **Secrets only from env:** `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`, `DATABASE_URL`
  (via `helixpay.config`). Never hardcode; never log a secret or a connection string.
- **Models:** extraction = `claude-sonnet-4-6`; synthesis/`ask` = `claude-opus-4-8`;
  embeddings = voyage, **1024-dim** (pinned in `helixpay.config`).
- Every LLM call uses a **named prompt in `prompts/`** + a **structured-output
  schema validated against the contracts**, with validate-and-repair-or-drop. No
  free-form trust.
- **Embedding/tsv ownership:** the ingest pipeline computes Voyage embeddings and
  passes them to `Repository.add_chunks(chunks, embeddings)`; the lexical `tsv` is a
  DB-**generated** column — never compute or insert it from Python.

### Ontology rules (the point of the project)
- **Never collapse conflicting facts.** Every value is a `Claim` (source + `as_of`
  + confidence). Conflicting claims coexist.
- **Contradictions are first-class rows**, surfaced in answers, never silently
  resolved. `AnswerBundle.contradictions` is present-and-empty, never hidden.
- **Never delete superseded facts** — set `valid_to` / `superseded_by` via
  `Repository.supersede_claim(...)`.
- **Entity resolution matches the seeded roster first.** `resolve_entity(name,
  entity_type=None, context=None)`; an ambiguous bare name with no resolving
  `context` returns `None` (never a silent pick — that's how the two Marias / two
  Tans stay distinct). Org reporting is `reports_to`; functional dotted-lines are a
  distinct `dotted_line_to` link.
- **Predicates canonicalize via `metric_vocab`** (`canonical_predicate` returns the
  input unchanged when unknown; never raises). `"annual recurring revenue"` and
  `"ARR"` must land on the same key or contradiction detection silently no-ops.
- **`ask()` output has zero uncited claims.**

### Gotchas (append every time Claude trips)
- pgvector needs `CREATE EXTENSION vector;` before the schema (the migration does it
  first).
- A uniqueness key containing an expression (e.g. `COALESCE(as_of, …)`) must be a
  `CREATE UNIQUE INDEX`, **not** a table-level `UNIQUE (...)` constraint — the latter
  is a syntax error in Postgres. (Cost us a freeze re-run on `links`.)
- `migrate.py` applies the schema **statement-by-statement** (psycopg executes one
  command per `execute()`); keep `schema.sql` free of dollar-quoted bodies so the
  comment-strip + `;` split stays correct.
- MCP must run streamable-HTTP, not stdio, or it only works locally.
- HTML dashboards: capture the number **and** its as-of date — that's where
  contradictions hide (the planted Q1 revenue/ARR conflict).
- Ingestion is idempotent on `content_hash`; re-running on unchanged data is a
  no-op. Seeding and `add_claim` are idempotent on their natural keys, so re-seeding
  is safe.
- **Metric-as-subject (SP_019):** the extractor sometimes stores a dashboard KPI with the
  *metric* as the claim subject (`metric|Q1 2026 Revenue`) instead of the company, so the value
  is unfindable as "HelixPay's revenue". `helixpay/ingest/repair.py` re-attributes known
  **company** metrics to the seeded company before resolution; milestone predicates
  (`ga_target`/`completion_target`) are deliberately **excluded** (their domain is a project/
  product, e.g. Project Confluence's GA), and regional metrics (`HelixPay Brasil revenue`) are
  left distinct so they never falsely merge into the company.
- **Dashboard `as_of` is NOT the metric's `as_of` (SP_019):** a "Q1 2026 Revenue" card is
  `as_of` the **quarter end** (2026-03-31), even if the dashboard header says "As of
  2026-04-21". The grader (`eval/run.py`) matches the value's reporting period — a baked-wrong
  as_of in the extraction cache can **only** be fixed by a re-record, never by post-processing
  (this is why the deterministic attribution fixes don't move golden recall at $0).
- **A named account mentioned with two subject_types mints a duplicate (SP_010 → SP_020):** an
  external account (e.g. `Açaí Express SP`) tagged both `customer` and `other` mints **two**
  unseeded rows → its bare name is ambiguous → an `owns`-link endpoint resolves to `None` and the
  link is **dropped** at ingest. SP_010 worked around it by *seeding the account* (a per-account
  hardcode); **SP_020 removed that hardcode and fixed the class at MINT time**: `resolve_mention`
  snaps an open-class mention to an existing same-name row when **one side is the catch-all
  `other`** (`_other_compatible`), so the duplicate is never created and the link resolves at
  ingest — for *every* account, no seed. Guards: `resolve_entity` returns `None` on a 2+-row tie
  (never snaps across an existing dup); two *specific* distinct types are never bridged; seeded
  persons (two Marias) are non-creatable and never reach the snap. (Pre-existing cross-run dupes
  in a long-lived DB are out of scope — that's the only case a post-ingest merge would add.)
- **The replay/seed CLI from `eval/smoke/` uses the BAKED image code unless `PYTHONPATH=/app` is
  set (SP_020):** with the host repo mounted at `/app`, `python -m helixpay.ingest.replay …` run
  with CWD `/app/eval/smoke` imports the **installed** (baked) `helixpay`, NOT your edited
  `/app/helixpay`, because `-m` puts the CWD (not `/app`) on `sys.path`. A resolution/pipeline
  code change then silently does nothing on replay. Always pass `PYTHONPATH=/app` (and
  `HELIXPAY_PROMPTS_DIR=/app/prompts` for prompt changes) on any host-mounted run from a subdir.
  `run_seed` from `-w /app` is unaffected (CWD `/app` is already on the path).
- **Adding a `METRIC_VOCAB` key silently widens `repair.KNOWN_KEYS` (SP_010 final-mile):**
  `repair.py` builds `KNOWN_KEYS` as *every* vocab key minus `_NON_COMPANY_KEYS`. A new key whose
  subject is NOT the company (e.g. `top_contributor`, a repo attribute) must be added to
  `_NON_COMPANY_KEYS` too, or `repair_metric_subject` will re-attribute a metric-typed claim
  canonicalizing to it onto `HelixPay`. Keep the two in lock-step.
- **The $0 replay must run from `eval/smoke/` (SP_010 final-mile):** the replay cache keys on the
  `source_uri` string. `python -m helixpay.ingest.replay replay data` from the repo root walks the
  **full** corpus (source_uri `data/all-hands…` → cache miss on non-smoke docs). Run it with CWD
  `eval/smoke` (where `data/` is the 9-doc smoke subset) so source_uris match the cache the smoke
  harness recorded. `replay` mode uses a `_ConstantEmbedder` (no Voyage) and `ReplayExtractor`
  (raises on miss) → genuinely $0; `run_smoke.py --record` is NOT $0 (it re-embeds via Voyage).
- **Image/chart extraction is structured now, but graded by SOURCE (SP_021):** the image vision pass
  (`helixpay/ingest/loaders/image.py` `_CAPTION_PROMPT`, still Sonnet) transcribes each chart **series** and its
  per-period values (actual vs plan via solid/dashed), and `extract_claims.md`'s "Charts & figures"
  section maps a region series → one `revenue` claim per region/period (`subject = HelixPay <Region>`;
  regions stay distinct, never collapsed onto `HelixPay`). A golden fact sourced to the jpeg is only
  FOUND if the satisfying claim **carries the image `source_uri`** (`run.py:_check_claim_fact`
  source-match) — the same value present in text (e.g. Brasil 4.8M in the interview) will NOT satisfy
  an image fact. That is the *feature*: an image-sourced recall-bar fact proves the image was
  extracted. Three traps: (1) **line-chart reads are approximate** — grade only **text-corroborated**
  datapoints (Brasil 4.8M ↔ interview golden; SEA 9.4M ↔ 14.2 total−4.8), and a `9.40`/`9.3` read
  MISSES under `normalize_value` (trailing zero ≠ substring) — an honest fidelity signal, never
  re-rig the prompt with the answer. (2) **doc `as_of` is "first ISO wins"** (`extract_iso_date`): keep
  the period-end ISO date on the caption's **header line only**, not on per-series lines, or an early
  quarter (Q1'25) becomes the doc as_of. (3) **the $0 replay cache predates this prompt**, so it reports
  the image facts MISSING — only a **paid single-image re-extraction** validates them; `HelixPay SEA` is
  **minted** at ingest (not seeded), so confirm exactly one `HelixPay SEA` row after the run.
- **`test/golden/facts.yaml` is the MASTER oracle; `eval/smoke/facts.yaml` + `eval/sample/facts.yaml`
  are GENERATED (SP_021):** edit the master, then re-run `python -m eval.smoke.build_smoke` (and
  `eval.sample.build_sample`) — never hand-edit the generated subsets (they carry "do not hand-edit"
  banners). The smoke builder filters by `manifest.py` source_uris; the **sample** manifest does NOT
  include the image, so image facts only land in smoke. A guard (`test/golden/test_golden.py`) pins the
  image **caption** fact to `recall_bar:false` while allowing structured datapoint facts to be graded.
- Seeded `reports_to`/`dotted_line_to` edges are **undated** (`as_of=None`, SP_011) so the export-dated
  `org-chart.md` edge doesn't dedupe away on the links natural key (`COALESCE(as_of,'0001-01-01')`). A DB
  seeded *before* this must be **re-seeded fresh** (changing `as_of` changes the key → a re-seed adds an
  undated twin, not a no-op). Fresh `make up && seed` unaffected.
- **The extraction prompt was leaking ground truth, and a guard now blocks it (SP_027):** SP_019's
  "re-record prompt surgery" (and later SP_021/SP_026) built few-shot examples from **real graded
  corpus facts** — `extract_claims.md` literally showed the model `HelixPay revenue SGD 14.2M @
  2026-03-31`, `Project Confluence → ga_target → end of Q3 2026`, `412` net-new merchants,
  `Sara Wijaya → helixpay/core top_contributor`, etc. (15 golden bar-fact values + 3 graded
  subjects). That coaches the extractor with answers it's later graded on (DEV_RULES §12), so the
  recall number can't be trusted. SP_027 replaced every example with **synthetic** subjects/values
  (year-shifted to 2027, fictional `Project Atlas`/`Ledger migration`/`acme/core`/`J. Okafor`) that
  teach the identical shape, and added `test/unit/ingest/test_prompts.py::
  test_golden_values_and_subjects_do_not_leak_into_prompts` — it loads `eval.run.load_golden`
  bar-fact **values AND subjects**, allowlists only the structural `{HelixPay, HelixPay SEA,
  HelixPay Brasil}`, and word-boundary-scans every `prompts/*.md`. Removing the
  `Confluence platform → Project Confluence` hint is safe: `seed/roster.py` already seeds those
  surface aliases, so canonicalization lives in the seed, not the prompt. **The de-leak only
  changes FUTURE extractions; the existing `helixpay_full` DB / `.replay-cache` were recorded under
  the leaked prompt, so a paid re-record is required to learn the true uncoached recall.**
- **MCP tools live on `ExposureEngine`, NOT frozen `QueryEngine` (SP_022/SP_023):** 12 = 4 frozen + 8
  optional on `ExposureEngine`+`HelixQueryEngine`, found by `_retrieval` `getattr` (`QueryEngine`-only →
  `{available:false}`); additive pure-read `Repository` reads (SP_009). SP_022:
  `search`/`fetch`/`get_sources`/`list_entities` (`search.source_as_of`=**document** date, provenance by
  chunk id not zip; `fetch`=full text, bad id→`found:false`). SP_023:
  `get_timeline`/`get_relationships`/`list_metrics`/`get_claims_by_predicate` (+`MetricVocab`; `get_links`
  +`to_entity_id`=incoming). `get_claims_by_predicate` canonicalize-matches in the **db layer** (alias set
  + period-strip `regexp_replace` `[[:space:]/-]+`; no POSIX `\b`, so `*` over-strips glued
  `"fy2026 ebitda"`→`"ebitda"`). `get_timeline` reuses via `subject_id`; `source_as_of`=**claim** period.
