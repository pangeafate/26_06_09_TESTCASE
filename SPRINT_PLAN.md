---
sprint_id: SP_XXX
features: []
user_stories: []
schema_touched: false
structure_touched: false
status: Planning
isolation: shared-tree
branch: ""
worktree: ""
agent_owner: ""
dependencies: []
dev_dependencies: []
---
<!-- Template: fill in the frontmatter (sprint_id, features, user_stories,
     schema_touched, structure_touched, status) and the sections below.
     Replace values in the frontmatter when you copy this template.

     DEPENDENCIES (validate_declared_deps.py + scripts/consolidate-deps.py —
     DEV_REINFORCE F-2). Do NOT edit pyproject.toml mid-sprint (parallel agents
     appending to one [project.dependencies] block conflict on every merge).
     Instead declare the third-party packages this sprint adds here, as inline
     lists; the orchestrator unions them into pyproject.toml at integration via
     `scripts/consolidate-deps.py`:
       dependencies:     runtime packages, e.g. [anthropic>=0.40, voyageai>=0.3]
       dev_dependencies: dev/test-only packages, e.g. [pytest>=8, ruff]
     A code-owning sprint must declare `dependencies` (use `[]` for none) — the
     failure mode F-2 prevents is *silence*, not emptiness.

     Sprint plans carry frontmatter for validate_doc_freshness.py Stage F-1.
     workspace/sprints/ is EXCLUDED from validate_doc_reality.py Stage C's
     frontmatter manifest because sprint-plan `status` uses a different enum
     (Planning | In Progress | Complete | Abandoned) than meta-docs.

     PARALLEL-AGENT ISOLATION (validate_worktree_isolation.py — authoritative
     rules in practices/GL-PARALLEL-ISOLATION.md). When more than one sprint is
     `In Progress` at once, declare HOW this sprint stays isolated from its
     peers:
       isolation:
         read-only    — analysis/docs only, no code writes (exempt from checks)
         shared-tree  — main working tree, no dedicated branch (the default;
                        fine for solo or fully-disjoint Micro work)
         branch-only  — a distinct branch in a separate checkout (no worktree)
         git-worktree — a dedicated git worktree on a dedicated branch
                        (`claude --worktree`; the preferred mode for parallel
                        Standard/Foundational work)
       branch:      required for branch-only / git-worktree.
                    Convention: `sprint/SP_XXX-<slug>`.
       worktree:    required for git-worktree. Convention: `.claude/worktrees/SP_XXX`.
       agent_owner: the agent/session that holds this working tree (optional).
     Leave isolation: shared-tree (and the others blank) for single-stream work
     — that is the historical, backward-compatible default. -->

# SP_XXX: [Sprint Name]

## Sprint Goal

[One to two sentences describing what this sprint delivers and why it matters.]

<!-- Example:
Implement a recurring task engine that automatically generates the next instance of a recurring task when the current one completes. This eliminates manual re-creation of repetitive tasks.
-->

## Current State

[Describe what exists today. Reference specific files, functions, or behaviors.]

<!-- Example:
Tasks can be created and completed but have no recurrence concept. Users must manually create a new task each time a repeated activity comes up. The `task_domain.py` has `TaskStatus` enum but no recurrence fields.
-->

## Desired End State

[Describe exactly what the system looks like after this sprint. Be concrete — mention new files, new behaviors, new fields.]

<!-- Example:
- Tasks have an optional `recurrence_rule` field (daily/weekly/monthly/custom)
- When a recurring task reaches `done` status, `generate_next_instance()` creates the next occurrence
- New instances inherit title, priority, and owner from the parent; get a fresh due date
- The `stale_immune` flag is auto-set on generated instances
- A new `recurring_task_service.py` handles generation logic
-->

## What We're NOT Doing

[Explicitly list what is out of scope for this sprint to prevent scope creep.]

<!-- Example:
- No UI for configuring recurrence rules (CLI/API only)
- No calendar integration for due date calculation
- No batch generation of future instances (only next-one-at-a-time)
-->

## Technical Approach

[Step-by-step description of how to implement the feature. Reference specific modules, functions, and patterns.]

<!-- Example:
1. Add `recurrence_rule` and `recurrence_parent_id` fields to `task_domain.py`
2. Create `recurring_task_domain.py` with `RecurrenceRule` enum and `calculate_next_due_date()`
3. Create `recurring_task_service.py` with `generate_next_instance()` — reads parent task, creates child
4. Hook into existing `update_task_status()` in `task_service.py` — trigger generation on status=done
5. Add `stale_immune=True` to generated instances
-->

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| [path] | [Create / Modify] | [What changes] |

<!-- Example:
| `src/lib/recurring_task_domain.py` | Create | RecurrenceRule enum, calculate_next_due_date() |
| `src/lib/recurring_task_service.py` | Create | generate_next_instance(), query_recurring_tasks() |
| `src/lib/task_domain.py` | Modify | Add recurrence_rule, recurrence_parent_id fields |
| `src/lib/task_service.py` | Modify | Hook generation into status update |
| `test/unit/test_recurring_task_domain.py` | Create | Tests for recurrence calculation |
| `test/unit/test_recurring_task_service.py` | Create | Tests for instance generation |
-->

