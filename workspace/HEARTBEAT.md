# Heartbeat — Task Polling and Periodic Maintenance

## On Session Start

Every new session or context restoration:

1. **Read MEMORY.md** — restore cross-session state (current sprint, last validation, known issues)
2. **Check for active sprint** — read PROGRESS.md, find `**Current:** SP_XXX`
3. **If active sprint exists** — read the sprint plan file, determine current stage (from MEMORY.md), resume work
4. **If no active sprint** — proceed to task polling

## On Heartbeat (Every 10 Minutes)

### 1. Poll for Tasks

Run the `poll-tasks` action from the **dev-deploy** skill:

```bash
python skills/dev-deploy/scripts/poll-tasks.py --tasks-dir tasks/
```

Read the JSON output:
- If `pending_count > 0`: begin the 7-stage Development Lifecycle Protocol (see AGENTS.md) on the task returned as `next_task`
- If `pending_count == 0`: proceed to maintenance checks

### 2. Check Deliveries

Scan `delivery/` for completed delivery reports older than 7 days. Archive them to `delivery/archive/` to keep the directory clean.

### 3. Workspace Health Check

Run `python skills/dev-bootstrap/scripts/bootstrap.py --action verify --project-root . --framework-root {{SDA_FRAMEWORK_ROOT}}` to verify workspace integrity.

### 4. Validation Check

If last validation was >24h ago (check MEMORY.md timestamp), run `python skills/dev-deploy/scripts/deploy.py --action validate --project-root .`

## Priority

Task polling takes precedence over maintenance. If a NEW task is found, skip maintenance checks and begin work immediately.

## Cron Schedule (If Supported)

| Job | Schedule | Command |
|-----|----------|---------|
| Task polling | Every 10 min | `python skills/dev-deploy/scripts/poll-tasks.py --tasks-dir tasks/` |
| Daily validation | 06:00 daily | `python skills/dev-deploy/scripts/deploy.py --action validate --project-root .` |
| Workspace health | 07:00 daily | `python skills/dev-bootstrap/scripts/bootstrap.py --action verify --project-root . --framework-root {{SDA_FRAMEWORK_ROOT}}` |
