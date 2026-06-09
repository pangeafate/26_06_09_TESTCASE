# Sprint Planning Discipline

_Structured sprint lifecycle management for self-developing agent projects_

**Version**: 1.0
**Status**: Active Development Guidelines

---

## Philosophy

Self-developing agents operate across sessions that may lose context. Sprint plans are the primary mechanism for maintaining continuity: they capture what needs to be built, why, and how. Without disciplined sprint planning, agents repeat work, forget decisions, and drift from the roadmap.

## Sprint Naming Convention

### Format

```
SP_XXX_Description.md
```

- **SP**: Sprint Plan prefix (always uppercase)
- **XXX**: Three-digit sequential number, zero-padded (001, 002, ..., 130)
- **Description**: PascalCase or Snake_Case short description of the sprint goal

### Examples

```
SP_001_Foundation_Setup.md
SP_042_User_Authentication.md
SP_100_Briefing_Accuracy.md
SP_125_Bug_Fix_Enrichment_Pipeline.md
```

### Multi-File Sprints

When a sprint produces multiple files (implementation plans, sub-task breakdowns, review notes), create a subfolder:

```
workspace/sprints/
├── SP_099_Proposal_Action_Path.md         # Single-file sprint
├── SP_100_Briefing_Accuracy/              # Multi-file sprint
│   ├── SP_100_Briefing_Accuracy.md        # Main sprint plan
│   ├── SP_100_Review_Notes.md             # Review findings
│   └── SP_100_Schema_Changes.md           # Schema migration details
```

## Sprint Directory

All sprint plans live in:

```
workspace/sprints/
```

Where `workspace/` maps to whatever implementation tracking directory the project uses (e.g., `00_IMPLEMENTATION/SPRINTS/`). The key requirement is a single, predictable location.

## Pre-Feature Checklist

Before building any feature, complete these steps in order:

### 1. Check PROJECT_ROADMAP.md

- Verify the feature aligns with the current roadmap phase
- If PROJECT_ROADMAP.md does not exist, create it first
- Confirm no conflicting work is in progress

### 2. Create the Sprint Plan

- Create `SP_XXX_Description.md` in `workspace/sprints/`
- Use the sprint plan template (see below or `templates/SPRINT_PLAN.md`)
- Include: goal, scope, technical approach, testing strategy, success criteria
- **Save the plan to disk before starting implementation** (see GL-CONTEXT-MANAGEMENT.md)

### 3. Update PROGRESS.md

- Add the new sprint to the "Active Sprint" section
- Include a condensed one-line description
- Record the start date

### 4. Run Self-Critique (see GL-SELF-CRITIQUE.md)

- Minimum 2 review iterations on the sprint plan
- Address all CRITICAL and HIGH issues before implementation
- Update the plan file with fixes

## Post-Feature Checklist

After implementation is complete and all tests pass:

### 1. Update PROGRESS.md

- Move sprint from "Active" to "Sprint History"
- Record completion date
- Summarize what was delivered (features, test counts, key decisions)

### 2. Update PROJECT_ROADMAP.md

- Mark completed milestones/features
- Update phase progress percentages
- Adjust future estimates if needed

### 3. Update FEATURE_LIST.md

- Set completed features to `Status: Complete`
- Update `Completion: 100%`
- Fill in implementation file paths and test file paths

### 4. Update USER_STORIES.md

- Mark satisfied acceptance criteria
- Update story status to `Complete` if all criteria met

### 5. Update Architecture/Schema/Structure (if changed)

- ARCHITECTURE.md: new modules, changed layer boundaries, new integrations
- CODEBASE_STRUCTURE.md: new directories, moved files, renamed modules
- Schema documentation: new tables, new fields, changed relationships

## Sprint Plan Template

This template is a minimum viable sprint plan. Projects may extend it with additional sections (risk analysis, dependency graph, rollback plan). For comprehensive plans, see `templates/SPRINT_PLAN.md` which supersedes this leaner version.

