---
sprint_id: SP_015
tier: Standard
features: [one-per-type-smoke, archetype-proving-loop, embedding-retrieval-sanity, full-run-governance-gate]
user_stories: []
schema_touched: false
structure_touched: false
status: In Progress
isolation: branch-only
branch: sprint/SP_015-one-per-type-proving
worktree: ""
agent_owner: "Agent B (recall)"
dependencies: [SP_014]
dev_dependencies: []
touches_paths:
  - eval/smoke/__init__.py
  - eval/smoke/manifest.py
  - eval/smoke/build_smoke.py
  - eval/smoke/check_smoke.py
  - scripts/full_run.py
  - workspace/acceptance/SP015_proof.md
  - .gitignore
  - test/unit/eval/test_smoke_builder.py
  - test/unit/eval/test_check_smoke.py
  - test/unit/scripts/test_full_run_guard.py
touches_checklist_items: [smoke-manifest-one-per-type, smoke-corpus-builder, smoke-per-doc-check, smoke-embedding-retrieval-sanity, full-run-proof-artifact, full-run-mcp-healthcheck, full-run-guard-refuse]
---

# SP_015: One-per-type proving loop + the "no more full runs" gate

## Sprint Goal

Prove the SP_014-fixed pipeline extracts **every document archetype correctly, with all
metadata**, on a minimal **one-document-per-type** corpus — iterating at the lowest
possible paid cost — and **encode the hard rule as a machine-enforced gate**:

> **No full run (record over all 44 docs / `./data`) is permitted until BOTH (a) all nine
> archetypes pass the proving bar, AND (b) the app is deployed in production with the MCP
> endpoint live and reachable by agents.**

This sprint delivers the cheap proving loop + the gate. It does **not** run the full
corpus and does **not** deploy — the production deployment and the single governed full
extraction are the gated follow-on (**SP_016**, outlined in Hand-off). The gate defined
here is what SP_016 must satisfy before it may run anything full.

Per the operator's decisions for this work:
- **Type = content archetype** (~7–8 → in fact **9**, see set below), not file format.
- **Proof bar = existing golden facts + loss-ledger eyeball** (no hand-authored per-doc
  oracle). Every chosen doc is golden-bearing, so the cheap bar has signal on all nine.
- **Per iteration = extract + Voyage embed + persist only** (no paid `ask()`; answer-quality
  is deferred to one final pre-deploy gate in SP_016).
- **"Deployed in production" = app deployed + MCP available for agents** (the gate's second
  half).

## Current State

- The full corpus is 44 docs across 9 archetypes (`find data -type f`). The existing
  `eval/sample/` is an 11-doc trap-coverage subset — good for contradictions, but it is
  **not** one-per-type (it carries 3 of one type, 0 of others like `chat/`) and it iterates
  at ~11 docs.
- SP_014 (dependency) adds the loss ledger, the `coerce`-then-validate step, and the
  truncation fix — the instruments this sprint reads to judge "no silent loss."
- `record` mode (SP_010, `helixpay.ingest.replay record`) extracts + embeds (Voyage
  1024-dim) + persists to a real DB, idempotent per `(source_uri, ordinal)`; `--force`
  re-extracts. This is the per-doc paid unit.
- There is **no** per-type smoke corpus, **no** per-doc completeness/correctness checker,
  and **no** guard preventing an accidental full run — the hard rule is currently only an
  intention.

## The one-per-type set (9 archetypes, all golden-bearing)

Exactly one document per type, each chosen because it **both** exercises the archetype's
metadata shape **and** carries ≥1 golden fact (so the golden+ledger bar can score it):

