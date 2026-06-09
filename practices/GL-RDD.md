# README-Driven Development Framework

_A documentation-first approach to software development for self-developing agent projects_

**Version**: 1.0
**Status**: Active Development Guidelines

---

## Philosophy

README-Driven Development (RDD) treats documentation as the primary design artifact. By writing documentation first, we clarify intent, establish contracts, and create a shared understanding before implementation begins. For AI agents building their own codebases, documentation serves a dual purpose: it is both the design contract and the persistent memory that survives context resets.

## Core Principles

### The Four Pillars

1. **Document First, Implement Second**
   - Write what you will build before building it
   - Documentation drives design decisions
   - Documentation becomes the contract
2. **Modular Architecture**
   - Small, focused modules (SRP - Single Responsibility Principle)
   - Clear boundaries between layers
   - Explicit dependencies
3. **Continuous Documentation**
   - Documentation evolves with code
   - Every change requires doc updates
   - Documentation is part of Definition of Done
4. **Predictable Structure**
   - Consistent patterns across the codebase
   - Self-documenting folder organization
   - Standardized file sizes and complexity limits

## Documentation Hierarchy

### Understanding a New Codebase (Sequential Process)

1. **Start with PROJECT_CONTEXT.md** - Understand what we are building
2. **Analyze the codebase** - See current development progress
3. **Review USER_STORIES.md** - Understand user stories and their implementation status
4. **Check FEATURE_LIST.md** - See detailed features with completion indicators
5. **Read GL-RDD.md and GL-TDD.md** - Understand development principles
6. **Review CODEBASE_STRUCTURE.md** - Understand code organization rules
7. **Check ARCHITECTURE.md** - Understand system design and technical decisions
8. **Review PROJECT_ROADMAP.md** - See implementation plan from MVP to target state
9. **Check PROGRESS.md** - Review sprint history and current progress
10. **Review active sprint plans** - Understand current work in progress

## Standard Project Structure

```
project-root/
├── 00_PLAN/                          # Product vision and requirements
│   ├── VISION.md                     # Product vision and goals
│   ├── USER_STORIES.md               # User stories linked to features
│   ├── FEATURE_LIST.md               # Complete feature list with status
│   └── ARCHITECTURE.md               # System design and architecture
├── 00_IMPLEMENTATION/                # Implementation planning and tracking
│   ├── PROJECT_ROADMAP.md            # Implementation plan (MVP to target)
│   ├── PROGRESS.md                   # Sprint tracking and history
│   ├── GL-RDD.md                     # README-Driven Development guidelines
│   ├── GL-TDD.md                     # Test-Driven Development guidelines
│   ├── GL-ERROR-LOGGING.md           # Error handling and logging standards
│   ├── CODEBASE_STRUCTURE.md         # Code organization rules
│   └── SPRINTS/                      # Individual sprint plans
│       └── SP_XXX_Description.md
├── src/
│   ├── capabilities/                 # Agent capabilities (spec + scripts)
│   │   └── [capability-name]/
│   │       ├── SPEC.md               # Capability specification
│   │       └── scripts/
│   │           └── [script].py
│   ├── models/                       # Data structures, enums, validation
│   │   └── [model].py
│   ├── lib/                          # Shared logic library
│   │   ├── __init__.py
│   │   └── [module].py
│   └── infra/                        # Infrastructure setup
│       └── [setup scripts]
├── test/                             # Test infrastructure (see GL-TDD.md)
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── scripts/                          # Build/deploy/utility scripts
└── README.md                         # Project overview
```

## Essential Documentation Files

### 00_PLAN Folder

#### VISION.md Template

```markdown
# Project Vision

## Executive Summary
[1-2 paragraph overview of what we are building and why]

## Problem Statement
[What problem are we solving?]

## Target Users
[Who will use this?]

## Core Value Proposition
[What unique value do we provide?]

## Success Metrics
[How do we measure success?]

## Non-Goals
[What are we explicitly NOT doing?]
```

#### USER_STORIES.md Template