## Testing Strategy

[Describe what tests will be written and the approach — TDD red/green/refactor.]

<!-- Example:
Following GL-TDD.md:

1. **Domain tests first**: Test `calculate_next_due_date()` for daily/weekly/monthly rules, edge cases (month-end, leap year)
2. **Service tests**: Test `generate_next_instance()` with mocked database API calls — verify field inheritance, stale_immune flag, due date calculation
3. **Integration path**: Test status update hook triggers generation (mock at service boundary)
4. **Edge cases**: No recurrence rule (skip), already-generated next instance (dedup), cancelled parent (no generation)
-->

## Success Criteria

- [ ] [Criterion 1 — specific and verifiable]
- [ ] [Criterion 2]
- [ ] [Criterion 3]
- [ ] All new code has passing tests
- [ ] All existing tests still pass
- [ ] PROGRESS.md updated
- [ ] PROJECT_ROADMAP.md updated (if milestone completed)

### Doc Reconciliation Checklist

Complete at Stage 6 (Documentation). Tick each meta-doc whose subject matter this sprint touched.

- [ ] `FEATURE_LIST.md` — feature statuses, sprint numbers, implementation paths
- [ ] `PROJECT_ROADMAP.md` — milestone status for touched phases
- [ ] `ARCHITECTURE.md` — only if system design changed
- [ ] `DATA_SCHEMA.md` — only if schema changed
- [ ] `CODEBASE_STRUCTURE.md` — only if directories/files moved
- [ ] `USER_STORIES.md` — if acceptance criteria were satisfied
- [ ] `last-reconciled` bumped on each touched meta-doc
- [ ] `python validators/validate_doc_reality.py <project_root>` returns 0
- [ ] `python validators/validate_doc_freshness.py <project_root>` returns 0 (writes `.docs_reconciled` lockfile)
- [ ] `.docs_reconciled` lockfile present at project root naming the current sprint

<!-- Example:
- [ ] `generate_next_instance()` creates a child task with correct fields
- [ ] Due date advances correctly for daily, weekly, and monthly rules
- [ ] `stale_immune` is auto-set to True on generated instances
- [ ] Duplicate generation is prevented (idempotency)
- [ ] All new code has passing tests
- [ ] All existing tests still pass
- [ ] PROGRESS.md updated
-->

## Review Log

### Pre-Implementation Review
- **Iteration 1** ([DATE]): [Reviewer] found [N] [SEVERITY]. Files reviewed: [file1, file2]
- **Iteration 2** ([DATE]): [Reviewer] found [N] issues. Files reviewed: [file1, file2]

**Resolution — All CRITICAL and HIGH addressed:**
1. **C-1 ([short identifier])**: [What was wrong] → [What was changed and why]
2. **H-1 ([short identifier])**: [What was wrong] → [What was changed and why]

<!-- Example (this is the format validate_sprint.py expects — each iteration is a bullet):
### Pre-Implementation Review
- **Iteration 1** (2026-01-01): architect-reviewer found 1 CRITICAL, 2 HIGH, 1 MEDIUM. Files reviewed: sprint plan, src/lib/service.py, src/models/entity.py
- **Iteration 2** (2026-01-02): code-reviewer found 0 CRITICAL/HIGH. Files reviewed: sprint plan, src/lib/service.py

**Resolution — All CRITICAL and HIGH addressed:**
1. **C-1 (missing input validation)**: Service accepted unbounded input → Added max-length check with 413 response
2. **H-1 (no retry on transient failure)**: API call failed permanently on timeout → Added exponential backoff with 3 retries
3. **H-2 (test gap)**: Happy path only → Added error-path tests for validation and retry
-->

### Post-Implementation Review
- **Iteration 1** ([DATE]): Found [N] [SEVERITY] issues. Files reviewed: [file1, file2]
- **Iteration 2** ([DATE]): Found [N] issues. Files reviewed: [file1, file2]

**Resolution — All CRITICAL and HIGH addressed:**
1. **C-1 ([short identifier])**: [What was wrong] → [What was changed and why]
2. **H-1 ([short identifier])**: [What was wrong] → [What was changed and why]

<!-- Example:
### Post-Implementation Review
- **Iteration 1** (2026-01-03): debugger found 1 HIGH issue. Files reviewed: src/lib/service.py, test/unit/test_service.py
- **Iteration 2** (2026-01-04): code-reviewer found 0 issues. Files reviewed: src/lib/service.py (clean iteration — ready to deploy)

**Resolution — All CRITICAL and HIGH addressed:**
1. **H-1 (silent data loss)**: Column mismatch returned empty string instead of error → Raises ValueError with diagnostic message
-->
