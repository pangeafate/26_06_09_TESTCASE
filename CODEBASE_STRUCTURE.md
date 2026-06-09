---
status: living
last-reconciled: 1970-01-01
authoritative-for: [directory-layout, layer-rules]
---
<!-- Template: fill in sections below. Replace last-reconciled with today's ISO date when you copy. Remove this comment when populated. -->

# Codebase Structure

## Directory Layout

[Tree diagram showing the top-level directory structure. Use indentation to show hierarchy.]

```
project-root/
  [directory/]          # [Purpose]
  [directory/]          # [Purpose]
    [subdirectory/]     # [Purpose]
  [file]                # [Purpose]
```

<!-- Example:
```
project-root/
  src/
    lib/                # Shared library — domain models + services
      task_domain.py    # Task dataclasses, enums
      task_service.py   # Task CRUD, lifecycle operations
    skills/             # Agent capabilities (one directory per skill)
      example-briefing/
        SKILL.md        # Capability definition
        scripts/
          main.py       # Entry point
  test/
    unit/               # Unit tests (mirror src/ structure)
    integration/        # Integration tests (real API calls)
  workspace/            # Agent configuration
    AGENTS.md           # Agent behavioral rules
    agent-config.json   # Runtime configuration
  scripts/              # Deployment and utility scripts
  docs/                 # Project documentation
  CLAUDE.md             # AI agent instructions
```
-->

## Layer Boundaries

[Define what code lives in each layer and the rules governing each layer.]

| Layer | Location | Contains | Rules |
|-------|----------|----------|-------|
| [Layer name] | [Path] | [What belongs here] | [Constraints] |

<!-- Example:
| Domain | `src/lib/*_domain.py` | Dataclasses, enums, pure functions | No I/O, no imports from service layer |
| Service | `src/lib/*_service.py` | API calls, database operations | May import domain, never imported by domain |
| Skills | `src/skills/*/scripts/` | CLI entry points | Import from lib, never import from other skills |
| Workspace | `workspace/` | Agent config, prompts | No Python code |
| Tests | `test/` | Mirrors src/ structure | No production imports from test/ |
-->

## Dependency Direction

[Describe the import rules — which layers can import from which.]

```
[Higher layer] --> [Lower layer]     (allowed)
[Lower layer] -/-> [Higher layer]    (forbidden)
```

<!-- Example:
```
Skills --> Lib (Domain + Service)    (allowed)
Service --> Domain                   (allowed)
Domain -/-> Service                  (forbidden)
Skills -/-> Skills                   (forbidden — no cross-skill imports)
Tests --> Any                        (allowed)
```
-->

## Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| [File type] | [Pattern] | [Concrete example] |

<!-- Example:
| Domain module | `{noun}_domain.py` | `task_domain.py` |
| Service module | `{noun}_service.py` | `task_service.py` |
| Test file | `test_{module_name}.py` | `test_task_domain.py` |
| Skill directory | `{agent}-{action}` | `example-briefing` |
| Enum class | `PascalCase` | `TaskStatus` |
| Dataclass | `PascalCase` | `TaskItem` |
| Function | `snake_case` verb-first | `create_task()`, `query_active_tasks()` |
-->
