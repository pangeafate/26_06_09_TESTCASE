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

### Gotchas (one-liners; full rationale in `workspace/CLAUDE_GOTCHAS.md` — append both places)
- **pgvector** needs `CREATE EXTENSION vector;` before the schema (migration does it first).
- An **expression uniqueness key** (e.g. `COALESCE(as_of,…)`) must be `CREATE UNIQUE INDEX`, never a table-level `UNIQUE(...)` (Postgres syntax error).
- `migrate.py` runs schema **statement-by-statement** → keep `schema.sql` free of dollar-quoted bodies (comment-strip + `;` split).
- **MCP** must run streamable-HTTP, not stdio (stdio is local-only, breaks the live URL).
- **HTML dashboards:** capture the number **and** its as-of date — that's where contradictions hide.
- **Idempotency:** ingest on `content_hash`, seed/`add_claim` on natural keys — re-running unchanged data is a no-op.
- **Metric-as-subject (SP_019):** `helixpay/ingest/repair.py` re-attributes known **company** metrics to the seeded company pre-resolution; `ga_target`/`completion_target` excluded (project/product domain); regional metrics stay distinct.
- **Dashboard `as_of` ≠ metric `as_of` (SP_019):** a "Q1 2026 Revenue" card is `as_of` the **quarter end**, not the dashboard header date. A baked-wrong cached `as_of` is fixable **only** by a paid re-record.
- **Dual-type mint (SP_010→SP_020):** an account tagged both `customer` and `other` mints two rows → ambiguous → links drop. `resolve_mention` snaps an open-class mention onto a same-name row when one side is catch-all `other` (`_other_compatible`). Guards: 2+-row tie → `None`; two *specific* distinct types never bridge; seeded persons (two Marias) non-creatable.
- **Replay from a subdir needs `PYTHONPATH=/app` (SP_020):** `python -m helixpay.ingest.replay` from `/app/eval/smoke` imports the **baked** `helixpay`, not your edit, unless `PYTHONPATH=/app` (+ `HELIXPAY_PROMPTS_DIR=/app/prompts` for prompts).
- **`METRIC_VOCAB` ↔ `repair._NON_COMPANY_KEYS` lock-step (SP_010):** a new vocab key whose subject isn't the company must also go in `_NON_COMPANY_KEYS`, or `repair_metric_subject` mis-attributes it onto `HelixPay`.
- **$0 replay runs from `eval/smoke/` (SP_010):** the cache keys on `source_uri`; run with CWD `eval/smoke` (9-doc subset) so URIs match. `replay` mode is genuinely $0 (`_ConstantEmbedder` + `ReplayExtractor`); `--record` re-embeds via Voyage (not $0).
- **Image facts graded by SOURCE (SP_021):** an image-sourced golden fact is FOUND only if the satisfying claim carries the **image `source_uri`** (`run.py:_check_claim_fact`); the same value in text won't satisfy it. Line reads are approximate — grade only **text-corroborated** datapoints; keep the period-end ISO on the caption **header line only** ("first ISO wins"); `HelixPay SEA` is **minted** at ingest.
- **`test/golden/facts.yaml` is the MASTER oracle (SP_021):** `eval/smoke/facts.yaml` + `eval/sample/facts.yaml` are GENERATED — edit master, re-run `eval.smoke.build_smoke`/`eval.sample.build_sample`, never hand-edit. The sample manifest excludes the image (image facts land in smoke only).
- **Seeded `reports_to`/`dotted_line_to` edges are undated (SP_011):** `as_of=None` so the export-dated `org-chart.md` edge doesn't dedupe away on the links natural key. A DB seeded *before* this must be re-seeded fresh.
- **Recompute sweep is the canonical post-ingest contradiction step (SP_028a):** `scripts/recompute_contradictions.py` is the single-writer clear-then-rewrite (266→115 at $0) — cardinality-skip (`predicate_cardinality.py` set-valued preds) on the CLAIM loop only + value-pair dedup (`helixpay/ingest/dedup.py` `DedupWriter`). **Do NOT** add date/rounding equivalence to shared `normalize.py` (8 callers incl. the eval matcher — `2026-05-12 ≡ May 12` drops the year, suppressing real cross-year conflicts).
- **LLM adjudication = the PAID refiner on the sweep (SP_028b):** `helixpay/ingest/adjudicate.py` + `scripts/adjudicate_contradictions.py`, run AFTER recompute. Two-block clusters (CLAIM `C1..Cn` + LINK `L1..Lm`); content-hash cache keyed on model+PROMPT_VERSION+NORM_VERSION+sorted sigs (no ids, no `source_uri`) → $0 re-run; verdict-absent → deterministic floor, present-but-empty → authoritative. Prompt uses synthetic 2099 values (SP_027 guard). Live (Sonnet): 115→67, oracle 1/8→2/8; 6 misses are entity-fragmented → SP_029.
- **Extraction prompt de-leak + guard (SP_027):** earlier prompts coached the extractor with real graded golden values/subjects (DEV_RULES §12). `prompts/*.md` now use **synthetic** examples; `test/unit/ingest/test_prompts.py` word-boundary-scans for leaks (allowlist only `{HelixPay, HelixPay SEA, HelixPay Brasil}`). Only future extractions change — the existing DB/cache need a paid re-record to learn true recall.
- **MCP tools live on `ExposureEngine`, not frozen `QueryEngine` (SP_022/SP_023):** 12 = 4 frozen + 8 optional, found by `_retrieval` `getattr` (`QueryEngine`-only → `{available:false}`). `get_claims_by_predicate` canonicalize-matches in the **db layer** (period-strip `regexp_replace`, no POSIX `\b`).
- **Drop taxonomy gate (SP_024, eval-only):** `ledger.py` splits drops into **LOSSY** vs **INTENTIONAL**; `check_smoke.py:doc_verdict` gates on `lossy_drops` only. Fail-safe: unknown reason ⇒ LOSSY (by *exclusion* from `INTENTIONAL_DROP_REASONS`, never an allow-list). `ungrounded` is RESERVED.
- **Coercion recovery + entity-collapse guard (SP_025, schema):** out-of-vocab `subject_type`→`other`, verb→`mentions`+ additive nullable **`links.raw_verb`** (OUT of the natural key → first-verb-wins). CRITICAL: the `other` fallback fed the SP_020 snap → a file/repo named like a product could collapse onto it. Fix: `helixpay/ingest/extract/coerce.py` sets transient `ClaimOut.raw_subject_type`; fallback subjects resolve with `allow_snap=False` (pipeline: `allow_snap=claim_out.raw_subject_type is None`). SP_020 genuine snap preserved; a fallback named exactly like a SEEDED `other` still attaches (test-pinned).
- **Comparator + extraction robustness (SP_026):** `normalize.py` strips letter-bearing annotation parens in the **numeric path only** (accounting negatives preserved) so "same number, different annotation" isn't a contradiction; `helixpay/ingest/extract/llm.py` `_MAX_TOKENS 8192→16384` (truncation-drop fix). SP_026 shipped without a Stage-2 plan (rationale in `research/contradiction-recall-and-extraction-delta.md`; stub back-filled at the merge gate); its `raw_verb` INSERT predates the `ALTER` column → that commit isn't independently bisectable (harmless at HEAD).
- **Extraction-quality audit (SP_029, read-only):** `python -m helixpay.audit` / `make audit` is the integrity/precision census the golden recall oracle can't give — provenance chain, grounding, resolution honesty, planted traps, suspicious-oversampled sample; read-only by construction, advisory (NOT a CI gate; `--strict` opt-in). Evidence grounding is **3-way** (`helixpay/audit/invariants.py` `evidence_grounding`): byte-exact→clean, casefold+whitespace-only→**WARN `evidence_not_verbatim`**, absent-even-normalized→**ERROR `evidence_not_in_chunk`**; pinned to case+ws ONLY (never shared `ingest.normalize`) so a wrong digit can't launder to WARN, offset-ERROR gated to the byte-exact path. Producer tech-debt it surfaces: `pipeline.py` stores the model's evidence quote (not the located raw span) + `grounding.locate_span` tolerates case/ws with raw offsets → ~136 live claims non-byte-verbatim with NO penalty/column; the WARN is the only signal (close-the-loop = future paid re-record). Traps are fixture-calibrated: `no_false_revenue_contradiction` is INFORMATIONAL on the full corpus.
- **Serving-path hardening (SP_031; full detail in `workspace/CLAUDE_GOTCHAS.md`):** dev-gateway runs the **project** interpreter (`_project_python`), not ambient `python3`. `ask()` memoizes `resolve_entity` in a **fresh per-call** dict (NEVER instance-level → stale-`None` leak); dedups only variant terms — true N+1 needs a frozen `resolve_entities`. **Audit→`db.audit_queries` is an INTENTIONAL layer-break**, ONLY read-only + census. **Undated** SP_011 org edges have no lower bound → visible under any `as_of` (never filter them). CI coverage is **advisory**; the 80% `require_report` flip waits for combined ≥80%.
