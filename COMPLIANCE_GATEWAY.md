# Compliance Gateway

This project uses a local-first development gateway. Hooks run it before code
leaves the machine, so broken or non-compliant work should not waste remote CI.

## Source Of Truth

Local git hooks are the primary enforcement point:

- `pre-commit`: fast checks, including the module-size/god-file sensor.
- `commit-msg`: sprint ownership, cross-sprint staging, and inbox acknowledgements.
- `pre-push`: full gateway, including detected runtime checks and validators.

The GitHub Actions workflow is only a backstop. It catches missed local setup,
explicit `git --no-verify`, or environment drift.

## Manual Command

Run the full local gate:

```bash
python3 scripts/dev-gateway.py . --stage manual
```

Run the fast pre-commit gate:

```bash
python3 scripts/dev-gateway.py . --stage pre-commit
```

Install or refresh hooks:

```bash
bash scripts/install-git-hooks.sh
```

## Bypass Policy

Bypasses require operator approval and are logged:

```bash
DEV_GATEWAY_BYPASS=1 \
DEV_GATEWAY_BYPASS_REASON="short reason" \
DEV_GATEWAY_BYPASS_APPROVED_BY="operator-name" \
python3 scripts/dev-gateway.py . --stage manual
```

For pre-push hook bypass:

```bash
DEV_PREPUSH_BYPASS=1 \
DEV_PREPUSH_BYPASS_REASON="short reason" \
DEV_PREPUSH_BYPASS_APPROVED_BY="operator-name" \
git push
```

Do not use `git --no-verify` unless an operator explicitly approves it. Git
skips hooks entirely in that mode, so only the remote backstop can see the
violation after the fact.
