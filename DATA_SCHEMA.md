---
status: living
last-reconciled: 1970-01-01
authoritative-for: [schema]
---
<!-- Template: fill in sections below. Replace last-reconciled with today's ISO date when you copy. Remove this comment when populated. -->

# Data Schema

## Database

- **Type**: [Database technology — e.g., PostgreSQL, SQLite, MongoDB, or a database-with-UI platform]
- **Version**: [Version if relevant]

## Connection

- **Method**: [How to connect — REST API, connection string, SDK]
- **Credentials**: [Where credentials are stored — environment variable name, secrets file path. Never put actual credentials here.]
- **Base URL / Host**: [Connection endpoint placeholder]

<!-- Example:
- **Method**: REST API via `https://<host>/api/`
- **Credentials**: Database token stored in `DATABASE_TOKEN` environment variable
- **Base URL / Host**: `https://database.example.com`
-->

## Tables

### [Table Name]

- **ID**: [Table identifier if applicable]
- **Purpose**: [What data this table stores]
- **Owner**: [Which agent/component owns writes to this table]

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| [field_name] | [text/number/boolean/date/single_select/link_row/...] | [Yes/No] | [What this field represents] |

<!-- Example:
### tasks

- **ID**: 613
- **Purpose**: All tracked tasks with lifecycle state
- **Owner**: Operations agent

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | auto_increment | Yes | Primary key |
| title | text | Yes | Human-readable task name |
| status | single_select | Yes | Current lifecycle state (open/in_progress/done/stale/cancelled) |
| priority | number | No | Numeric priority (1=highest) |
| owner_chat_id | number | Yes | Chat ID of the task owner |
| due_date | date | No | When this task is due |
| created_on | date | Yes | Auto-set on creation |
| stale_immune | boolean | No | If true, skip stale detection |
-->

## Relationships

[Describe foreign key relationships, link tables, and cross-references between tables.]

<!-- Example:
- `initiative_tasks.initiative_id` -> `initiatives.id` (many-to-one)
- `initiative_tasks.task_id` -> `tasks.id` (many-to-one)
- `knowledge_links` is a join table connecting `knowledge_items` to `knowledge_units`
-->

## Migrations

[How schema changes are applied. Include the process for adding fields, creating tables, and handling backward compatibility.]

<!-- Example:
1. Add field via database UI or REST API (`POST /api/database/fields/table/{table_id}/`)
2. Update DATA_SCHEMA.md with the new field
3. Update domain model (dataclass/enum) in `src/lib/`
4. Update service layer to read/write the new field
5. Add tests covering the new field
6. No destructive migrations — fields are added, never removed from production
-->
