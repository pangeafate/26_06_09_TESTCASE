---
sprint_id: SP_016
tier: Foundational
features: [decouple-deploy-from-fullrun, ci-deploy-job, app-live-mcp, governed-full-run, prod-seed-transfer, live-behavioral-closure]
user_stories: []
schema_touched: false
structure_touched: true
status: In Progress
isolation: branch-only
branch: sprint/SP_016-live-deploy
worktree: ""
agent_owner: "Agent 5 (infra/deploy)"
fix_type: "operator-observable: the recall + contradiction behaviour must be replayed against the DEPLOYED live system (Rule 21 closure) — 502 endpoint, no live answers"
dependencies: [SP_014, SP_015]
dev_dependencies: []
touches_paths:
  - deploy/deploy.sh
  - deploy/README.md
  - deploy/tests/test_infra_contract.py
  - .github/workflows/deploy.yml
  - scripts/prod_seed.sh
  - scripts/verify_mcp.py
  - workspace/acceptance/SP016_live_verification.md
  - PROGRESS.md
  - PROJECT_ROADMAP.md
  - PROJECT_CONTEXT.md
touches_checklist_items: [deploy-decouple-fullrun, deploy-ci-job, deploy-app-live-200, deploy-mcp-agent-reachable, fullrun-through-guard, prod-seed-pgdump-restore, live-answer-quality-gate, deploy-doc-reconcile]
---

# SP_016: Functional live system — gated deploy + the one governed full run

## Sprint Goal

Turn `https://helixpay.serverado.app` from a **502** into a **functional live system** an
agent can query — deployed CI/CD-first (CLAUDE.md Rule 11), through the SP_015 hard-rule
gate, with the recall + contradiction behaviour **replayed against the deployed system**
(Rule 21 behavioural closure for the whole recall saga).

End state: the public URL returns 200; `/mcp` speaks streamable-HTTP and an external agent
can list + call tools; the production DB is **fully populated by the single governed full
extraction** (44 docs, real 1024-dim Voyage embeddings); and a live `ask()` over the golden
questions shows **recall ≥85%, zero uncited claims, and both planted contradictions
surfaced**.

This sprint deploys the app and runs the one full extraction. It depends on **SP_014**
(extraction fixes + ledger) and **SP_015** (the 9/9 proof + the `scripts/full_run.py`
guard). The guard is honoured, not bypassed.

## Current State (substrate already built — SP_006, landed)

- **Compose / image / Makefile** exist and are contract-tested: `docker-compose.yml`
  (`db` pgvector-pg16 **never published**; `app` bound `127.0.0.1:8000` loopback),
  `Dockerfile` (py3.12 + uv, non-root uid 10001, `CMD uvicorn helixpay.api.app:app`),
  `Makefile` (`up|ingest|ingest-record|replay|demo|test|fmt`), `deploy/deploy.sh`,
  `deploy/nginx.conf`, `deploy/tests/test_infra_contract.py` (12 invariants green).
- **`pyproject.toml`** already consolidates the runtime deps (`fastapi`, `uvicorn[standard]`,
  `mcp`, `anthropic`, `voyageai`, …) **and** the `helixpay` console script — the SP_006
  integration TODOs are **resolved**.
- **Droplet is provisioned:** DNS `helixpay.serverado.app` A→`138.197.187.49`; **system
  nginx** vhost → `127.0.0.1:8000` (streamable-HTTP settings); Let's Encrypt TLS (HTTP→HTTPS
  301). The box is shared (pangeabot/obsidiancomments/n8n/baserow behind the same nginx) —
  **be surgical**. SSH: `ssh -i ~/.ssh/id_rsa root@138.197.187.49`.
- **Current state: 502** — nginx routes correctly to `:8000`; no app is running there yet.
- **The blocker to fix:** `deploy/deploy.sh` runs `helixpay ingest ./data` as its last step
  — an **unguarded full paid extraction** baked into deploy. That violates the SP_015 hard
  rule (no full run until proven **and** deployed, and only via the guard). It must be
  decoupled.

## Desired End State

- `https://helixpay.serverado.app/` → **200**; `/health` → 200; `/mcp` → streamable-HTTP
  handshake + a tool call round-trips for an external MCP agent.
- Deploy runs **CI/CD-first** (push `main` → CI build/test → deploy job), bringing up the
  app with **schema + seed only** (no full ingest) — the "deployed" half of the gate.
