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

> PLACEHOLDER. The orchestrator's Phase 0 gate fills this section in before
> fanning out to the build agents, per `HELIXPAY_BUILD_SPEC.md` §7. Do not start
> the parallel build until it is written. Target contents:
>
> - **Stack & commands:** Python 3.12, uv; Postgres + pgvector; FastAPI; MCP
>   Python SDK (streamable-HTTP). `make up | ingest | demo | test | fmt`.
> - **Conventions:** cross-module types live in `helixpay/contracts/` and are
>   never redefined locally; all DB access goes through `Repository` (no raw SQL
>   outside `db/`); secrets only from env; models — extraction =
>   `claude-sonnet-4-6`, synthesis/`ask` = `claude-opus-4-8`, embeddings = voyage
>   (1024d); every LLM call uses a named prompt in `prompts/` + a structured-output
>   schema with validate-and-repair.
> - **Ontology rules:** never collapse conflicting facts — store every value as a
>   Claim (source + as_of + confidence); contradictions are first-class rows,
>   surfaced never silently resolved; never delete superseded facts (set
>   `valid_to` / `superseded_by`); entity resolution matches the seeded roster
>   first; predicates canonicalize via `metric_vocab`; `ask()` output has zero
>   uncited claims.
> - **Gotchas:** pgvector needs `CREATE EXTENSION vector;` before migrations; MCP
>   must run streamable-HTTP not stdio; HTML dashboards — capture the number AND
>   its as-of date; ingestion is idempotent on `content_hash`.
