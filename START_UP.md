<!-- Template: fill in sections below. Remove this comment when populated. -->

# Start-Up Guide

## Prerequisites

[System requirements, tools, and access needed before starting.]

- [ ] [Requirement 1 — runtime, language version]
- [ ] [Requirement 2 — package manager, build tools]
- [ ] [Requirement 3 — access to external services]
- [ ] [Requirement 4 — credentials configured]

<!-- Example:
- [ ] Python 3.13 installed
- [ ] Virtual environment created (`.venv/`)
- [ ] SSH access to deployment server
- [ ] Database API token configured
- [ ] Messaging platform bot token configured
- [ ] Git repository cloned with all branches
-->

## Step 1: Understand the Project

Read these files in order to build a mental model of the project:

1. **PROJECT_CONTEXT.md** — What the project does and the agent's role
2. **ARCHITECTURE.md** — System components, data flow, and design decisions
3. **DATA_SCHEMA.md** — Database tables, fields, and relationships
4. **CODEBASE_STRUCTURE.md** — Directory layout, layer boundaries, naming conventions
5. **FEATURE_LIST.md** — All implemented features with source file references
6. **AGENT_IDENTITY.md** — Agent personality, behavioral rules, safety boundaries
7. **AGENT_INSTRUCTIONS.md** — Development rules and deployment procedures

<!-- Example:
After reading these files, you should be able to answer:
- What does the agent do and for whom?
- Where does data live and how does it flow?
- What code exists and how is it organized?
- What rules govern how I build new features?
-->

## Step 2: Understand the Practices

Read the practice guides that govern development:

1. **GL-TDD.md** — Test-driven development: write failing tests before implementation
2. **GL-RDD.md** — README-driven development: document before you build, module splitting rules
3. **GL-ERROR-LOGGING.md** — Error handling and logging standards
4. **GL-SPRINT-DISCIPLINE.md** — Sprint planning, self-critique, gap analysis
5. **GL-DEPLOYMENT.md** — Deployment procedures and safety checks

<!-- Example:
Key takeaways:
- Never write code without a failing test first
- Split modules when they mix concerns (domain vs service, formatting vs logic)
- All errors must be logged with structured context
- Sprint plans require 2 review iterations before implementation
- Gap analysis runs up to 5 iterations after implementation, stops on clean pass
-->

## Step 3: Understand Current Progress

Read these files to understand where the project stands right now:

1. **PROJECT_ROADMAP.md** — Current phase, upcoming milestones
2. **PROGRESS.md** — Active sprint, recent sprint history
3. **Active sprint plan** (if one exists) — What is currently being built

## Running Tests

[Commands to run the test suite.]

```bash
[test command — e.g., .venv/bin/python -m pytest test/unit/ -q]
```

<!-- Example:
```bash
# Run all unit tests
.venv/bin/python -m pytest test/unit/ -q

# Run a specific test file
.venv/bin/python -m pytest test/unit/test_task_domain.py -v

# Run integration tests (requires network access)
.venv/bin/python -m pytest test/integration/ -q
```
-->

## Deployment

[Commands to deploy the project.]

```bash
[deploy command — e.g., bash scripts/deploy.sh]
```

<!-- Example:
```bash
# Standard deployment (pushes to GitHub, CI/CD auto-deploys)
bash scripts/deploy.sh

# Emergency direct deployment via SSH
bash scripts/deploy.sh --direct

# Agent-specific deployment
bash scripts/deploy-agent-a.sh
bash scripts/deploy-agent-b.sh
```
-->

## Common Tasks

| Task | Steps |
|------|-------|
| [Common task 1] | [Numbered steps or command] |
| [Common task 2] | [Numbered steps or command] |

<!-- Example:
| Task | Steps |
|------|-------|
| Add a new database field | 1. Add field via API or UI. 2. Update DATA_SCHEMA.md. 3. Update domain model. 4. Update service layer. 5. Add tests. |
| Create a new skill | 1. Create `src/skills/{name}/SKILL.md`. 2. Create `src/skills/{name}/scripts/main.py`. 3. Add argparse CLI. 4. Write tests in `test/unit/`. 5. Register in agent config. |
| Start a new sprint | 1. Read PROJECT_ROADMAP.md. 2. Create `SP_XXX_Name.md` in sprints dir. 3. Run 2 review iterations. 4. Implement with TDD. 5. Run gap analysis. 6. Update PROGRESS.md + FEATURE_LIST.md. |
| Debug a failing test | 1. Run the specific test with `-v` flag. 2. Read the test and implementation. 3. Check domain/service contract. 4. Fix and verify all tests pass. |
| Add a new agent capability | 1. Create CAPABILITY.md from template. 2. Implement scripts. 3. Write tests. 4. Register in agent workspace config. 5. Deploy. |
-->