| # | Archetype | Document | Golden / metadata signal it proves |
|---|-----------|----------|-------------------------------------|
| 1 | plain-md / overview | `data/overview.md` | company-level metrics; baseline markdown |
| 2 | pdf / board-deck | `data/board-deck-q1-2026.pdf` | revenue 14.2M, NPS 47, Confluence end-Q3 (contradiction side); pdf path |
| 3 | html / dashboard | `data/dashboards/april-2026-kpi-dashboard.html` | revenue 14.2M + NPS 47 **with as-of date**; dense → Defect-A trigger |
| 4 | email | `data/email/customer-acai-express-thread.md` | Maria **Santos** owns Açaí (ownership link; two-Marias side A) |
| 5 | interview | `data/interviews/sales/maria-silva.md` | Maria **Silva** Brasil revenue 4.8M (two-Marias side B; name disambiguation) |
| 6 | org-chart | `data/org-chart.md` | Daniel→Arjun→Wei, Sara→Daniel (link **direction**), headcount 274; dense |
| 7 | code-analysis | `data/code/contributors-analysis-q1-2026.md` | Sara Wijaya top contributor; Daniel Tan vs Tan Wei Ming (two-Tans) |
| 8 | chat / slack | `data/chat/sales-floor-april.md` | golden-bearing chat log; informal multi-speaker shape |
| 9 | image / vision | `data/images/revenue-trend-q1-2026.jpeg` | vision-caption extraction; the fidelity-loss path (`research/image-ingestion-fidelity-loss.md`) |

Alternates (same type, **not** picked, noted for intra-type variance risk): pdf
`q1-2026-results.pdf`; dashboards `q4-2025-kpi-dashboard.html` / `sales-pipeline-2026-04-21.html`;
email `cosmos-hotels-debrief.md`; images `org-chart-snapshot.jpeg` / `nps-by-segment-q1-2026.jpeg` /
`merchant-reconciliation-bug.jpeg`.

## Scope

**In:** the one-per-type manifest + smoke corpus builder (analogous to `build_sample.py`);
a per-doc completeness+correctness checker (golden read-out + ledger inspection + a $0
embedding/retrieval sanity); the `full_run.py` guard that refuses a full extraction unless
proven+deployed; the committed proof artifact; their unit tests.