```markdown
# Sprint Plan: [Description]

## Sprint Information
**Sprint ID:** SP_XXX_Description
**Duration:** X days (estimated)
**Start Date:** YYYY-MM-DD

## Sprint Goal
[Clear, concise goal in 1-2 sentences. What problem does this sprint solve?]

## Scope

### Features to Implement
- **F-XXX:** [Feature name]
  - [ ] Task 1 description
  - [ ] Task 2 description

### Out of Scope
[Explicitly list what this sprint does NOT include]

## Technical Approach

### New Files
| File | Purpose |
|---|---|
| `src/lib/new_module.py` | [What it does] |
| `test/unit/test_new_module.py` | [What it tests] |

### Modified Files
| File | Changes |
|---|---|
| `src/lib/existing.py` | [What changes and why] |

### Key Design Decisions
1. [Decision 1]: [Rationale]
2. [Decision 2]: [Rationale]

## Testing Strategy
[Per GL-TDD.md: what test types, what coverage targets, what edge cases]

### Test Plan
- [ ] Unit tests for [module 1]
- [ ] Unit tests for [module 2]
- [ ] Integration test for [feature]
- [ ] Edge cases: [list specific edge cases]

## Success Criteria
- [ ] All features implemented per scope
- [ ] All tests passing (0 failures)
- [ ] Coverage meets thresholds (80%+ line, 75%+ branch)
- [ ] Documentation updated (PROGRESS.md, FEATURE_LIST.md, etc.)
- [ ] Self-critique passed (0 CRITICAL/HIGH issues)

## Dependencies
[Other sprints, external services, or human decisions this sprint depends on]

## Rollback Plan
[How to safely revert if something goes wrong post-deploy]
```

## PROGRESS.md Management

### Archival Rule

When PROGRESS.md exceeds **25 sprint entries** in the Sprint History section, archive the oldest entries:

1. Create `PROGRESS_ARCHIVE_NNN.md` (where NNN is sequential: 001, 002, ...)
2. Move the oldest batch of sprints (e.g., 25 at a time) to the archive file
3. Add a reference at the top of PROGRESS.md:

```markdown
## Archived Sprints
- `PROGRESS_ARCHIVE_001.md` - Sprints SP_001 through SP_025
- `PROGRESS_ARCHIVE_002.md` - Sprints SP_026 through SP_050
```

4. Keep the most recent 25 sprints in the main file

### Why Archive

- Large PROGRESS.md files consume agent context window
- Historical sprint details are rarely needed for current work
- Archives preserve the full record for auditing

### PROGRESS.md Entry Format

Each completed sprint gets a condensed entry:

```markdown
### Sprint N: SP_XXX_Description
**Duration:** YYYY-MM-DD to YYYY-MM-DD
**Status:** Complete
**Summary:** [1-2 sentences: what was built, key metrics]
**Features Delivered:** F-XXX, F-YYY
**Tests Added:** +NN new tests (total: NNNN)
**Key Decisions:** [Any architectural decisions worth remembering]
```

## Sprint Lifecycle Summary

```
1. PLAN
   Check roadmap -> Create sprint plan -> Update PROGRESS.md -> Save to disk

2. CRITIQUE (GL-SELF-CRITIQUE.md Stage 3)
   Architect review -> Code review -> Consolidate -> Update plan

3. IMPLEMENT (GL-TDD.md)
   RED -> GREEN -> REFACTOR (repeat per feature)

4. VALIDATE (GL-SELF-CRITIQUE.md Stage 5)
   Gap analysis iterations -> Fix issues -> Re-run tests

5. DOCUMENT (GL-DOC-RECONCILIATION.md)
   Update PROGRESS.md -> ROADMAP -> FEATURES -> USER_STORIES -> ARCHITECTURE
   Bump last-reconciled -> run validate_doc_freshness.py -> write .docs_reconciled

6. DEPLOY (GL-DEPLOYMENT.md)
   Verify .docs_reconciled lockfile -> Push to version control -> CI/CD auto-deploy -> Verify deployment
```

---

_This framework ensures sprint planning discipline survives context resets and maintains project continuity across sessions._
