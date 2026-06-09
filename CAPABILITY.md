<!-- Template: fill in sections below. Remove this comment when populated. -->

---
name: [capability-name]
description: [One-line description of what this capability does]
version: [1.0.0]
---

# [Capability Name]

## When to Use

[Describe the conditions under which the agent should invoke this capability. Be specific about triggers, context, and prerequisites.]

<!-- Example:
Use this capability when:
- The user requests a task status update or task creation
- The pipeline detects an inbox event that maps to a task action
- A recurring task completes and needs its next instance generated

Do NOT use when:
- The request is about strategic initiatives (use `strategy-initiative` instead)
- The user is asking a question that doesn't require task mutation
-->

## Available Actions

### [action-name]

- **Command**: `[executable] [arguments]`
- **Input**: [Description of required and optional parameters]
- **Output**: [What the action returns on success]

<!-- Example:
### create

- **Command**: `python main.py --action create --title "Task title" --priority 2 --due-date 2026-04-15`
- **Input**: `--title` (required), `--priority` (optional, default 3), `--due-date` (optional, ISO format), `--owner-chat-id` (required)
- **Output**: JSON with `task_id`, `status`, and confirmation message on stdout

### query

- **Command**: `python main.py --action query --status open --owner-chat-id 12345`
- **Input**: `--status` (optional filter), `--owner-chat-id` (required for scope), `--limit` (optional, default 20)
- **Output**: JSON array of matching tasks on stdout

### update-status

- **Command**: `python main.py --action update-status --task-id 42 --new-status done`
- **Input**: `--task-id` (required), `--new-status` (required, one of: open/in_progress/done/cancelled)
- **Output**: JSON with updated task fields on stdout
-->

## Exit Codes

| Code | Meaning | Agent Should |
|------|---------|-------------|
| 0 | Success | Process output normally |
| 1 | Recoverable error | Retry or inform user of the issue |
| 2 | Fatal error | Stop and report to user; do not retry |
| 3 | Configuration error | Check config/credentials; do not retry |

## Data Sources

[Optional. List the data tables or APIs this capability reads from and writes to.]

<!-- Example:
| Table | Access | Purpose |
|-------|--------|---------|
| tasks (613) | Read/Write | Task CRUD operations |
| agent_queue (617) | Write | Queue proposals for user review |
| contacts (609) | Read | Resolve owner information |
-->

## Behavioral Rules

[Optional. Rules the agent must follow when using this capability.]

<!-- Example:
1. Always verify scope before writing — never create tasks in another user's scope
2. When updating status to `done`, check for recurrence rule and trigger next instance generation
3. Never delete tasks — use `cancelled` status instead
4. Log all write operations to stderr with `[AUDIT]` prefix
-->

## Error Taxonomy

[Optional. Maps stored status values or error codes to their meaning. Useful when the capability writes status fields to a database.]

<!-- Example:
| Stored Value | Meaning | Recovery |
|-------------|---------|----------|
| `failed_agent` | Agent produced invalid output | Re-run with stricter prompt |
| `failed_store` | Database write failed | Retry after backoff |
| `failed_parse` | Could not parse agent response | Log raw response, mark as failed |
-->

## References

[Optional. Links to implementation files for quick navigation.]

<!-- Example:
- Entry point: `src/skills/example-write/scripts/main.py`
- Domain: `src/lib/task_domain.py`
- Service: `src/lib/task_service.py`
- Tests: `test/unit/test_task_domain.py`, `test/unit/test_task_service.py`
-->

## Examples

[Show concrete examples of how the agent invokes this capability and what it gets back.]

<!-- Example:
### Creating a task

```
$ python main.py --action create --title "Review Q1 report" --priority 1 --owner-chat-id 12345
{"task_id": 42, "status": "open", "title": "Review Q1 report", "priority": 1}
```

### Querying open tasks

```
$ python main.py --action query --status open --owner-chat-id 12345
[{"task_id": 42, "title": "Review Q1 report", "status": "open", "priority": 1}]
```
-->
