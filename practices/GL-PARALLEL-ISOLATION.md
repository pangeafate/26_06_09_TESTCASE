# Parallel-Agent Isolation

_How multiple agents work the same repository at the same time without
clobbering each other_

**Version**: 1.0
**Status**: Active Development Guidelines

---

## Philosophy

Running several agents in parallel is the single biggest throughput multiplier
available to a self-developing project — but only if the agents cannot
overwrite each other's work. The discipline that makes it safe is simple and
borrowed from how Claude Code's own team works: **each concurrent agent gets its
own working tree and its own branch, and merges back through its own pull
request.** A shared working directory with two agents editing files is a race
condition; a dedicated worktree per agent is not.

This practice makes that isolation a *declared, validated* property of every
sprint rather than an act of discipline that is easy to forget. It complements —
it does not replace — the claim-based collision prevention in
`GL-SPRINT-DISCIPLINE.md` (`touches_paths` / `touches_checklist_items`) and the
`scripts/git-hooks/commit-msg.py` foreign-claim guard. Claims tell you *who owns
what*; isolation tells you *how two owners stay out of each other's way*.

## Relationship to claim overlap (Rule 6)

`validate_sprint_overlap.py` treats `touches_paths` overlap as a **warning**, not
a failure, because two sprints touching the same directory is often legitimate
(both add a validator, both edit a shared module on disjoint lines). That stance
is deliberate and stays. This practice does **not** forbid path overlap. It
escalates the existing warning to a failure only for the one genuinely dangerous
combination: **two non-isolated, code-writing sprints, of a strict tier, editing
overlapping paths in the same working tree at the same time.** Move either
sprint into its own worktree or branch and the failure clears — the overlap
itself was never the problem, the *shared mutable working tree* was.

One honest caveat: because the FAIL keys on declared `touches_paths` overlap, an
agent could also clear it by *under-declaring* its paths rather than isolating.
That would be a discipline violation, not a fix — and it does not actually buy
safety, because the `commit-msg.py` foreign-claim guard re-checks staged files
against other sprints' claims at commit time and will refuse files an
under-declared plan tries to sneak in. Read WI-3 and the commit-msg guard as a
pair: the validator catches the planned collision early, the hook catches the
actual one at staging. Do not treat the tier escalation alone as a complete
solution.

## Isolation Modes (Authoritative)

**This table is the single authoritative source for isolation modes.** The
`isolation` frontmatter field in `templates/SPRINT_PLAN.md`, the rules in
`adapters/AGENTS.md` / `adapters/CLAUDE.md`, and the enforcement in
`validators/validate_worktree_isolation.py` all derive from it.

| Mode | What it means | Distinct branch? | Distinct working tree? | Use for |
|---|---|---|---|---|
| `read-only` | Analysis, log-reading, docs-only; no code writes | n/a | n/a | Investigation / reporting sprints |
| `shared-tree` | The main working tree, no dedicated branch | No | No | Solo work, or fully-disjoint Micro work |
| `branch-only` | A distinct branch in a separate checkout (no managed worktree) | Yes | Separate checkout | Parallel work without git worktrees |
| `git-worktree` | A dedicated `git worktree` on a dedicated branch | Yes | Yes | **Preferred** for parallel Standard/Foundational work |

An **omitted** `isolation` field is treated as `shared-tree` — the historical,
backward-compatible default. A single-stream project never needs to set it.

### Tier → required isolation

The requirement scales with the sprint's declared `tier` (see
`adapters/CLAUDE.md` for tier definitions), and only bites when **more than one
sprint is `In Progress`** — a solo sprint has no peer to collide with.

| Tier | When running alongside another active code sprint |
|---|---|
| `Micro` | May stay `shared-tree`; overlapping paths warn, never fail |
| `Standard` | Should isolate (`git-worktree`/`branch-only`); shared-tree + overlap **fails** |
| `Foundational` | Should isolate; shared-tree + overlap **fails** |
| `Precedent-Clone` | Strict (a clone may repeat any tier) — declare `tier: Micro` to relax |
| _unspecified / unrecognized_ | Treated as strict (same as Standard) — declare `tier` to relax |

The unspecified-tier fail-safe mirrors the review-iteration floor in
`GL-SELF-CRITIQUE.md`: only an explicit `tier: Micro` relaxes the rule.
`validate_worktree_isolation.py` additionally **warns** when `tier` is set to a
value outside `{Precedent-Clone, Micro, Standard, Foundational}`, so a typo that
silently fell through to strict is at least visible.

### A note on `branch-only` (and what the validator can verify)

