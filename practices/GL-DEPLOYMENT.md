---
status: living
last-reconciled: 2026-06-08
---

# GL-DEPLOYMENT

## Purpose

Deployment is a controlled lifecycle stage, not a file-copy operation. This
guide defines the portable deployment discipline for projects using the
development rules in this bundle.

## Principles

1. Deploy through version control and CI/CD by default.
2. Validate before pushing or releasing.
3. Treat direct host access as emergency-only or read-only reconnaissance.
4. Verify the exact artifact or commit that was deployed.
5. Record bypasses, rollbacks, and unresolved risks.

## Pre-Deploy Gate

Before deployment:

```bash
python3 scripts/reconcile-sprint-frontmatter.py .
python3 validators/validate_doc_reality.py .
python3 validators/validate_doc_freshness.py .
python3 validators/run_all.py .
```

If any command fails, fix the failure instead of bypassing it.

For code-bearing changes, run the local CI gauntlet when the project provides
one:

```bash
bash scripts/ci-local.sh
```

## Staging Rules

Stage explicit files only. Do not use sweep staging. Confirm the staged diff
matches the sprint plan's `touches_paths` before committing.

Commit messages should include the sprint id for lifecycle-managed work:

```text
feat(SP_123): add durable queue processor
fix(SP_124): close duplicate callback replay
docs(SP_125): reconcile deployment guide
```

## CI/CD Rules

A deployable branch must run:

- Typecheck or compile checks when applicable.
- Unit and integration tests.
- Repository validators.
- Documentation validators.
- Security or policy checks required by the project.

CI jobs may run in parallel, but the deployment gate must aggregate all
required jobs. Do not mark required jobs `continue-on-error`.

## Post-Deploy Verification

After deployment, verify:

- The deployed commit or build id matches the pushed revision.
- Required health checks pass.
- The primary user workflow still works.
- Any fixed operator-observable symptom has been replayed or explicitly marked
  pending operator smoke.

Use scheduled wakeups or CI status polling with a bounded ceiling. Do not
tight-loop.

## Failure Handling

Treat the following as agent-fixable until proven otherwise:

- Typecheck or lint failures.
- Test regressions.
- Validator failures.
- Documentation reconciliation failures.
- Fixture drift.
- Smoke-test timeout caused by the new change.

Escalate only when the blocker is outside repository or deployment control,
such as account state, billing, missing secrets that the agent cannot access,
or an unrelated dependent service outage.

## Rollback Rules

Rollback is a deployment action and must be recorded. A rollback report should
include:

- Deployed revision.
- Rolled-back revision.
- Triggering failure.
- Operator-visible impact.
- Follow-up sprint or bug id.

Rollback does not close the sprint unless the success criteria explicitly allow
it.

## Scenario Coverage For Scheduled Work

Scheduled jobs need a deterministic test path. If a job normally runs by cron,
queue, or event bus, expose a test-only trigger in non-production or protected
test scope. The trigger must be authenticated, scoped to test principals, and
unable to fire arbitrary production events.

Scenario turns for scheduled work should assert side effects rather than chat
text unless the job actually emits user-facing messages.

## Bypass Discipline

Every bypass needs:

- Exact command or gate bypassed.
- Reason.
- Risk accepted.
- Follow-up if the bypass is not self-contained.

Prefer project-supported bypass environment variables that log automatically.
If bypassing hooks with native git flags, add a manual bypass-log entry.
