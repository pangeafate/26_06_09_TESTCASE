# Review Protocol & Gap Analysis

_Multi-iteration self-critique framework for self-developing agent projects_

**Version**: 1.0
**Status**: Active Development Guidelines

---

## Philosophy

Self-developing agents suffer from confirmation bias: the context that wrote the code is predisposed to believe it is correct. This framework enforces separation between builder and reviewer, requiring fresh contexts for all review work. The goal is not perfection -- it is catching the bugs that the builder cannot see.

## Core Rule: Builder/Reviewer Isolation

**The context that wrote code must NOT be the same context that reviews it.**

This is a hard rule, not a suggestion. Confirmation bias is measurable and significant in LLM outputs: a model evaluating its own work consistently rates it higher and catches fewer bugs than a fresh context evaluating the same work.

### How to Enforce Isolation

- **Multi-agent setups**: Use dedicated sub-agents for review work. The builder agent triggers review agents with task descriptions that do not include the builder's reasoning.
- **Single-agent setups**: Create explicit context breaks. Save all work to disk, start a fresh session, and load only the artifacts (code + tests) without the builder's chain of thought.
- **Minimum requirement**: The reviewer must not have access to the sprint plan's rationale section during post-implementation review. They review code and tests on their own merits.

## Review Iteration Floor (Authoritative)

**This section is the single authoritative source for the minimum number of
review iterations.** The Stage 3 and Stage 5 "minimum iterations" statements
below, the `tier` floor in `adapters/CLAUDE.md`/`adapters/AGENTS.md`, and the
`validate_sprint.py` enforcement all derive from this table — do not encode a
different floor elsewhere.

The floor scales with the sprint's declared `tier` (frontmatter field, see
`adapters/AGENTS.md`):

| Tier | Minimum iterations (Stage 3 and Stage 5 each) | Maximum |
|---|---|---|
| `Micro` | 1 | 5 |
| `Standard` | 2 | 5 |
| `Foundational` | 2 | 5 |
| _unspecified / unrecognized_ | 2 (fail-safe) | 5 |

A sprint with no declared `tier` is held to the strong floor of 2 — the floor
only relaxes when a sprint explicitly declares `tier: Micro`.

### Why Micro may drop to 1 — and the compensating guard

The value of a 2-iteration floor is that it forces a **second independent
context**: the bias guard from Builder/Reviewer Isolation. A single iteration
loses that second context, so for `Micro` sprints the lone iteration **must
name its independent reviewer** with an explicit `Reviewer:` annotation (in
addition to the usual severity finding and `Files reviewed:` annotation):

```
- **Iteration 1** (2026-06-09): architect-reviewer found 0 CRITICAL/HIGH, 1 LOW. Files reviewed: src/lib/foo.py. Reviewer: architect-reviewer
```

Without the `Reviewer:` annotation a Micro single-iteration review is
indistinguishable from a builder rubber-stamping their own work, so
`validate_sprint.py` rejects it. Standard/Foundational sprints already satisfy
the second-context requirement through their 2-iteration floor and do not need
the annotation.

## Stage 3: Pre-Implementation Review

### When

After writing and saving a sprint plan, BEFORE starting implementation.

### Purpose

Catch architectural mistakes, incorrect assumptions about the existing codebase, scope creep, and missing edge cases while changes are still cheap (editing a plan vs. rewriting code).

### Process

Run the tier's minimum review iterations in parallel (see **Review Iteration Floor** above — 2 for Standard/Foundational, 1 for Micro). Continue until **0 CRITICAL or HIGH issues** remain.

#### Reviewer 1: Architect-Reviewer

**Lens**: System-level thinking. Does this plan fit the existing architecture?