```markdown
# User Stories

## Story Format
As a [type of user], I want [goal] so that [benefit]

## Epic: [Epic Name]

### US-001: [Story Title]
**As a** [user type]
**I want** [functionality]
**So that** [benefit]

**Acceptance Criteria:**
- [ ] Criterion 1
- [ ] Criterion 2

**Status:** [Not Started | In Progress | Complete]
**Features:** Links to FEATURE_LIST.md entries
**Implementation:** [File locations if implemented]
```

#### FEATURE_LIST.md Template

```markdown
# Feature List

## Feature Categories

### [Category Name]

#### F-001: [Feature Name]
**Description:** Plain English description
**Status:** [Not Started | In Progress | Complete | Blocked]
**Completion:** [0-100%]
**User Stories:** US-001, US-002
**Implementation:**
- File: [path/to/file.ext]
- Tests: [path/to/test.ext]
**Dependencies:** F-002, F-003
**Notes:** Any relevant information
```

### 00_IMPLEMENTATION Folder

#### PROJECT_ROADMAP.md Template

```markdown
# Project Roadmap

## Phases

### Phase 1: MVP
**Target Date:** YYYY-MM-DD
**Status:** [Planning | In Progress | Complete]

#### Milestone 1.1: [Name]
**Features:** F-001, F-002, F-003
**Status:** [0-100%]
**Sprint:** SP_XXX_Description

### Phase 2: Enhanced Features
[Continue pattern...]

## Release History
- v0.1.0 (YYYY-MM-DD): MVP release
```

#### PROGRESS.md Template

```markdown
# Development Progress

## Active Sprint
**Current:** SP_XXX_Description
**Started:** YYYY-MM-DD
**Target Completion:** YYYY-MM-DD

## Sprint History

### Sprint N: SP_XXX_Description
**Duration:** YYYY-MM-DD to YYYY-MM-DD
**Status:** Complete
**Features Delivered:** F-001, F-002
```

#### Sprint Plan Template (SP_XXX_Description.md)

```markdown
# Sprint Plan: [Description]

## Sprint Information
**Sprint ID:** SP_XXX_Description
**Duration:** X days
**Start Date:** YYYY-MM-DD

## Sprint Goal
[Clear, concise goal in plain English]

## Scope
### Features to Implement
- **F-XXX:** [Feature name]
  - [ ] Task 1 description
  - [ ] Task 2 description

## Technical Approach
[Plain English description of how features will be implemented]

## Testing Strategy
[Description of testing approach per GL-TDD.md]

## Success Criteria
- [ ] All features implemented
- [ ] All tests passing
- [ ] Documentation updated
```

## Module Development Workflow

```
Identify Need -> Write Module README -> Define Interfaces -> Write Tests -> Implement -> Refactor -> Update Docs -> Review -> Merge
```

## Module Splitting Guidelines

### CRITICALLY IMPORTANT -- Architectural Principles

#### When to Split Files (Based on Architectural Concerns)

**ALWAYS SPLIT when a module violates these principles:**

1. **Single Responsibility Principle Violations**
   - Split when mixing: Domain Logic + I/O Operations + Utilities
   - **Domain Logic**: Business rules, validation, entity behavior, workflows
   - **I/O Operations**: Database calls, file operations, network requests, external APIs
   - **Utilities**: Formatting, parsing, helpers, transformations

2. **Multiple Component/Feature Mixing**
   - Split when combining multiple unrelated components or features
   - Each component should have its own focused module

3. **Layer Boundary Violations**
   - Split when mixing different architectural layer concerns

#### When NOT to Split Files

**KEEP INTACT when modules follow established patterns and remain cohesive:**

1. **Service Pattern**: All operations for a business capability belong together
   - *Exception*: If service mixes orchestration + I/O + utilities, separate by concern type
2. **Repository/Client Pattern**: All CRUD operations for an entity belong together
   - *Exception*: If repository mixes business rules with I/O, extract business rules
3. **Entity/Model Pattern**: All behavior for a domain entity belongs together
   - *Exception*: If entity includes I/O operations, extract those
4. **Adapter Pattern**: All operations for external integration belong together
   - *Exception*: If adapter includes business logic, extract to separate module

