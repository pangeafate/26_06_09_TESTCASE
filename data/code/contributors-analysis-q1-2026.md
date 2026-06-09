# HelixPay Engineering — Contributor and Repository Analysis, Q1 2026

*Source: in-house analysis script over GitHub history (`helixpay/*` org). Period: 2026-01-01 → 2026-03-31. Author: Vikram Patel. Generated 2026-04-08.*

This is a periodic analysis we run for the eng leadership review. Not exhaustive —
focuses on the four repositories that drive the strategic roadmap. Some identities
remain unresolved against the org chart.

## Repositories in scope

| Repository                | Primary owner    | Scope                                          |
|---------------------------|------------------|------------------------------------------------|
| `helixpay/core`           | Sara Wijaya      | Payments core, merchant data model, fees engine |
| `helixpay/pos-app`        | Ahmad Rashid     | POS terminal app + POS Self-Service kiosk app  |
| `helixpay/loyalty`        | Yong Wei (PM); Sara dotted | Loyalty service, Tap-Loyalty bridge   |
| `helixpay/platform-infra` | Vikram Patel     | Dual-write tooling, Terraform, observability   |

## Headline numbers — Q1 2026

| Repo               | Commits | PRs merged | Net LOC  | Active contributors |
|--------------------|---------|------------|----------|---------------------|
| `core`             | 412     | 168        | +14,202  | 11                  |
| `pos-app`          | 187     | 78         | +3,914   | 6                   |
| `loyalty`          | 64      | 22         | +1,024   | 3                   |
| `platform-infra`   | 298     | 121        | +9,478   | 5                   |

Across all four repos, ~62% of Q1 commit volume is tagged (by branch prefix or PR label)
to the Confluence program — primarily the merchant_id schema work. This matches the
qualitative read from the eng leads: most of the team is on platform unification, not
on customer-visible feature work.

## Top contributors by repo (commit count, Q1)

### `helixpay/core`

| Contributor          | Commits | Lines (+/−)       | Notes                                               |
|----------------------|---------|-------------------|-----------------------------------------------------|
| Sara Wijaya          | 89      | +4,201 / −2,118   | merchant_id schema design + migration script        |
| Camila Souza         | 71      | +3,112 / −1,840   | Brasil reconciliation logic, tax-id edge cases       |
| Pedro Almeida        | 58      | +2,401 / −1,022   | Fees engine, BR locale handling                      |
| Tan Wei Ming         | 41      | +1,612 / −720     | Started early Feb after relocation; ramp-up commits |
| Rishi Iyer           | 33      | +1,128 / −602     | Fraud rules                                          |
| `noise` (unresolved) | 28      | +840 / −411       | Likely former contractor account; flag for cleanup   |
| Daniel Tan           | 22      | +602 / −180       | Reviews + occasional direct fixes                   |
| Aaron Wong           | 18      | +312 / −104       | Unclear — appears to be a marketing email, possible misattribution; investigating |
| 3 others (≤10 each)  | 52      |                   |                                                     |

Note: "Daniel Tan" and "Tan Wei Ming" both appear in this list and are different
people. Tan Wei Ming relocated from Singapore to São Paulo on 2026-02-09 and his
GitHub email changed to a `@helixpay.com.br` alias mid-quarter; commits before and
after were attributed to two separate identities until manually reconciled.

### `helixpay/pos-app`

| Contributor          | Commits | Notes                                       |
|----------------------|---------|---------------------------------------------|
| Ahmad Rashid         | 51      | Mostly review + Tap-Loyalty bridge tweaks   |
| Lin Xinyi            | 42      | Frontend on the merchant portal embedded in POS app |
| Gabriel Souza        | 31      | Brasil mobile work; **not related to Camila Souza** |
| Aiman Idris          | 24      | **Likely misattribution — Aiman is a CSM, not an engineer.** Investigating: probably an old PR by an engineer who left, where the commit author email collides with a current CSM. Will scrub. |
| 2 others             | 39      |                                             |

