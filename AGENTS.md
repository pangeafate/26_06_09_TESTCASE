# Coding Agent Behavioral Rules

This file is a project-neutral adapter for coding agents. It connects the
methodology in `practices/` with executable skills in `skills/dev-*`.

Every skill has a `SKILL.md` with exact commands and parameters. Read the
relevant `SKILL.md` before using a skill for the first time.

---

## Repository Contract

If a project also provides a primary rulebook such as `CLAUDE.md`, this file is
an adapter, not a competing process. Follow the stricter rule whenever two
instructions overlap.

Operationally:

1. Read the primary rulebook before planning, editing, reviewing,
   documenting, validating, committing, pushing, deploying, or touching host
   resources.
2. Treat omitted rules as still active when they exist in the primary
   rulebook.
3. Record meaningful rule conflicts in the sprint plan or delivery report.
4. Do not treat a direct user request as permission to skip lifecycle gates,
   validators, collision rules, deployment rules, or host isolation rules.

Generic tool mappings:

- Use `python3` for repository validators and scripts.
- Use explicit path edits and explicit path staging.
- Use progress updates for execution tracking.
- Use isolated reviewers or fresh review contexts for quality gates.
- Prefer CI/CD-first deployment; direct host access is emergency-only or
  read-only reconnaissance unless the project rulebook says otherwise.

---

## Multi-Agent Collision Prevention

Before touching production code, tests, scripts, meta-docs, sprint plans, or
deployment files, check active claims.

Mandatory pre-work checks:

1. List active sprint claims:
   ```bash
   find workspace/sprints -name 'SP_*.md' -exec sh -c \
     'for f do if grep -q "status: In Progress" "$f"; then echo "--- $f ---"; grep -E "touches_paths|touches_checklist_items" "$f"; fi; done' sh {} +
   ```
2. Read matching sprint frontmatter before choosing scope.
3. If intended `touches_checklist_items` overlaps another active sprint, stop
   and coordinate or choose disjoint work.
4. Treat `touches_paths` overlap as a collision warning even when validators
   allow it.
5. If untracked files exist in the area you are about to touch, assume another
   agent owns them until proven otherwise.
6. Check the agent inbox for the sprint you intend to work on:
   ```bash
   ./scripts/agent-message.sh check SP_NNN
   ```
   Resolve open entries in the same sprint, or explicitly acknowledge and
   defer them in the commit or delivery report.

Forbidden sweep operations:

- `git add -A`, `git add .`, `git add -u`, `git add --all`
- `git stash -u`, `git stash --include-untracked`
- `git clean -f`, `git clean -fd`, `git clean -fdx`
- `git reset --hard`
- `git checkout -- .`, `git restore .`

Staging and committing rules:

- Stage explicit file paths only.
- Commit sprint plans first for production code, database schema, external
  integration, new capabilities, or host-touching work.
- Do not commit files outside the sprint's declared `touches_paths` unless the
  plan or bypass log explains the cross-sprint reason.
- If bypassing a hook is unavoidable, record a one-line justification in the
  project bypass log and include it with the bypassing commit.
- Before pushing deployable changes, run the full validator suite.

Parallel work is allowed only when checklist items and write paths are
disjoint, or when branch/worktree isolation plus explicit coordination makes
ownership clear. When more than one sprint is `In Progress` at once, declare how
this sprint stays isolated in its frontmatter `isolation` field
(`read-only` | `shared-tree` | `branch-only` | `git-worktree`) and set `branch`
(and `worktree` for `git-worktree`) accordingly. Strict-tier
(Standard/Foundational/unspecified) code sprints that share the main working
tree and overlap on `touches_paths` are rejected by
`validators/validate_worktree_isolation.py`; move them to a dedicated worktree
or branch. The authoritative rules and naming conventions
(`sprint/SP_XXX-<slug>` branches, `.claude/worktrees/SP_XXX` worktrees) live in
`practices/GL-PARALLEL-ISOLATION.md`.

---

## Task Lifecycle

When operating on file-dispatched tasks, poll for new tasks on every incoming
message and heartbeat:

```bash
python3 skills/dev-deploy/scripts/poll-tasks.py --tasks-dir tasks
```

If a `tasks/TASK_*.md` file exists and is selected:

1. Change `Status: NEW` to `Status: IN_PROGRESS`.
2. Execute the development lifecycle below.
3. On success, change status to `DELIVERED` and write a delivery report.
4. On failure, change status to `FAILED` and write a failure report.

Process only one file-dispatched task at a time.

Direct user requests are valid work. For direct requests, apply the same gates
minus task-file status and delivery mechanics unless the project rulebook
allows a docs-only or self-improvement shortcut.

---

## Development Lifecycle

### Stage 1 - Recognition

Read the task or direct request. Determine whether it changes code,
configuration, schema, external integrations, host resources, skills, tests, or
documentation only.

Before deciding scope:

- Read the primary rulebook.
- Check the roadmap and active sprint state.
- Run active-claim discovery.
- Check the target sprint inbox.
- Search for prior art before adding new modules, scripts, functions, tables,
  events, tunables, or skills.
- Search the bug log before work that could repeat known failures.

### Stage 2 - Sprint Planning

Use `skills/dev-sprint` to create a sprint plan, then fill in:

- Current state
- Desired end state
- Technical approach
- Testing strategy
- Success criteria
- Critical path or direct blocker
- Collision check
- Priority justification
- Prior-art and bug-log check
- Scenario coverage plan when dispatch behavior changes
- Behavioral closure plan when fixing operator-observable behavior

Sprint frontmatter must include:

- `tier`
- `touches_paths`
- `touches_checklist_items`
- `isolation` when another sprint is `In Progress` in parallel (with `branch`,
  and `worktree` for `git-worktree`) — see `practices/GL-PARALLEL-ISOLATION.md`
- `fix_type` when closing an operator-observable bug
- `followup_for_patch` when `fix_type` is `patch` or `mitigation`
- `clones_from` when using a precedent clone

Update `PROGRESS.md` with the active sprint and save the plan before
implementation.

### Stage 3 - Plan Review

Run independent architecture and code review passes over the plan and
referenced files. Findings must be ranked `CRITICAL`, `HIGH`, `MEDIUM`, or
`LOW`. Address all `CRITICAL` and `HIGH` findings and iterate until the tier
minimum is satisfied.

Review-log entries must name the reviewer, exact files reviewed, and severity
counts. Do not add performative entries.

### Pre-Implementation Gate

Before writing code, run:

```bash
python3 validators/validate_sprint.py <project-root> --gate pre-impl
```

If it fails, fix the plan or review log first.

### Stage 4 - Implementation

Follow test-driven development:

1. Write a failing test.
2. Write minimal code to pass.
3. Refactor while keeping tests green.
4. Repeat.

### Stage 5 - Post-Implementation Review

Run plan-blind review over only the changed code and tests. Do not include the
sprint plan in Stage 5 review context. Fix blocking findings, rerun tests, and
iterate until the tier minimum is satisfied.

### Stage 6 - Documentation

Update every meta-doc whose subject changed. Reconcile sprint frontmatter and
run documentation validators:

```bash
python3 scripts/reconcile-sprint-frontmatter.py .
python3 validators/validate_doc_reality.py .
python3 validators/validate_doc_freshness.py .
```

Deployment is blocked until doc validators pass.

### Stage 7 - Deployment and Delivery

Run the local development gateway:

```bash
python3 scripts/dev-gateway.py . --stage manual
```

Then stage explicit paths, commit with the sprint id when applicable, push or
open a PR, and watch CI/deploy checks. Fix mechanical failures autonomously.

### Stage 8 - Behavioral Closure

For operator-observable fixes, replay the original trigger after deployment or
record an explicit pending operator-smoke status with exact reproduction steps.

---

## Review Protocol

Prefer isolated sub-agent review when the environment supports it. Otherwise
use single-agent review with an explicit context break and compensate with
additional iterations.

Stage 3 reviewers see the plan. Stage 5 reviewers see only code and tests.

Useful reviewer roles:

- `architect-reviewer`
- `code-reviewer`
- `debugger`
- `security-auditor`
- `performance-reviewer`

---

## Self-Improvement Rules

Autonomous, low-risk changes:

- Workspace memory and validator config updates
- Development tooling improvements
- Documentation clarifications

Full lifecycle required:

- Production code changes
- Database schema changes
- External service integrations
- New skills or capabilities

After any autonomous change, append a one-line entry to the self-improvement
log.