- The **single governed full extraction** (`scripts/full_run.py`) runs only after the gate
  opens, and its output seeds production (44 docs + 1024-dim embeddings + claims / links /
  contradictions).
- A live answer-quality gate proves the recall + contradiction behaviour **on the deployed
  system** (Rule 21), recorded + signed in `workspace/acceptance/SP016_live_verification.md`.
- Meta-docs reconciled **before** deploy (Rule 16); dev-gateway green (Rule 13); CI green on
  the deployed commit (Rule 11).

## Scope

**In:** decoupling the full ingest from `deploy.sh` (deploy = up + migrate + seed only); a
CI deploy job (`.github/workflows/deploy.yml`); the MCP agent-reachability verifier
(`scripts/verify_mcp.py`); the production seed-transfer path (`scripts/prod_seed.sh` —
pg_dump of the guarded local full run → restore on the droplet after `CREATE EXTENSION
vector`); the live answer-quality / behavioural-closure verification + its signed artifact;
the infra-contract test for the decoupling; the Rule-16 doc reconciliation
(PROGRESS/ROADMAP/CONTEXT, whose subject — system live — genuinely changes).

**Out (and who owns it):** the extraction code (**SP_014**); the smoke proof + the
`full_run.py` guard logic itself (**SP_015** — SP_016 *invokes* it); the query/synthesis +
provenance surface that shapes citation quality (**SP_011/012** — see Risks: ideally merged
before the Phase-C gate); the contracts/schema (**frozen**); `eval/run.py` structure
(**SP_013**). No new MCP tools, no contract changes.

## Technical Approach

### Phase A — deploy the app, MCP live (CI/CD-first, Rule 11)
1. **Decouple the full run from deploy.** Edit `deploy/deploy.sh`: drop the
   `helixpay ingest ./data` step. Deploy now = `docker compose up -d --build` → wait db
   healthy → `python -m helixpay.db.migrate` → `python -m helixpay.seed.run_seed` →
   `curl /health`. The app goes live serving the seeded backbone; the full corpus arrives
   only through the guard (Phase B). Update `deploy/tests/test_infra_contract.py` to assert
   `deploy.sh` contains **no** unguarded `ingest ./data`.
