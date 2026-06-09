---
status: living
last-reconciled: 2026-06-08
---

# GL-GRANT-DRIFT

## Purpose

Grant drift is the difference between intended access policy and live access
policy. This guide applies to tool grants, role memberships, feature flags,
schema-pack permissions, environment-scoped capabilities, and other runtime
authorization data.

## Contract

Live authorization state is runtime truth. Code defaults are seed defaults and
comparison baselines only. Deploying a changed default must not silently grant
or revoke access on an existing principal.

## Expected Drift

Drift can be legitimate:

- An operator grants or revokes access.
- A self-service admin flow changes policy.
- A migration intentionally moves live state before code catches up.

Drift can also signal risk:

- Code expects a grant that live state does not have.
- Live state has broad grants no longer represented in code.
- A skill or capability version changed but principals still pin the old
  version.

## Report Shape

A drift report should separate at least these buckets:

- `code_only`: default exists in code, not live state.
- `live_only`: live state grants access absent from code defaults.
- `code_ahead`: code references a newer capability version than live state.
- `live_ahead`: live state references a newer capability version than code.
- `stale_pins`: principals pinned to old compatible versions.
- `missing_live_principal`: a principal expected by code has no live record.
- `malformed`: report could not be trusted.

## Gate Policy

Projects should define an explicit exit policy. A conservative default:

- `code_only`: fail deployment unless the rollout plan explains why code is
  allowed to be ahead.
- `live_only`: warn, alert, and require human review; do not automatically
  delete.
- `missing_live_principal` or `malformed`: fail closed.
- `code_ahead`, `live_ahead`, and `stale_pins`: fail or warn according to the
  project's compatibility policy.

## Runtime Alerts

Drift discovered outside deploy time should create an observable ticket or
alert. Alerts must include:

- Principal id.
- Capability or grant id.
- Drift bucket.
- Current live value.
- Expected/default value.
- Safe remediation command or manual procedure.

## Convergence

Routine convergence is "code catches up to live": freeze reviewed live policy
into future defaults.

The reverse direction, overwriting live state from code defaults, is an
emergency reset. It must require an explicit confirmation flag and must refuse
when live state contains operator-owned grants that cannot be merged safely.

## Race Safety

When multiple sync jobs may patch the same principal:

- Re-fetch immediately before writing.
- Patch only the columns owned by the sync operation.
- Recompute hashes or versions against the freshly fetched row.
- Treat last-writer-wins hashes as acceptable only when the hash covers the
  full current row state.

## Audit Requirements

Every write that changes live authorization state must leave audit evidence.
At minimum record actor, principal, changed grant or capability, previous
value, new value, reason, and timestamp.

## Anti-Patterns

- Auto-revoking `live_only` grants without provenance.
- Treating an empty default list as permission to erase live grants.
- Hiding authorization policy inside agent-specific code.
- Mixing validity checks with authorization checks.
- Reporting drift as advisory when no trusted live snapshot was read.
