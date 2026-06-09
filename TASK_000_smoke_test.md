# Task: Smoke Test — Verify Pipeline

**ID:** TASK_000
**Status:** NEW
**Requested by:** {{MAIN_AGENT_ID}}
**Deploy to:** {{MAIN_AGENT_ID}}
**Target workspace:** {{MAIN_AGENT_WORKSPACE}}
**Created:** {{CREATED_AT}}
**Timeout hours:** 1
**Priority:** high

## What the Human Asked For

This is an automated smoke test created during framework installation. No human request — this validates the end-to-end pipeline.

## What Functionality Is Missing

A minimal `smoke-test` skill that returns `{"status": "ok", "message": "Pipeline verified"}` as JSON to stdout.

## Acceptance Criteria

- [ ] `smoke-test/scripts/smoke.py` exists and outputs valid JSON with `status` and `message` fields
- [ ] `smoke-test/SKILL.md` exists with usage instructions
- [ ] At least 2 unit tests pass
- [ ] Skill is deployed to the requesting agent's workspace
- [ ] Requesting agent receives a delivery notification
- [ ] Requesting agent relays the Task Completion Summary to the human

## Domain Context

This is a pipeline validation task. The skill itself is trivial — the purpose is to verify that task pickup, sprint planning, TDD implementation, sub-agent review, cross-agent deployment, delivery notification, and human relay all work end-to-end. If the human sees the Task Completion Summary, the pipeline is working.