`git-worktree` is the only mode whose tree-level isolation the validator can
*verify*: it carries a `worktree` path, and WI-2 confirms that path is unique.
`branch-only` asserts a distinct branch in a separate checkout, but there is no
checkout-path field for the validator to check — its isolation rests on the
agent actually working in a separate clone. The validator therefore exempts
`branch-only` from the shared-tree collision check (WI-3) on the strength of its
unique branch (WI-2) alone. If two `branch-only` sprints in fact share one
physical working tree, the git hooks (commit-msg foreign-claim guard) remain the
backstop. **Prefer `git-worktree` for parallel Standard/Foundational work**;
reach for `branch-only` only when you genuinely run separate checkouts.

## Naming Conventions

Keying the branch and worktree to the sprint id ties together the claim system,
the branch, the worktree, and the eventual PR under one identifier:

- **Branch**: `sprint/SP_XXX-<slug>` (e.g. `sprint/SP_042-intake-pipeline`)
- **Worktree**: `.claude/worktrees/SP_XXX` (Claude Code's `--worktree` default
  layout is `.claude/worktrees/<name>/` on a `worktree-<name>` branch; the
  sprint-scoped form is preferred here for traceability)

`validate_worktree_isolation.py` emits a **warning** when a declared `branch`
does not contain the sprint id — it does not fail, because a separate-checkout
workflow may use any branch name, but traceability is strongly preferred.

The optional `agent_owner` frontmatter field records which agent/session holds
the working tree. It is **informational only** — the validator does not read or
enforce it — but it is useful in a delivery report or when a human untangles who
was driving a stalled parallel sprint.

## Creating an isolated worktree

```bash
# native Claude Code, if your version supports it (preferred): dedicated
# worktree + branch + optional tmux. Flag/layout are owned by the Claude Code
# tool and may differ by version — `claude --help` is authoritative.
claude --worktree SP_042 --tmux

# portable fallback with plain git, keyed to the sprint:
git worktree add .claude/worktrees/SP_042 -b sprint/SP_042-intake-pipeline
```

Gitignored-but-needed files (`.env`, local config) are **not** copied into a
fresh worktree. Claude Code's native worktree support reads a `.worktreeinclude`
file at the repo root (`.gitignore` syntax) and copies matching gitignored files
into each new worktree; with the plain-git fallback above there is no such
mechanism, so copy those files into the new tree by hand. Reinstall the git
hooks in the new tree if your project does not use the worktree-aware wrapper
installer (`scripts/install-git-hooks.sh` already resolves hook sources from the
current worktree at runtime).

## One PR per sprint

Each isolated sprint merges back through **its own pull request** off its own
branch. Do not batch multiple sprints onto one branch. There is no prescribed
cross-sprint merge order — rely on the normal pre-push gateway
(`scripts/dev-gateway.py`) and PR review per branch, and resolve conflicts at
merge time like any other PR. (This mirrors observed practice: parallel agents
each open a PR independently; no special merge protocol is imposed.)

## Builder/Reviewer isolation via worktrees

`GL-SELF-CRITIQUE.md` requires that the context which wrote code is not the
context that reviews it. Worktrees strengthen that from a *convention* into a
*git mechanic*: a Stage 5 reviewer agent that runs in its own worktree
physically cannot mutate the builder's tree. Where the agent runtime supports
it, a custom reviewer agent (e.g. the quality roles in `roles/quality/`) can be
given `isolation: worktree` in its own agent frontmatter so it always spawns in
a fresh worktree — a pattern available to adopters, not a setting shipped
pre-applied to those role files.

## What this practice does NOT do

- It does not forbid `touches_paths` overlap (that remains a Rule-6 warning).
- It does not impose a merge order or a conflict-resolution protocol.
- It does not require worktrees for solo work or for read-only/analysis sprints.
- It does not enforce the branch/worktree **naming** convention or the
  one-PR-per-sprint rule at any git hook in this phase. Naming is validated only
  at the sprint-plan layer (a WI-1 WARN); no commit-msg or pre-push hook is
  branch-aware yet. Treat branch discipline as convention backed by review, not
  by a gate.

## Validator behaviour (summary)

`validators/validate_worktree_isolation.py`, wired into `validators/run_all.py`:

| Stage | Check | Outcome |
|---|---|---|
| WI-1 | unknown `isolation` value | FAIL |
| WI-1 | `git-worktree` without `worktree`, or `git-worktree`/`branch-only` without `branch` | FAIL |
| WI-1 | `branch` set but does not reference the sprint id | WARN |
| WI-2 | two active sprints share a `branch` or a `worktree` | FAIL |
| WI-3 | two non-isolated sprints overlap on paths, ≥1 strict tier | FAIL |
| WI-3 | two non-isolated **Micro** sprints overlap on paths | WARN |
| WI-3 | a strict-tier non-isolated sprint runs alongside other active code work | WARN |

Solo sprints, properly isolated parallel sprints, and plans with no `isolation`
field all pass.

---

_Parallel agents are a force multiplier only when they cannot corrupt each
other's work. Declare your isolation; let the validator hold the line._