**Evaluation criteria:**
- Architecture risks: Does the plan introduce unnecessary coupling, violate layer boundaries, or create circular dependencies?
- Backward compatibility: Will existing functionality break? Are migration steps needed?
- Deployment ordering: Can the changes be deployed incrementally, or is it all-or-nothing?
- Scope creep: Does the plan include work beyond its stated goal?
- TDD compliance: Does the testing strategy cover the stated scope? Are edge cases identified?
- Performance: Will new code paths introduce latency, memory pressure, or scaling issues?
- Missing edge cases: What happens with empty inputs, null values, concurrent access, partial failures?

**Severity ranking:**
- **CRITICAL**: Will cause data loss, security breach, or system failure
- **HIGH**: Will cause incorrect behavior or require follow-up sprint to fix
- **MEDIUM**: Suboptimal but functional; technical debt
- **LOW**: Style, naming, documentation improvements

**Required input**: Full sprint plan + all source files referenced in the plan.

#### Reviewer 2: Code-Reviewer

**Lens**: Practical implementation. Are the plan's claims factually correct?

**Evaluation criteria:**
- Do referenced functions, classes, and methods actually exist in the codebase?
- Are function signatures (parameter names, types, return types) accurate?
- Are field names, enum values, and constants spelled correctly?
- Do referenced files exist at the stated paths?
- Are import paths valid?
- Does the plan's description of existing behavior match the actual code?
- Are there issues the architect-reviewer missed?

**Required input**: Full sprint plan + all source files referenced in the plan.

#### Reviewer 3: Main Agent (optional)

In multi-agent setups, the main agent can serve as a third reviewer, bringing domain knowledge that dedicated reviewers may lack. In single-agent setups, skip this -- the main agent IS the builder, violating isolation.

### Consolidation

After all reviewers complete:

1. Merge findings, deduplicating overlapping issues
2. Address all CRITICAL issues immediately (update the plan)
3. Address all HIGH issues (update the plan)
4. Log MEDIUM/LOW issues in the plan's "Known Limitations" or "Future Work" section
5. If any CRITICAL issues were found, re-run review on the updated plan (only the changed sections need re-review)
6. Save the updated plan to disk before proceeding to implementation

## Stage 5: Post-Implementation Review (Gap Analysis)

### When

After all tests pass and BEFORE deploying or pushing to version control.

### Purpose

Find logical gaps, missing edge cases, inconsistencies between modules, broken cross-references, and untested paths that survived implementation.

### Process

Run the tier's minimum iterations (see **Review Iteration Floor** above — 2 for Standard/Foundational, 1 for Micro), up to **5 maximum**. Stop early ONLY if an iteration finds **zero issues**.

#### Iteration Structure