The Aiman Idris row is a known data-quality issue and is the kind of thing this
analysis surfaces. We have at least three cases per quarter of GitHub identities
that don't map cleanly to current employees — flagging for cleanup is part of why
this report exists.

### `helixpay/loyalty`

| Contributor      | Commits | Notes                                          |
|------------------|---------|------------------------------------------------|
| Yong Wei         | 38      | PM — most are doc + spec commits, not code     |
| Camila Souza     | 18      | Tap-Loyalty bridge fixes                       |
| Sara Wijaya      | 8       | Cross-repo coordination                        |

The Tap-Loyalty bug (HX-LOY-487, open since Nov 2025) shows commit activity in
February (3 commits attempted fix, reverted), then quiet through March. Stalled
behind Confluence work.

### `helixpay/platform-infra`

| Contributor      | Commits | Notes                                          |
|------------------|---------|------------------------------------------------|
| Vikram Patel     | 102     | Dual-write tooling, recon scripts              |
| Anand R.         | 67      | SRE; observability work                        |
| `Nikita@local`   | 41      | **Unresolved identity. Local-machine commits without a verified email.** Likely Vikram's secondary machine; needs cleanup. |
| 2 others         | 88      |                                                |

## Unresolved GitHub identities (action required)

The following commit identities don't map cleanly to the current employee directory:

1. **`noise`** — appears in `core` and `loyalty`. Likely a former contractor; commits
   span Q4 2024 to early Q2 2025, with sporadic activity since. Recommend retiring
   the account.
2. **`Nikita@local`** — appears only in `platform-infra`. Local-machine signature.
   Probably one of the existing engineers' personal-machine commits without a verified
   email. Vikram is checking.
3. **`Aaron Wong` in `core`** — Aaron Wong is in Performance Marketing per the org chart.
   Likely a misattribution from a years-old contractor whose email Aaron's was later
   recycled to. Investigating.
4. **`Aiman Idris` in `pos-app`** — see above; probably a recycled email.

## Cross-repo collaboration

Pairs with the highest cross-repo PR review activity (i.e., engineers from one repo
reviewing PRs in another):

| Pair                                   | Cross-PR reviews |
|----------------------------------------|------------------|
| Sara Wijaya ↔ Camila Souza             | 47               |
| Vikram Patel ↔ Sara Wijaya             | 38               |
| Sara Wijaya ↔ Yong Wei                 | 21               |
| Ahmad Rashid ↔ Camila Souza            | 18               |
| Daniel Tan ↔ Sara Wijaya               | 16               |

This pattern reflects the Confluence work — the three top pairings are all on the
critical path of the schema migration.

## Hot files (most-modified files Q1)

| File                                                         | Commits | Repo  |
|--------------------------------------------------------------|---------|-------|
| `helixpay/core/merchants/schema_v3.py`                       | 84      | core  |
| `helixpay/core/migrations/dual_write/reconciliation.py`      | 71      | core  |
| `helixpay/platform-infra/terraform/dual_write/main.tf`       | 58      | infra |
| `helixpay/core/fees/br_locale.py`                            | 44      | core  |
| `helixpay/loyalty/tap_bridge.py`                             | 22      | loyalty |

The fact that `tap_bridge.py` is the fifth most-modified file despite the team being
under-resourced for Tap-Loyalty work is a signal of how often we touch it for partial
fixes that don't fully land.

## Caveats

- This analysis uses commit count as a proxy for contribution. It penalizes squash-merge
  cultures and over-credits chatty branches. Do not use as a perf review input.
- Some Brasil engineers commit primarily under `@helixpay.com.br` aliases that were
  added mid-quarter. We've reconciled the obvious ones; small attribution errors
  remain.
- The Confluence tag heuristic (branch prefix `confluence/*` or `merchant-id/*`, or
  PR label `confluence`) is approximate — undercounts ad-hoc work, overcounts when
  someone reuses the prefix for unrelated changes.

— Vikram, 2026-04-08