**Out (and who owns it):** the SP_014 extraction fixes themselves (**SP_014**, dependency);
`eval/run.py` / `DEFAULT_RECALL_BAR` / harness structure and the existing `eval/sample/`
(**SP_013** — this sprint adds a sibling `eval/smoke/`, edits neither); `replay.py` / make
targets (**SP_010**); the production deployment, MCP-live, and the governed full run
(**SP_016**); `ask()` / answer-quality (deferred to SP_016's final gate).

## Technical Approach

### Smoke corpus (`eval/smoke/manifest.py`, `eval/smoke/build_smoke.py`)
- `manifest.py`: the 9-tuple `(archetype, source_uri, why)` above — the single source of
  truth for "one per type."
- `build_smoke.py` (deterministic, no network/DB, mirrors `build_sample.py`): copy each doc
  into `eval/smoke/data/<same subpath>` so `source_uri` matches the golden refs verbatim
  (root `data` so cache files are cleanly named, no `._` prefix), and **filter** the
  verified golden set to those 9 source_uris into `eval/smoke/facts.yaml` — a traceable
  subset, never re-labeled.

### The cheap loop (paid, ~9 docs/iteration, Sonnet+Voyage only)
1. One-time: isolated DB `helixpay_smoke` (own gitignored env file, same pattern as the
   sample README) — `migrate` + `seed` the deterministic backbone.
2. Each iteration: `--force` record **only the docs whose extraction inputs changed** — a
   code/prompt change forces all 9; a single-doc fix forces 1 (record is idempotent per
   `(source_uri, ordinal)`, so done chunks aren't re-billed). Extract + embed + persist;
   **no `ask()`**.
3. Run `check_smoke.py` (below). Iterate until all 9 pass.

### Per-doc proving bar (`eval/smoke/check_smoke.py`) — golden + ledger
For each of the 9 docs, three signals:
- **Completeness (ledger, the no-silent-loss proof):** `empty_extractions == 0` and
  `truncated_calls == 0` (post the SP_014 8192 bump) for that doc; every `items_dropped`
  is **0 or human-explained** in the run notes (genuine chrome, not a metadata loss). This
  is where the ledger earns its place — it converts the previously-silent loss into a
  per-doc number a human can sign off.
- **Correctness (golden):** every golden fact pinned to that doc's `source_uri` is **FOUND**
  via `eval.run --golden eval/smoke/facts.yaml` (value + as_of + provenance; links
  direction-correct). Golden-precision 100% over the smoke facts.
- **Metadata eyeball (the operator-accepted judgement layer):** `check_smoke.py` dumps the
  persisted claim/link rows for the doc (subject→resolved entity id, predicate, value,
  **as_of**, source provenance, confidence) so a human confirms as_of present+correct,
  provenance present, the subject resolved to the **right roster id** (not a minted dupe),
  and no uncited value — on docs/fields the sparse golden set doesn't cover.
- **Trap preservation:** `resolve_entity("Maria")` / `("Tan")` still return `None`; the four
  full-name people resolve to four distinct ids; any contradiction touching a chosen doc
  still surfaces.

### Embedding sanity ($0, addresses "run the new embedding")
> **Stage-3 correction (architect):** the original draft called `repository.search_chunks(text)`.
> That method does not exist — the frozen contract is `search_semantic(qvec, k)` (takes a
> **vector**, not text) + `search_lexical(q, k)` (`contracts/repository.py:92,95`). A true
> vector-retrieval check would need a **paid** `embed_query` per doc — not $0. So the $0
> guarantee and the method were both wrong.

Corrected, **$0**, DB-only: after record, for each doc assert its persisted chunks carry a
**non-null, non-zero-norm 1024-dim embedding** (`SELECT count(*) … WHERE document_id=? AND
embedding IS NOT NULL`, plus a norm check). This directly catches the failure the plan cares
about — a zero-vector / misconfigured embed path — with **zero** API calls. A *true*
vector-retrieval top-hit check (`embed_query` + `search_semantic`) is **optional and paid
(cents)**; if wanted, it is labelled paid, not folded into the $0 loop.

### The hard-rule gate (`scripts/full_run.py` + machine proof)
> **Stage-3 correction (security + architect):** the original draft was **theatre** on three
> counts, all folded in below: (a) the proof was a human-edited "signed" markdown flag —
> trivially forged; (b) the "deployed" check hit `/health`, which **always** returns ok and
> says nothing about MCP — and the engine silently falls back to `MockQueryEngine` when
> `DATABASE_URL` is unset (`api/app.py:37-39,87-90`); (c) the wrapper is **bypassable** —
> `make ingest`, `make ingest-record`, `python -m helixpay.ingest.replay record ./data`, and
> `deploy/deploy.sh:40` all reach the paid extractor (`pipeline.run → AnthropicClient`)
> without ever importing the guard. **As scoped, this guard is ADVISORY, not enforcing.**

`scripts/full_run.py` is the **sanctioned** entry to a 44-doc record. It **refuses** (exit
non-zero, **zero** API calls, no `record`-mode construction on the refusal branch —
`replay.py:135` builds `AnthropicClient` eagerly, so the decision must precede it) unless
**both**:
1. **Proven — re-derived, not trusted.** `check_smoke.py` emits a **machine-readable JSON**
   result (9 per-doc verdicts + the content hashes of the 9 docs + golden subset). The guard
   **recomputes** the doc hashes and requires 9/9 green; a stale or hand-edited proof fails
   the hash/verdict check. The human `SP015_proof.md` narrative records the run for people but
   **gates nothing mechanical** — the guard never trusts a typed flag.
2. **Deployed — a real MCP round-trip.** Open a **streamable-HTTP** MCP session to
   `HELIXPAY_PROD_MCP_URL` (env via `helixpay.config` conventions; HTTPS required; stdio
   rejected), `initialize`, call a tool (e.g. `get_sources`), and assert a structurally valid
   MCP response **from the real engine, not the mock**. `/health` is explicitly **forbidden**
   as the gate signal. On failure, log host only — never the full URL or any DSN.

**Enforcement honesty (the open fork — see Hand-off):** closing the bypass doors for real
needs an authorization chokepoint at the shared paid path (`helixpay.config` /
`pipeline.run` / `llm.py`) that every entry reads — which is **production substrate** and
overlaps **SP_014** (`llm.py`) and **SP_016** (`deploy.sh:40`). That crosses this Standard
sprint's scope (DEV_RULES "stop and re-plan" trigger: unlisted substrate files). This sprint
ships the **sanctioned, re-derived, non-forgeable advisory guard**; true machine enforcement
is deferred to a coordinated change (operator decision pending).

## Testing Strategy

- `test/unit/eval/test_smoke_builder.py` — the 9-tuple manifest is one-per-type (no
  archetype repeated, none missing); `build_smoke.py` copies all 9 and filters golden to
  exactly their source_uris; re-run is deterministic.
- `test/unit/scripts/test_full_run_guard.py` — guard **refuses** when the proof artifact is
  absent/unsigned (asserts **no** `record`/`AnthropicClient` invoked); refuses when the MCP
  health check fails; **permits** only when both pass (mocked). The refusal path makes zero
  paid calls.
- `check_smoke.py` self-test: with a seeded fixture DB, a doc whose golden fact is FOUND +
  ledger-clean passes; a doc with a silent empty (ledger `empty_extractions>0`) **fails**
  even if it has no golden fact (completeness catches what golden can't).
- **Acceptance (paid, DB-gated — the proving loop itself):** `helixpay_smoke` up → record
  the 9 docs → `check_smoke.py` green on all 9 → write+sign `SP015_proof.md`. Recorded as
  pending operator smoke with exact steps.

## Cost & Sequencing

- **Per iteration:** 9 docs, Sonnet extract + Voyage embed (1 vision call for the image),
  **no Opus** — minutes and cents, vs ~1 h / full Opus-inclusive for the corpus.
- **Total paid surface until the gate opens:** N×(9-doc record). Budget ~2–4 iterations.
  This is the *entire* sanctioned paid spend until SP_016 — the guard blocks everything else.
- **Order:** SP_014 merges → build smoke corpus → loop until 9/9 → sign proof → (SP_016)
  deploy app+MCP → guard passes → **one** governed full run.

## Risks & Mitigations

- **Intra-type variance — one doc may not represent its whole type.** Images (4 very
  different: chart, org snapshot, bug screenshot, nps) and dashboards (3 layouts) have the
  widest spread; the chosen image/dashboard proves the *path*, not every instance.
  Mitigation: the **loss ledger runs on the SP_016 full run too**, so an unrepresented
  dense instance can't fail *silently* — it surfaces as a ledger non-zero against prod,
  observable and fixable. State this limitation in the proof artifact; do not claim the
  9-doc pass proves every instance, only every *type*.
- **Golden+ledger bar is completeness-strong, correctness-partial.** Golden facts are
  sparse; for fields with no golden, "correct" rests on the eyeball. Mitigation: the ledger
  guarantees nothing was *dropped*; the eyeball dump makes the *correctness* judgement
  explicit and reviewable. (A hand-authored per-doc oracle was offered and declined — noted
  so the residual subjectivity is a recorded, accepted choice.)
- **Image/vision is the fragile, paid-per-call type.** Known fidelity loss
  (`research/image-ingestion-fidelity-loss.md`). Mitigation: it's its own archetype with
  its own pass/fail; if it can't clear the bar, that blocks the gate (correctly) and is
  surfaced before any full spend.
- **Guard bypass.** Someone could call `record ./data` directly, around the guard.
  Mitigation: the guard is the *documented* entry; additionally note in the make-target help
  (coordinate with SP_010) and the runbook that direct full `record` is forbidden pre-gate.
  A hard lock (refuse in `replay.py` itself) would edit SP_010's file — deferred to
  coordination, not done here.
- **Secret handling (CLAUDE.md §7 — Stage-3 security finding).** The committed
  `SP015_proof.md` must record the DB **name** (`helixpay_smoke`) only — **never**
  `DATABASE_URL` / any connection string; the builder must never copy a real env into
  `eval/smoke/data/`. The smoke env file (`.env.smoke` or `eval/smoke/.env`) is **not** matched
  by the bare `.env` `.gitignore` line — this sprint **adds it to `.gitignore`** so the smoke
  DB password can never be committed. The MCP health check and any error path log **host
  only**, never the full URL or a DSN-bearing exception.
- **Path coordination.** `eval/smoke/` is a new sibling to `eval/sample/` (SP_013 owns the
  harness but not this subdir); `scripts/full_run.py`, `eval/smoke/check_smoke.py` JSON output,
  and `workspace/acceptance/` are new; **no** edit to `eval/run.py`, `replay.py`, `pipeline.py`,
  `config.py`, `llm.py`, or `Makefile` (the enforcement chokepoint that *would* touch those is
  the deferred fork). Make-target wiring is deferred to coordinate with SP_010's Makefile.

## Success Criteria

- `eval/smoke/` builder produces the 9-doc one-per-type corpus + filtered golden;
  `check_smoke.py` reports per-doc completeness + correctness + retrieval sanity.
- On `helixpay_smoke`, each archetype proves **no silent loss + golden-correct + human-reviewed
  metadata** (not "100% correct on every field" — the accepted limit of the golden+ledger bar):
  ledger clean or every drop explained, golden facts FOUND at 100% precision, **$0**
  persisted-embedding assertion green, name-traps and any touched contradiction intact. A doc
  whose completeness is unverifiable (ledger absent, pre-SP_014) reports **INCOMPLETE**, never
  PASS.
- `scripts/full_run.py` **refuses** unless it re-derives 9/9 green from `check_smoke`'s machine
  output (hash-checked, not a typed flag) **and** a real `/mcp` round-trip succeeds; **permits**
  only with both. Unit-proven: **constructors** of `AnthropicClient`/`VoyageEmbedder` are never
  called on the refusal path (zero paid surface). Note: the guard is **advisory** — the bypass
  doors (`make ingest`/`ingest-record`, `replay record`, `deploy.sh:40`) are documented as
  forbidden; true enforcement is the deferred chokepoint fork.
- `workspace/acceptance/SP015_proof.md` written and signed with the per-doc evidence.
- `uv run pytest test` green; `uv run mypy helixpay` clean.

### Pre-Implementation Review

> Standard tier — review-iteration floor = 2 (`practices/GL-SELF-CRITIQUE.md`). Run at
> Stage 3 before implementation by two independent reviewers. **Both ran; findings folded
> into the design above.** The review hit the DEV_RULES "stop and re-plan" trigger (real
> enforcement needs unlisted substrate files) — implementation paused for the operator's
> enforcement-scope decision (see Hand-off fork).

- **Iteration 1** — architect-reviewer, plan-as-written. Files: build_sample.py, eval/run.py,
  eval/models.py, repository.py, contracts/repository.py, mcp/server.py, config.py, CLAUDE.md.
  - **CRITICAL:** retrieval sanity calls non-existent `search_chunks`; the frozen contract is
    `search_semantic(qvec)` / `search_lexical(q)`, and a true embedding test needs a **paid**
    `embed_query` — so "$0 vector retrieval" was triply wrong. **Resolved:** replaced with a
    $0 persisted-embedding DB assertion (non-null, non-zero-norm); paid vector check optional.
  - **HIGH:** the SP_014 ledger is a backward dep on an unbuilt interface; absent-ledger must
    never read as PASS. **Resolved:** define a minimal `for_source(uri)->{empty,truncated,
    dropped}` Protocol; absent ledger → loud `INCOMPLETE`, never green.
  - **HIGH:** "signed markdown" proof is forgeable; guard must re-derive. **Resolved:** machine
    JSON + hash recompute (gate section).
  - **MEDIUM:** success phrasing "every type extracts correctly with all metadata" overstates
    the bar. **Resolved:** downgraded to "no silent loss + golden-correct + human-reviewed
    metadata" in Success Criteria.
- **Iteration 2** — security-auditor, adversarial. Files: Makefile, replay.py, pipeline.py,
  deploy.sh, config.py, api/app.py, mcp/server.py, eval/run.py, .gitignore.
  - **CRITICAL (gate fails open):** `make ingest` / `ingest-record` / `replay record ./data`
    / `deploy.sh:40` all reach the paid extractor without the guard — the gate is **advisory**.
    Real enforcement needs a config-level auth chokepoint (substrate; SP_010/014/016 overlap).
    **Resolved (scoped):** ship the sanctioned advisory guard; **fork** the enforced chokepoint
    to a coordinated change (Hand-off). `deploy.sh:40` fix belongs to SP_016 (already planned).
  - **CRITICAL (forgeable proof) / HIGH (lying health check):** folded into the gate section
    (re-derive from machine output; real `/mcp` round-trip, not `/health`, assert real engine
    not mock).
  - **HIGH (paid-call leak):** tests must assert **constructors** of `AnthropicClient` /
    `VoyageEmbedder` are never called on refusal/`check_smoke` (not just `.extract()`);
    `check_smoke` must call `eval.run.check_extraction` (Level 1) **only**, never `run()`/
    `main()` (which calls Opus `ask()`). **Resolved:** encoded in Testing Strategy.
  - **HIGH (secret leak):** the committed proof must record DB **name only**, never
    `DATABASE_URL`; the smoke env file (`.env.smoke`/`eval/smoke/.env`) is **not** matched by
    the bare `.env` `.gitignore` line — must be added. **Resolved:** see Risks + Scope.

### Post-Implementation Review

> Plan-blind review over changed code + tests after `pytest` passes and before the paid
> smoke loop (Rule 9). Floor = 2. Iteration 1 ran; iteration 2 is DB-gated runtime (pending
> operator smoke). **Scope note:** only the SP_014-independent slice is implemented — the
> builder, the pure checker logic + the `check()` skeleton (pluggable ledger/embedding
> probes), and the advisory guard. The ledger/embedding probe wiring and the paid 9-doc run
> are operator/SP_014-gated.

- **Iteration 1** — code-reviewer, plan-blind over the changed code + tests
  (`manifest.py`, `build_smoke.py`, `check_smoke.py`, `full_run.py`, `.gitignore`, proof
  template, 3 test files). **0 CRITICAL.** Verified: INCOMPLETE-never-PASS holds (absent
  ledger / zero-norm embedding / golden-MISSING never yield PASS); the gate re-derives from
  per-doc verdicts + content hashes and trusts no typed flag; `.gitignore` is safe (explicit
  entries, `.env.example` not swallowed); no raw SQL outside `helixpay/db/` (embedding is a
  pluggable probe). 2 HIGH + 3 MEDIUM/LOW, all test-coverage/robustness gaps, **fixed
  pre-merge**:
  - HIGH — the lazy-import refusal test was vacuous for the *default* runner. **Fixed:** added
    `test_default_record_runner_not_imported_on_refusal` (real default, asserts
    `helixpay.ingest.replay` unimported on refusal).
  - HIGH — the "no paid surface" grep guard missed `from eval.run import run` (→ paid
    `ask()`). **Fixed:** added to the forbidden list; guard now ignores comment lines.
  - MEDIUM — `mcp_check()` could crash `gate()`. **Fixed:** wrapped → refusal, not traceback.
  - MEDIUM — dead `load_golden` re-export removed; `all_green` documented as deliberately
    not trusted by the gate.
  - LOW — determinism test now also asserts `corpus_fingerprint` byte-stability across builds.
  - Re-ran: `test/unit/eval` + `test/unit/scripts` → **24 passed**; full suite **374 passed,
    36 skipped** (no regressions).
- **Integration (post-SP_014, now landed).** The SP_014 ledger interface is on disk, so the
  previously-deferred probe wiring is implemented: `check_smoke.ledger_probe_from(ledger)`
  adapts SP_014's zero-arg `LossLedger.probe()` into the per-URI `LedgerProbe` `check()`
  expects (a URI the ledger never recorded → `None` → INCOMPLETE, never a silent PASS), and
  `embedding_probe_from(mapping)` adapts a materialised embedding-audit result. A cross-sprint
  seam test (`test/unit/eval/test_ledger_seam.py`, 8 cases) exercises the **real** `LossLedger`
  end-to-end through the verdict bar (clean→PASS, empty/truncated→FAIL, drop→INCOMPLETE,
  unseen→INCOMPLETE) so a drift in either sprint's shape fails here. `test/unit/eval`
  **16 → 24 passed** (+8 seam); the no-paid-surface guard still holds (the adapters add no
  answer surface). The remaining DB/embedding probe is injected by the operator harness at smoke time.
- **Iteration 2** — pending runtime (DB-gated, paid): build the smoke corpus, record the 9
  docs on `helixpay_smoke`, run `check()` with the now-wired SP_014 ledger + embedding probes,
  emit `SP015_smoke_result.json`, and confirm 9/9 (or the honest INCOMPLETE if a doc loses
  data). Recorded as pending operator smoke (Rule 21).

## Hand-off

- **OPEN FORK (operator decision) — advisory vs enforced gate.** Stage-3 security review
  proved the gate is **advisory**: `make ingest`/`ingest-record`, `replay record ./data`, and
  `deploy.sh:40` all spend the full paid extraction without the guard. **Option A (shipped by
  this sprint):** the sanctioned, re-derived, non-forgeable advisory guard + documented
  forbidden doors. **Option B (deferred re-plan):** a config-level authorization chokepoint at
  the shared paid path (`helixpay.config`/`pipeline.run`/`llm.py`) that every entry reads —
  real enforcement, but production substrate, Foundational, overlapping SP_014 (`llm.py`) and
  SP_016 (`deploy.sh`). Recommend folding B into SP_014's chokepoint or a small dedicated
  Foundational sprint, not bloating this one. **Until B lands, the "no more full runs" rule is
  enforced by discipline + the SP_016 `deploy.sh` decoupling, not by code.**
- **Gate hand-off to SP_016 (deploy + governed full run):** SP_016 must (1) deploy the
  proven app + schema + seed + MCP (streamable-HTTP) to the droplet and prove the endpoint
  is reachable by an agent (502→200, tool round-trip); (2) satisfy `scripts/full_run.py`
  (proof artifact signed **and** MCP health green); (3) run the **single** governed full
  extraction through the guard; (4) run the deferred `ask()` / answer-quality + contradiction
  gate once, full-corpus. Recommend SP_016 be its own **Foundational** sprint (CI/CD-first,
  external integration, Rule 11).
- **The hard rule, in one line for the runbook:** the only sanctioned 44-doc extraction is
  `scripts/full_run.py`, which will not run until `SP015_proof.md` is signed and the prod
  MCP endpoint answers. No exceptions, no ad-hoc `record ./data`.
- **Pending operator smoke (this sprint):** `helixpay_smoke` up → record the 9 → `check_smoke.py`
  9/9 → sign `SP015_proof.md`. No DB in the build environment.
