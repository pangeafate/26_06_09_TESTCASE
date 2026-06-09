# Documentation Reconciliation

_How to keep meta-documentation aligned with shipped reality_

**Version**: 1.0
**Status**: Active Development Guidelines

---

## Philosophy

Documentation rot is structural. It happens when doc-writing is disconnected from a validated discipline: docs that describe code paths are written once and never reconciled, aspirational docs are read as current spec, the same content lives in two files and drifts, and `TBD` markers outlive their intended owners.

This practice provides the conventions — and `validators/validate_doc_reality.py` provides the enforcement — that close those gaps.

## The Four Drift Modes and Their Controls

| Drift mode | Control | Enforcement |
|---|---|---|
| Dead references (docs reference paths that no longer exist) | Reconciliation checklist at sprint close | Stage A |
| Stale placeholders (`TBD` markers that outlive their sprint) | `TBD-by: SP_NNN` convention | Stage B |
| Silent aspiration (vision-era docs read as current spec) | Frontmatter `status:` + vision quarantine | Stage C |
| Copy-paste duplication (two files share 15 Rules, drift) | `@inherits:` directive | Stage D |

## Frontmatter Convention

Every meta-doc at project root carries a frontmatter block at **byte 0**:

```markdown
---
status: living
last-reconciled: 2026-04-13
authoritative-for: [features, sprint-history]
---
```

### Required keys

- `status`: one of `living | vision | spec | archived | generated`.
- `last-reconciled`: ISO-8601 date (`YYYY-MM-DD`). Bump on every sprint that touches the doc's subject matter.

### Optional keys

- `authoritative-for`: list of topics this doc is the source of truth for.

### Status semantics

- **living** — actively maintained; source of truth for its topics.
- **vision** — aspirational, pre-implementation. Must live under `vision/` and start with a visible banner. Excluded from validation by default.
- **spec** — frozen contract for a specific feature. Updates require a new sprint.
- **archived** — historical; retained for reference but no longer authoritative.
- **generated** — emitted by tooling; do not edit by hand. Frontmatter present for consistency; staleness checks disabled.

## Single-Source Rule and `@inherits:`

If content appears in two files, one must be the source and the other an explicit reference. Never copy-paste.

When inheritance is the right pattern (e.g., project-level `CLAUDE.md` inherits the framework's `AGENT_INSTRUCTIONS.md`), mark the inherited block:

```markdown
@inherits: AGENT_INSTRUCTIONS.md

...content copied from the source, with the understanding that updates flow from the source...

@inherits-end:
```

Stage D of `validate_doc_reality.py` skips duplication detection inside `@inherits:` / `@inherits-end:` ranges. An unterminated `@inherits:` directive (no matching end) emits an advisory and suppresses only the directive line itself — it does **not** suppress the rest of the file.

## Vision-Doc Quarantine

Aspirational documents (pitches, visions, pre-MVP ideas) are written in a different tense than specs and will confuse agents reading them as current truth.

Conventions:
- Vision documents live under `vision/` at project root.
- Their frontmatter declares `status: vision`.
- The first line after the frontmatter is a visible banner:
  ```
  > **ASPIRATIONAL** — written YYYY-MM-DD. Not a spec for current behavior. See FEATURE_LIST.md for shipped features.
  ```
- `vision/` is in the default `exclude_dirs` of the doc-reality validator; vision docs are never scanned for dead paths or duplication.

## `TBD-by: SP_NNN` Convention

Placeholders that must eventually be resolved include a target sprint:

```markdown
The streaming backend is `TBD-by: SP_007`.
```

Stage B of `validate_doc_reality.py` fails when `SP_NNN` is less than the active sprint number (per `PROGRESS.md`). It emits an advisory (not a failure) when the target is equal to the active sprint.

Guideline: any `TBD` worth keeping in a doc is worth tagging. Untagged `TBD` markers are technical debt with no deadline.

## Sprint-End Reconciliation Checklist

Every sprint's **Stage 6 (Documentation)** must walk this checklist. Each entry maps to a meta-doc; tick the ones the sprint's deltas touched.

- [ ] `FEATURE_LIST.md` — feature statuses, sprint numbers, implementation paths
- [ ] `PROJECT_ROADMAP.md` — milestone status for touched phases
- [ ] `ARCHITECTURE.md` — only if system design changed
- [ ] `DATA_SCHEMA.md` — only if schema changed
- [ ] `CODEBASE_STRUCTURE.md` — only if directories/files moved
- [ ] `USER_STORIES.md` — if acceptance criteria were satisfied
- [ ] `last-reconciled` bumped on each touched meta-doc
- [ ] `python validators/validate_doc_reality.py <project_root>` returns 0
- [ ] `python validators/validate_doc_freshness.py <project_root>` returns 0 (writes `.docs_reconciled` lockfile on success)

A failure of the final step blocks Stage 7 (Deployment) — see Rule 16 in `AGENT_INSTRUCTIONS.md`.

## Migrating an Existing Project

A project that predates `validate_doc_freshness.py` pulls the new validator on upgrade. To avoid breaking its existing sprints:

- By default, `doc_freshness.enabled` is `false` (or absent) — the validator advisory-passes on every run.
- Opt in by adding to `.validators.yml`:
  ```yaml
  doc_freshness:
    enabled: true
  ```
- Before enabling: ensure every sprint plan under `workspace/sprints/` has a frontmatter block with `sprint_id`, `features`, `user_stories`, `schema_touched`, `structure_touched`, `status`. Backfilling historical sprints is optional; only the currently-active sprint's plan is examined by Stage F-1.
- First run after opt-in: expect findings. Triage, fix, bump `last-reconciled` dates, re-run. `.docs_reconciled` is written on the first fully clean run.

## Generated-Doc Marker (Forward-Compatible)

Docs produced by tooling (e.g., a future `TRACEABILITY.md` generator) write frontmatter with `status: generated` and `last-reconciled` sourced from the most recent input sprint's date (not "today" — the output must be deterministic). Hand-edits to generated files are lost on regeneration; treat them as build artifacts committed for convenience.

## Exclusion Layers

`validate_doc_reality.py` has three independent exclusion mechanisms; use the right one:

1. **`exclude_dirs`** (`.validators.yml` → `doc_reality.exclude_dirs`) — skips the filesystem walk. Use for directories where illustrative paths are expected (examples, templates, fixtures).
2. **`dead_path_exclusions`** — exact token match against the extracted backtick-wrapped path. Use for one-off documented exceptions.
3. **`dead_path_glob_exclusions`** — fnmatch pattern match against the extracted token. Use for growing sets like `PROGRESS_ARCHIVE_*.md`.

Inline suppression markers (`<!-- doc-reality:ignore-paths -->`, `<!-- doc-reality:ignore-block-start/end -->`) apply exclusively to Stage A. Stage D uses `@inherits:` blocks; Stages B and C have no suppression (a `TBD-by` with an elapsed sprint or a missing frontmatter key is always a failure).

## Enforcement

See `validators/validate_doc_reality.py` for the runnable enforcement of every convention in this document.

---

_This practice ensures that documentation stays factual by construction. The validator catches drift at sprint close; the conventions prevent it at sprint start._
