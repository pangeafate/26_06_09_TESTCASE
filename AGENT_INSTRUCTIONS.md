<!-- Template: fill in sections below. Remove this comment when populated. -->

> **Note**: This is the template version for your project's agent instructions. The framework's own development rules are in the root `AGENT_INSTRUCTIONS.md`.

# Agent Instructions

## Development Rules

[Numbered rules that govern how the agent develops code. Reference the relevant GL-*.md practice guides.]

1. [Rule — reference GL-TDD.md if applicable]
2. [Rule — reference GL-RDD.md if applicable]
3. [Rule — reference GL-ERROR-LOGGING.md if applicable]
4. [Rule]

<!-- Example:
1. Never write code before writing a failing test first — follow GL-TDD.md (automated tests required for all Python skill scripts, services, and library code)
2. Follow GL-RDD.md for documentation-first development and module splitting guidelines
3. Follow GL-ERROR-LOGGING.md for error handling and logging standards
4. Maintain clear layer boundaries: skills (execution) / lib (shared logic) / workspace (agent config) / infra (setup)
5. Always use appropriate agents and run them in parallel to speed up work. Context isolation: review and debugging work MUST be done by dedicated sub-agents, not inline
6. Primary language: Python 3.13
7. Database: your-database (REST API) — system of record for all data
-->

## Sprint Discipline

[Rules governing how sprints are planned, executed, and closed. Reference GL-SPRINT-DISCIPLINE.md.]

<!-- Example:
1. Before building any feature:
   - Check PROJECT_ROADMAP.md
   - Create the sprint plan in `00_IMPLEMENTATION/SPRINTS/` using naming: `SP_XXX_Description.md`
   - Update PROGRESS.md with condensed sprint description
   - After implementation, update PROGRESS.md, PROJECT_ROADMAP.md, FEATURE_LIST.md, and USER_STORIES.md
2. Sprint plan self-critique: After writing a sprint plan, run 2 parallel self-critique iterations using dedicated sub-agents before starting implementation
3. Post-sprint gap analysis: After tests pass and BEFORE deploying, run up to 5 iterations of gap analysis using dedicated sub-agents. Stop early if an iteration finds zero issues
4. Save sprint plans before implementation. After context compaction, re-read the sprint plan file to restore context
-->

## Deployment

[Rules governing how code is deployed. Reference GL-DEPLOYMENT.md.]

<!-- Example:
1. Deploy via: `bash scripts/deploy.sh` (pushes to GitHub for CI/CD auto-deploy)
2. Agent-specific: `scripts/deploy-agent-a.sh` or `scripts/deploy-agent-b.sh`
3. Use `--direct` flag only for emergency SSH deployment
4. After a clean gap analysis iteration (zero issues found), deploy automatically
5. Never deploy without all tests passing
-->

## Platform-Specific Rules

[Rules specific to this project's technology stack, infrastructure, or organizational constraints.]

<!-- Example:
1. All scripts run as user `appuser` on the server — file ownership must be `appuser:appuser`
2. Shared library (`src/lib/`) is deployed alongside skill scripts for import access
3. Do not use Docker for application code — Docker is only for database infrastructure
4. Use `docker-compose` (NOT `docker compose`) on the server
5. Agent workspace needs `.agent/workspace-state.json` to be recognized by the runtime
6. nginx route required for each webhook endpoint
-->