Each iteration uses **2-3 reviewers sequentially** (not in parallel -- each reviewer builds on the previous one's findings). Each reviewer operates in a fresh context.

#### CRITICAL RULE: No Sprint Plan Access

Post-implementation reviewers must **NEVER see the sprint plan**. They receive only:
- The new/modified source files
- The new/modified test files
- A neutral prompt: "Review these files for bugs, logical gaps, missing edge cases, and inconsistencies."

**Why**: The sprint plan explains the builder's intent. A reviewer who reads it will unconsciously evaluate the code against the plan's description rather than against objective correctness. This is the primary source of confirmation bias in code review.

#### Review Checklist

Each iteration must check:

| Category | What to Verify |
|---|---|
| Enum/schema sync | Do enum values match database schema options? Are all values handled in switch/match statements? |
| Model/schema coverage | Do model fields cover all database columns? Are optional vs required fields correct? |
| Import paths | Do all imports resolve? Are there circular imports? |
| CLI argument handling | Are all arguments validated? Are defaults sensible? Is help text accurate? |
| Service logic | Are all code paths reachable? Are early returns correct? Do loops terminate? |
| Error path coverage | Is every `except`/`catch` block tested? Do error messages include context? |
| Cross-module contracts | Do function signatures match between caller and callee? Are return types consistent? |
| Test quality | Do tests actually assert meaningful behavior? Are mocks correctly configured? Do test names describe what they verify? |
| Edge cases | Empty collections, null/None values, boundary values, concurrent access, partial failures |

#### Fixing Issues

When a reviewer finds an issue:

1. Fix the code or test
2. Re-run the full test suite
3. If tests fail, fix until green
4. Continue the current iteration (do not restart)

#### Iteration Outcomes

- **0 issues found**: Stop. The code is ready for deployment.
- **Issues found, all fixed**: Proceed to next iteration with fresh reviewer context.
- **Iteration 5 still has CRITICAL or HIGH issues**: BLOCK deployment. Report to human operator with a summary of unresolved issues. Do not push code with known critical defects.

### Severity Definitions for Gap Analysis

| Severity | Definition | Action |
|---|---|---|
| CRITICAL | Data corruption, security vulnerability, crash in normal operation | Block until fixed |
| HIGH | Incorrect behavior in realistic scenario, missing validation that could corrupt state | Block until fixed |
| MEDIUM | Incorrect behavior in unlikely scenario, missing optimization, poor error message | Fix if time permits, otherwise log as tech debt |
| LOW | Style, naming, documentation, minor test improvement | Log for future sprint |

## Review Templates

### Pre-Implementation Review Prompt (for Architect-Reviewer)

```
Review this sprint plan for architecture risks, backward compatibility,
deployment ordering, scope creep, TDD compliance, missing edge cases,
and performance concerns.

Read the sprint plan FULLY, then read every source file it references.
Rank issues by severity: CRITICAL / HIGH / MEDIUM / LOW.

Be harsh. Your job is to find problems, not confirm the plan is good.

Sprint plan: [path]
Referenced files: [list of paths]
```

### Pre-Implementation Review Prompt (for Code-Reviewer)

```
Verify the factual claims in this sprint plan against the actual codebase.
Check that referenced functions, field names, signatures, file paths,
and behavioral descriptions actually exist and are accurate.

Find issues the architect-reviewer missed. Focus on practical
implementation details.

Read the sprint plan FULLY, then read every source file it references.
Rank issues by severity: CRITICAL / HIGH / MEDIUM / LOW.

Sprint plan: [path]
Referenced files: [list of paths]
```

### Post-Implementation Review Prompt (for Gap Analysis Reviewers)

```
Review these files for bugs, logical gaps, missing edge cases,
inconsistencies between modules, broken cross-references, and untested
paths.

Check: enum/schema sync, model/schema field coverage, import paths,
CLI arg handling, service logic correctness, test coverage for error
paths, and cross-module contract consistency.

DO NOT ask for or read the sprint plan. Evaluate the code and tests
on their own merits.

Files to review: [list of new/modified source and test files]
```

## Iteration Tracking

For transparency and auditability, log review iterations:

```markdown
## Review Log: SP_XXX

### Pre-Implementation Review
- **Iteration 1** (YYYY-MM-DD): Architect found 2 HIGH, 1 MEDIUM. Code-reviewer found 1 CRITICAL, 1 HIGH.
- **Consolidation**: Fixed 1 CRITICAL + 3 HIGH. 1 MEDIUM logged as future work.
- **Iteration 2** (YYYY-MM-DD): Re-review of changed sections. 0 CRITICAL/HIGH. Proceeding.

### Post-Implementation Review
- **Iteration 1**: Found 3 issues (1 HIGH, 2 MEDIUM). Fixed all, tests green.
- **Iteration 2**: Found 1 issue (1 LOW). Logged for future sprint.
- **Iteration 3**: 0 issues. Clean. Proceeding to deploy.
```

## Summary

| Stage | When | Min Iterations | Stop Condition | Reviewer Access |
|---|---|---|---|---|
| Pre-implementation (Stage 3) | After plan, before code | 2 | 0 CRITICAL/HIGH | Full sprint plan + source files |
| Post-implementation (Stage 5) | After tests pass, before deploy | 2 (max 5) | 0 issues in single iteration | Code + tests ONLY (no sprint plan) |

---

_This framework ensures that self-developing agents do not grade their own homework. Fresh contexts catch what the builder cannot see._