2. **CI deploy job** (`.github/workflows/deploy.yml`): on push to `main` after the existing
   dev-rules CI passes, an SSH deploy step runs `deploy/deploy.sh` on the droplet (secrets
   from GitHub Actions secrets / the box's `.env`, never echoed). Direct interactive SSH is
   emergency-only/recon (Rule 11); the CI job is the sanctioned path. Watch the run until the
   pushed commit is verified green or an actionable blocker is known.
3. **Secrets on the box.** `.env` (chmod 600, never committed) with **freshly rotated** keys
   — the keys exposed earlier in transcript are **compromised and must not be used in
   production**. `DATABASE_URL` uses host `db`; `POSTGRES_PASSWORD` matches. Never log a
   secret or a connection string.
4. **Verify live + MCP agent-reachable** (`scripts/verify_mcp.py`): assert
   `https://helixpay.serverado.app/health` is 200, then open a **streamable-HTTP** MCP
   session to `/mcp` (never stdio — stdio breaks the live URL), `list_tools`, and call one
   tool from `helixpay/mcp/server.py` end-to-end. This is the operator's definition of
   "deployed in production" and the second half of the SP_015 gate. Neighbour nginx sites
   stay 200 throughout.

### Phase B — the one governed full extraction (through the guard)
With SP_015's `workspace/acceptance/SP015_proof.md` signed (9/9 archetypes) **and**
`verify_mcp.py` green, `scripts/full_run.py` (SP_015) will open. Run the **single** full
paid extraction, then seed production:
- **Recommended — local guarded run → dump → restore** (`scripts/prod_seed.sh`): run
  `full_run.py` against the **local** DB (record over `./data`), validate the loss ledger
  locally (no silent empties/truncations on the full 44 — the SP_015 "types not instances"
  safety net fires here), `pg_dump` the populated DB, then restore on the droplet **after
  the migration's `CREATE EXTENSION vector`** so the 1024-dim vector columns load. Gentler on
  the shared 2vcpu/4gb box and validated before prod sees it; matches the
  `helixpay-replay-vs-prod-seed` reuse guidance.
- **Alternative — run-into-prod:** invoke `full_run.py` on the box against the compose DB
  directly. Satisfies the same gate; noted but not recommended (paid run on the shared box,
  no local dry-run). Operator picks at run time.
- Idempotent on `content_hash`, so an accidental re-invoke is a no-op; the guard blocks a
  second *un-gated* full run regardless.

### Phase C — live behavioural closure (Rule 21) + delivery
- **Answer-quality gate (the deferred paid `ask()`, once):** against the **live** system,
  `ask()` the golden questions (`eval.run` Level-2, Opus) and assert: **recall ≥85%** over
  the `recall_bar:true` facts, **zero uncited claims**, **both planted contradictions present
  in `AnswerBundle.contradictions`**, the two-Marias/two-Tans stay distinct. Record verdicts
  + the live endpoint evidence in `workspace/acceptance/SP016_live_verification.md`. This is
  the Rule-21 replay of the original recall symptom against the deployed system — the close
  of the recall saga (SP_010→016).
- **Stage 6 docs → Stage 7 delivery (Rule 16, then 11):** reconcile PROGRESS / ROADMAP /
  CONTEXT to "system live, full corpus served" **before** the final deploy/tag; run
  `dev-gateway --stage manual` green (Rule 13); push; watch CI to verified-green.

## Testing Strategy

- `deploy/tests/test_infra_contract.py` (extend) — `deploy.sh` performs up+migrate+seed and
  **does not** run an unguarded full `ingest ./data`; compose invariants (db unpublished,
  app loopback-only) still hold; `.github/workflows/deploy.yml` exists and gates on CI.
- `scripts/verify_mcp.py` — unit-level: streamable-HTTP transport selected (asserts **not**
  stdio); a mocked `/mcp` session lists ≥1 tool and a tool call round-trips; a 502/handshake
  failure exits non-zero (so it's a real gate, not a log line).
- `scripts/prod_seed.sh` — dry-run asserts the order `CREATE EXTENSION vector` → restore;
  refuses if the dump predates a signed `SP015_proof.md` (no ungated prod seed).
- **Live acceptance (paid, operator, DB-gated):** Phase A `verify_mcp.py` green → Phase B
  one full run + seed → Phase C live `ask()` gate green → sign `SP016_live_verification.md`.
  Recorded as pending operator smoke with exact steps (Rule 21).

## Cost & Sequencing

- **Phase A is $0** (deploy + seed + MCP verify — no LLM). Can proceed as soon as SP_014 is
  merged; it does **not** wait on the smoke loop (deploy serves the seeded backbone first).
- **Phase B is the one paid full run** (~1 h, Sonnet+Voyage over 44 docs) — the only
  sanctioned full extraction, blocked until proven+deployed.
- **Phase C is one paid Opus pass** (the golden questions) — the deferred answer-quality gate,
  run **once** against live.
- Order: SP_014 merge → Phase A deploy + MCP verify → (SP_015 proof signed) guard opens →
  Phase B full run + prod seed → Phase C live gate → docs + tag.

## Risks & Mitigations

- **One-per-type proved *types*, not *instances* (carried from SP_015).** The full run is the
  first 44-doc exposure since the fixes. Mitigation: the **loss ledger runs on the full run**
  (Phase B, locally) — an unrepresented dense instance fails *loudly*, not silently, before
  prod is seeded.
- **Shared 2vcpu/4gb box.** A 44-doc paid extraction (pdfplumber + embeddings) could strain
  neighbours. Mitigation: recommended path runs the full extraction **locally**, ships a
  `pg_dump`; the box only does a restore. nginx changes stay surgical (neighbour sites 200).
- **Compromised API keys.** The keys exposed in transcript must **not** reach prod.
  Mitigation: rotate before Phase A; `.env` chmod 600, never committed; secrets via env only.
- **pgvector dump/restore.** A naive restore fails without the extension. Mitigation:
  `prod_seed.sh` enforces `CREATE EXTENSION vector` (the migration) **before** restore; the
  1024-dim columns and the generated `tsv` are preserved by the dump.
- **Citation quality depends on SP_011/012.** The Phase-C "zero uncited claims" /
  contradiction-surfacing gate exercises the query/synthesis + provenance surface. If
  SP_011/012 aren't on `main`, Phase C measures whatever is deployed. Mitigation: prefer
  merging SP_011/012 before Phase C; otherwise record the as-deployed result and gap.
- **Accidental second full run / re-bill.** Mitigation: the guard refuses ungated runs;
  ingestion is idempotent on `content_hash` (a re-run is a no-op).
- **MCP transport.** stdio works locally but breaks the live URL. Mitigation: streamable-HTTP
  enforced + asserted by `verify_mcp.py`.
- **Deploy before docs (Rule 16).** Mitigation: PROGRESS/ROADMAP/CONTEXT reconciled in this
  sprint's Stage 6 **before** the Stage 7 tag; only docs whose subject changed (Rule 7).

## Success Criteria

- `https://helixpay.serverado.app/` → 200; `/health` → 200; `/mcp` streamable-HTTP session
  lists tools and a tool call round-trips for an external agent (`verify_mcp.py` green).
- `deploy.sh` no longer runs an unguarded full ingest; CI deploy job green on the deployed
  commit; neighbour nginx sites unaffected.
- Production DB populated by the **single guarded** full run: 44 docs, real 1024-dim
  embeddings, claims/links/contradictions present.
- Live `ask()` over the golden questions: **recall ≥85%** (`recall_bar` facts), **zero
  uncited claims**, **both contradictions surfaced**, name-traps distinct.
- `workspace/acceptance/SP016_live_verification.md` signed with live-endpoint evidence
  (Rule 21 closure).
- `uv run pytest test` + `uv run pytest deploy/tests` green; `uv run mypy helixpay` clean;
  `dev-gateway --stage manual` green; meta-docs reconciled.

### Pre-Implementation Review

> Foundational tier — review-iteration floor = 2 (`practices/GL-SELF-CRITIQUE.md`).
> `fix_type` set (live behavioural closure) → **Rule 21**: the recall + contradiction symptom
> must be replayed against the **deployed** system at close-out, not asserted.
> Both iterations completed before implementation. Findings folded in below.

- **Iteration 1 — Architect-Reviewer** (phasing, deploy/full-run decoupling, CI-first vs SSH):
  - CRITICAL-A1: `deploy.sh` must contain **no** `helixpay ingest ./data` call — removing it is
    the core Phase A deliverable. Infra test `test_deploy_sh_contains_no_unguarded_ingest`
    asserts this invariant. FOLDED IN: `deploy.sh` rewritten with ingest step removed.
  - HIGH-A3: `verify_mcp.py` must exit non-zero on handshake failure (real gate, not a log line).
    FOLDED IN: `probe()` returns `False` on any exception; `main()` propagates to non-zero exit.
  - MEDIUM-A4: `prod_seed.sh` SP015 check must use the TEMPLATE marker (grep-based), not file
    modification time. FOLDED IN: `grep -q "TEMPLATE" "${PROOF_PATH}"` is the guard.
  - LOW-A5: `git pull` in `deploy.sh` is dual-mode (manual + CI). Kept with explanatory comment.
  - Phase A fully satisfies "deployed" half of the gate: the app serves the seeded backbone;
    `verify_mcp.py` confirms the public MCP endpoint; `full_run.py`'s `_default_mcp_check` then
    opens the gate for Phase B. Phase A alone does NOT constitute the full gate (no signed proof
    + full corpus yet) — recorded as pending operator smoke.

- **Iteration 2 — Security-Auditor** (key rotation, secret handling, pg_dump/restore, nginx):
  - CRITICAL-S1: Compromised keys must not reach prod. FOLDED IN: `deploy.sh` header warns
    explicitly; `deploy/README.md` updated; acceptance template documents key rotation as
    operator step 1.
  - CRITICAL-S2: `prod_seed.sh` must never echo `DATABASE_URL` / DSN. FOLDED IN: `_safe_db_host`
    helper strips credentials; all log output uses only host+dbname.
  - HIGH-S3: Nginx blast radius — this sprint makes NO nginx changes. Zero risk. CONFIRMED.
  - HIGH-S4: `CREATE EXTENSION vector` must precede `pg_restore`. FOLDED IN: `prod_seed.sh`
    runs `python -m helixpay.db.migrate` (step 1) before `pg_restore` (step 3); test
    `test_migration_before_restore_in_script` asserts line-order invariant.
  - HIGH-S5: CI SSH key — FOLDED IN: `deploy.yml` uses `ssh-keyscan` to populate known_hosts
    (avoids `StrictHostKeyChecking=no`); key stored only in `secrets.DEPLOY_SSH_KEY` and
    removed in `if: always()` cleanup step.
  - MEDIUM-S6: `verify_mcp.py` logs host only on failure. FOLDED IN: all `print()` calls use
    `urlsplit(url).hostname` not the full URL.
  - MEDIUM-S7: `pg_restore` idempotency. FOLDED IN: `--clean --if-exists` flags present;
    test `test_restore_uses_clean_and_if_exists` asserts both flags.

### Post-Implementation Review

> Plan-blind review over changed code/config + tests after `pytest` passes and before the
> live deploy (Rule 9). Floor = 2 for Foundational. Reviewed by an independent plan-blind
> `security-auditor` (Rule 5).

- **Iteration 1** — independent plan-blind `security-auditor`. Verdict **SHIP-WITH-FIXES**.
  Every finding verified against evidence (`uv run pytest deploy/tests test/unit/scripts`,
  `bash -n`, live `sed`/`urlsplit` harnesses) and resolved:
  - **CRITICAL C1 — `pg_restore --dburl=` is not a real flag** → every production restore
    would abort under `set -e`; the grep-only test never executed the command so it passed
    green. **Resolved:** `--dbname=` (accepts a URI) + a test asserting no `--dburl` and
    requiring `--dbname`/`-d`.
  - **HIGH H1 — `_safe_db_host` leaked an `@`-containing password** (sed matched only to the
    first `@`). **Resolved:** reparsed with Python `urlsplit` (splits userinfo on the last
    `@`); isolated-function tests over `@`/`:`-in-pass, IPv6, passwordless.
  - **HIGH H2 — the seed guard was decorative** (greps markdown for `TEMPLATE`). **Resolved:**
    a Step-0b gate binds the seed to the **machine JSON** `SP015_smoke_result.json` (the same
    source of truth `scripts/full_run.py` uses) — refuses unless `all_green` + every doc
    `verdict == PASS`; missing/not-green/green tests added.
  - **MEDIUM M1 —** `verify_mcp.py` called an arbitrary first tool with `{}` (could bill paid
    `ask` / false-negative). **Resolved:** `initialize` + `list_tools()≥1` is the round-trip;
    no blind `call_tool`.
  - **MEDIUM M2 —** dump could linger on failure + ungitignored. **Resolved:** `trap … EXIT` +
    `*.pgdump`/`.prod_seed_dump.pgdump` in `.gitignore`.
  - **MEDIUM M3 —** no CI deploy concurrency guard. **Resolved:** `concurrency: { group:
    deploy-prod, cancel-in-progress: false }`.
  - **LOW L1 —** removed dead env-parsing loop; **NIT N1** test-only coroutine warning tidied.
  - Confirmed SOUND: no unguarded `ingest` in deploy.sh; pgvector restore ordering (migrate →
    `CREATE EXTENSION vector` → restore) with no neighbour blast radius; MCP streamable-HTTP
    only (stdio never imported), https enforced, 502/handshake exit non-zero; no nginx
    mutation; `deploy.yml` secrets via `secrets.*`, SSH key cleaned up `if: always()`.
    Post-fix: **49 deploy/scripts tests pass; `bash -n` clean.**
- **Iteration 2** — **pending runtime (operator, paid, Rule 21):** live 200 + `/mcp` agent
  round-trip (`verify_mcp.py`) + the Phase-C answer-quality gate as runtime evidence. Held at
  the operator boundary (rotated keys + DB required). Sprint stays **In Progress** until the
  live replay lands. See **Hand-off**.

## Hand-off

- **This is the milestone close** of the recall saga (SP_010 → 016): the live system at
  `https://helixpay.serverado.app` answers golden questions with cited claims and surfaced
  contradictions over the full corpus. `SP016_live_verification.md` is the operator-facing
  proof.
- **Operator smoke (Rule 21), exact steps:** rotate keys → `.env` on box (chmod 600) →
  push `main` (CI deploy) → `verify_mcp.py` green (200 + `/mcp` round-trip) → sign
  `SP015_proof.md` (if not already) → `scripts/full_run.py` (local) → `scripts/prod_seed.sh`
  (dump→restore) → live `eval.run` Level-2 → sign `SP016_live_verification.md`. No DB/secrets
  in the build environment.
- **Moving-target property retained:** re-running `deploy.sh` converges (idempotent
  migrate/seed); dropping a new file into `data/` + a gated `full_run.py` re-records only the
  new doc (idempotent on `content_hash`).
- **Standing rule:** the only sanctioned 44-doc extraction remains `scripts/full_run.py`
  behind the proof+MCP gate — no ad-hoc `make ingest`/`record ./data` in production.
