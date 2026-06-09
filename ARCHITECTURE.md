---
status: living
last-reconciled: 1970-01-01
authoritative-for: [system-design, components]
---
<!-- Template: fill in sections below. Replace last-reconciled with today's ISO date when you copy. Remove this comment when populated. -->

# Architecture

## System Overview

[High-level diagram of the system. Use ASCII art or a Mermaid diagram to show major components and their connections.]

<!-- Example:
```
 Chat Platform API
       |
   [Agent Runtime]
       |
  +---------+---------+
  |         |         |
Skills    Lib     Workspace
  |         |
  +----+----+
       |
   [Database]
```
-->

## Components

### [Component Name]

- **Purpose**: [What this component does]
- **Technology**: [Language, framework, runtime]
- **Dependencies**: [What it depends on]
- **Key files**: [Entry points or important paths]

<!-- Example:
### Agent Runtime

- **Purpose**: Orchestrates pipeline stages, routes messages, executes skills
- **Technology**: Python 3.13, your-agent-platform framework
- **Dependencies**: Chat Platform API, Database REST API
- **Key files**: `workspace/agent-config.json`, `workspace/AGENTS.md`

### Skills Layer

- **Purpose**: Executable tools the agent invokes to perform discrete actions
- **Technology**: Python CLI scripts with argparse
- **Dependencies**: Shared library (`src/lib/`)
- **Key files**: `src/skills/*/SKILL.md`, `src/skills/*/scripts/`
-->

## External Services

| Service | Purpose | Protocol | Auth Method |
|---------|---------|----------|-------------|
| [Service name] | [What it provides] | [REST/gRPC/SQL/etc.] | [Token/OAuth/etc.] |

<!-- Example:
| Database | System of record for all project data | REST API | Database token |
| Chat Platform API | User interaction channel | HTTPS webhook | Bot token |
| Google Drive | Document storage | REST API | Service account |
-->

## Data Flow

[Describe how data moves through the system from input to output. Include the main flows.]

<!-- Example:
1. User sends message via chat platform
2. Agent runtime receives webhook, runs pipeline stages
3. Pipeline invokes relevant skill(s) via CLI
4. Skills read/write database via shared library services
5. Results formatted and returned to user via chat platform
-->

## Key Design Decisions

| Decision | Rationale | Alternatives Considered |
|----------|-----------|------------------------|
| [Decision made] | [Why this choice] | [What else was evaluated] |

<!-- Example:
| Domain + Service pairs | Separates business logic from I/O; testable without mocks | Single-file modules (rejected: grew too large) |
| CLI-based skills | Agent runtime invokes via subprocess; language-agnostic | In-process function calls (rejected: coupling) |
| Database-with-UI over raw SQL | Low-ops, UI for manual inspection, REST API | Raw Postgres (rejected: no built-in UI) |
-->
