# Context Restoration & Management

_Strategies for maintaining continuity across context resets in self-developing agent projects_

**Version**: 1.0
**Status**: Active Development Guidelines

---

## Philosophy

Self-developing agents operate under a fundamental constraint: their working memory is finite and ephemeral. Context windows fill up, sessions end, and compaction events discard reasoning chains. The agent's ability to continue meaningful work after these interruptions depends entirely on what was persisted to disk before the interruption occurred.

Context management is not a convenience -- it is a survival mechanism. An agent without context management will:
- Repeat work already completed
- Make decisions that contradict earlier decisions
- Lose track of partially completed multi-step operations
- Drift from the sprint plan's scope and intent

## Core Rules

### Rule 1: Sprint Plans Saved Before Implementation

The sprint plan must be written to disk as a file BEFORE any implementation begins.

**Why**: If context is lost during implementation, the sprint plan file is the agent's primary recovery artifact. An in-memory-only plan disappears on compaction or session end.

**Enforcement**: This is a hard prerequisite in the sprint lifecycle (GL-SPRINT-DISCIPLINE.md). No code is written until the plan file exists on disk.

### Rule 2: Re-Read Sprint Plan After Any Context Loss

After any of these events, the FIRST action is to re-read the sprint plan file:

- Context compaction (the platform's mechanism for freeing context window space)
- Session restart or new session
- Long pause between actions (> 30 minutes)
- Explicit instruction from human to "continue" or "resume"

**How**: Read the full sprint plan file from disk. Do not rely on summary memories or abbreviated notes.

**Why**: The sprint plan contains the complete specification: what to build, what approach to take, what files to modify, what tests to write, and what success looks like. Partial recall produces partial implementation.

### Mid-Session Context Compaction

When the agent platform compresses or truncates the conversation history mid-session (common in long implementation sessions), the agent must:

1. **Stop current work immediately** — do not continue coding from partial memory
2. Re-read the active sprint plan file from disk (it was saved before implementation began)
3. Re-read MEMORY.md for cross-session state
4. Re-read PROGRESS.md for active sprint confirmation
5. Assess current stage: compare what the sprint plan says should be done vs what files exist on disk (run validators to detect current state)
6. Resume from the identified stage — do not restart from Stage 1

The sprint plan file is the authoritative context anchor. If the agent's memory of what it was doing conflicts with what the sprint plan says, trust the sprint plan.

**Signs of context compaction:**
- The agent cannot recall earlier conversation turns
- The agent asks about decisions that were already made
- The agent proposes changes that were already implemented
- The agent repeats a review iteration that was already completed

Recovery takes priority over speed. A 2-minute re-read prevents hours of re-work from a corrupted context state.

### Rule 3: Sprint Plan Is the Authoritative Context Anchor

When there is ambiguity about what to do next, the sprint plan is the source of truth -- not memory, not conversation history, not previous reasoning.

If the sprint plan and the agent's memory disagree:
- The sprint plan wins
- If the plan appears to be wrong (based on new information discovered during implementation), update the plan file first, then proceed

### Rule 4: Sub-Agents Receive Complete Task Descriptions

When spawning sub-agents (reviewers, specialized workers, debugging agents), provide them with:

- The complete task description (what to do and what to produce)
- All file paths they need to read
- Any constraints or requirements

Do NOT provide:
- References to "the previous conversation"
- Assumptions about what the sub-agent already knows
- Abbreviated instructions that depend on context the sub-agent lacks

**Why**: Sub-agents have no prior context. They start with an empty context window. Every piece of information they need must be explicitly provided.

### Rule 5: Persist Intermediate State for Long-Running Tasks

Tasks that span multiple steps (multi-file implementations, iterative reviews, complex migrations) must persist intermediate state to disk.

**Mechanisms:**

| Approach | When to Use | Example |
|---|---|---|
| Checklist in sprint plan | Sequential tasks with clear steps | `- [x] Create domain model`, `- [ ] Create service layer` |
| Status file | Complex multi-phase operations | `workspace/sprints/SP_XXX_status.json` |
| Test results | Implementation progress | Passing tests = completed functionality |
| Git commits | Logical checkpoints | Commit after each completed sub-feature |

**The key insight**: If the agent loses context mid-task, it should be able to determine what is already done by examining the filesystem and test results -- not by remembering what it did.

### Rule 6: Use Platform Memory for Cross-Session Learnings

If the platform provides a persistent memory mechanism (e.g., MEMORY.md, a memory API, or equivalent):

**Use it for:**
- Project state summaries (what has been built, key milestones)
- Architectural decisions and their rationale
- Known gotchas and workarounds
- Key identifiers (table IDs, API endpoints, configuration values)
- User preferences and conventions

**Do NOT use it for:**
- In-session state tracking (use sprint plan checklists instead)
- Detailed implementation notes (use sprint plans instead)
- Temporary debugging information (use logs instead)
- Full file contents (use the filesystem instead)

**Why**: Platform memory is typically size-constrained and loaded at every session start. It should contain information that accelerates orientation, not information that duplicates what is already on disk.

## Context Recovery Procedure

When resuming work after a context loss, follow this sequence:

### Step 1: Orient

Read the current state:
1. Read `PROGRESS.md` to identify the active sprint
2. Read the active sprint plan file
3. Run `git status` and `git log --oneline -5` to see recent changes

### Step 2: Assess

Determine what has been completed:
1. Check the sprint plan's task checklist
2. Run the test suite to see what passes
3. Look at recently modified files

### Step 3: Resume

Pick up where work left off:
1. Identify the next unchecked task in the sprint plan
2. Follow the TDD cycle (GL-TDD.md) for that task
3. Continue the sprint lifecycle (GL-SPRINT-DISCIPLINE.md)

## Breaking Work Into Context-Safe Stages

For large sprints that risk exceeding context limits:

### Stage Pattern

```
Sprint Plan
  -> Stage 1: Domain models (commit when done)
  -> Stage 2: Service layer (commit when done)
  -> Stage 3: Capability scripts (commit when done)
  -> Stage 4: Integration tests (commit when done)
  -> Stage 5: Review and documentation (commit when done)
```

Each stage is:
- **Self-contained**: Can be implemented without remembering the details of other stages
- **Committed**: Changes are saved to git, making them recoverable
- **Verifiable**: Tests confirm the stage is complete
- **Documented**: The sprint plan's checklist reflects completion

### When to Split Stages

Split when:
- The sprint involves more than 5 files
- The sprint involves more than 3 modules
- Estimated token consumption exceeds 50% of available context
- The sprint has distinct phases (domain -> service -> integration)

## Anti-Patterns

### Context Management Anti-Patterns

**NEVER DO:**

- Start implementation without saving the sprint plan to disk
- Continue work after compaction without re-reading the sprint plan
- Send sub-agents abbreviated instructions that assume shared context
- Keep important state only in conversation history
- Trust your "memory" of what was already implemented -- verify via filesystem
- Accumulate large volumes of text in the sprint plan during implementation (use separate status files if needed)

### Signs of Lost Context

If the agent exhibits any of these behaviors, context has been lost and recovery is needed:

- Attempting to create files that already exist
- Re-implementing functionality that tests already cover
- Asking questions whose answers are in the sprint plan
- Making architectural decisions that contradict the sprint plan
- Losing track of which review iteration is current

## Summary

| Situation | Action |
|---|---|
| Starting a sprint | Save plan to disk FIRST |
| Context compaction | Re-read sprint plan immediately |
| New session | Orient (PROGRESS.md -> sprint plan -> git status) |
| Spawning sub-agent | Provide complete task description, all file paths |
| Multi-step task | Persist intermediate state (checklists, commits) |
| Ambiguity about what to do | Sprint plan is source of truth |
| Sprint plan seems wrong | Update the file first, then proceed |

---

_This framework ensures that self-developing agents can survive context resets and continue productive work. The filesystem is the agent's durable memory; the context window is temporary working space._