**Resolution Rule**: When pattern cohesion conflicts with SRP, prioritize SRP.

### Quality Metrics (Supporting Guidelines)

#### Complexity Indicators (Review Triggers)

- **Cyclomatic Complexity**: >10 suggests review needed
- **Cognitive Complexity**: >15 suggests complexity reduction
- **File Dependencies**: >8 imports suggests tight coupling
- **Function Parameters**: >4 parameters suggests complex interface

These are review triggers, not hard limits. A module exceeding one metric may be fine; exceeding two or more demands splitting.

#### Mechanical Enforcement (Module Size Sensor)

Cyclomatic/cognitive complexity stay advisory review-triggers, but **raw file
size and import count are mechanically enforced** by
`validators/validate_module_size.py` (a language-agnostic sensor, wired into
`validators/run_all.py`). Without it, the size guidance above is prose with no
teeth and modules silently grow into thousands-of-line God-files.

Two-tier severity (configurable in `.validators.yml` under `module_size`):

- lines > `fail_lines` (default 2000) → **FAIL** — module must be split.
- lines > `warn_lines` (default 800) → WARNING — approaching God-file size.
- imports > `warn_imports` (default 25) → WARNING — high coupling.

The sensor does not split anything; it makes debt visible and blocks *new*
God-files. Pre-existing offenders can be grandfathered via the `allow:` list
(they keep WARNing so the debt stays visible) while a tracked sprint splits them
down one concern at a time. Composition roots legitimately carry many imports,
which is why import count is warn-only and the line count is the load-bearing
signal. See `validator-config.example.yml` for the full config schema.

## Layer Boundaries & Rules

### Dependency Direction

```
Capabilities (execution) -> Shared Logic (lib) -> Models (data) <- Config (settings)
```

### Layer Responsibilities

| Layer | Responsibilities | Forbidden | Dependencies |
|---|---|---|---|
| Capabilities | Script execution, API orchestration, output formatting | Business logic in spec files, direct config access | -> Lib |
| Shared Logic (Lib) | Business logic, API clients, data validation | Script execution, agent interaction | -> Models, Config |
| Models | Data structures, enums, validation rules | External dependencies, I/O | <- (No dependencies) |
| Infrastructure | Setup scripts, container config, deployment | Business logic | -> Config |

### What Each Layer Produces

- **Capabilities**: Executable scripts that the agent invokes; each has a spec (SPEC.md) describing inputs/outputs and a `scripts/` directory with implementation.
- **Shared Logic**: Importable Python modules containing business rules, service functions, API client wrappers, and data transformations.
- **Models**: Pure data definitions (dataclasses, enums, type aliases) with optional validation. No side effects, no I/O.
- **Infrastructure**: One-time or periodic setup: database migrations, deployment scripts, environment configuration.

## Development Checklist

### Pre-Development

```
[ ] Problem clearly defined
[ ] README / capability spec written
[ ] Interfaces designed
[ ] Dependencies identified
[ ] Tests outlined
```

### During Development

```
[ ] Following README-driven approach with TDD (Document -> Test -> Code)
[ ] Maintaining single responsibility per module
[ ] Separating domain logic, I/O operations, and utilities
[ ] Updating documentation as implementation evolves
[ ] Adding error handling
[ ] Including logging
```

### Pre-Commit

```
[ ] All tests passing
[ ] Coverage meets threshold (80%+)
[ ] No modules mixing domain logic + I/O + utilities
[ ] Single responsibility principle maintained
[ ] Layer boundaries respected
[ ] Documentation updated
```

## Anti-Patterns to Avoid

### Do Not:

- Create monolithic modules that violate SRP
- Mix concerns across architectural layers
- Skip error handling
- Use magic numbers/strings
- Create circular dependencies
- Document after implementation
- Skip tests for "simple" code

### Do:

- Keep modules focused (SRP)
- Maintain clear layer boundaries
- Handle all error cases explicitly
- Use configuration/constants
- Design clear dependency graphs
- Write documentation first
- Test everything, including edge cases

---

_This framework establishes a documentation-first approach to software development, ensuring clarity, maintainability, and scalability in self-developing agent projects._
