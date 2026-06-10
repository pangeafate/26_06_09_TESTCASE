# SP_016 — Live System Verification (operator sign-off template)

> **Status: TEMPLATE — not yet run.**
> Filled in by the operator after completing Phases B + C (the governed full run +
> live answer-quality gate). This file is the Rule-21 closure artifact for the
> recall + contradiction saga (SP_010 → SP_016).
>
> The gate is NOT mechanical — nothing reads this file programmatically. It is the
> human-facing record that the operator has verified the live system end-to-end.
>
> DB host/name only here — NEVER paste DATABASE_URL or any connection string.

---

## Phase A — Deploy + MCP live (operator, $0)

### Operator run order

1. **Rotate API keys** — any keys previously exposed in transcripts or history are
   COMPROMISED. Generate fresh `ANTHROPIC_API_KEY` and `VOYAGE_API_KEY` before
   proceeding. Record the rotation date, not the key values.

2. **Prepare `.env` on the box** (droplet `helixpay.serverado.app`):
   ```
   # On the box — NEVER commit this file, NEVER paste the URL here:
   cp /opt/helixpay/.env.example /opt/helixpay/.env
   chmod 600 /opt/helixpay/.env
   # Edit .env: fill in freshly-rotated ANTHROPIC_API_KEY, VOYAGE_API_KEY,
   # POSTGRES_PASSWORD, and DATABASE_URL (host=db, db=helixpay).
   ```

3. **Push `main` and watch CI/CD** — the `deploy.yml` workflow:
   - Runs the `gateway` job (dev-rules CI: validators, lint, unit tests).
   - If gateway passes, runs the `deploy` job (rsync + `deploy/deploy.sh` on the box).
   - `deploy.sh` sequence: `docker compose up -d --build` → wait db healthy →
     `python -m helixpay.db.migrate` → `python -m helixpay.seed.run_seed` → `curl /health`.
   - The app now serves the **seeded backbone** (deterministic entities/metrics/links).
     Full corpus is NOT loaded yet.

4. **Run `scripts/verify_mcp.py`** (locally, with `HELIXPAY_PROD_MCP_URL` set):
   ```bash
   HELIXPAY_PROD_MCP_URL=https://helixpay.serverado.app/mcp \
     python scripts/verify_mcp.py
   # Must exit 0.
   ```

### Phase A results (fill in)

| Check | Expected | Actual | Date |
|-------|----------|--------|------|
| CI `gateway` job | PASS | __ | __ |
| CI `deploy` job | PASS | __ | __ |
| `https://helixpay.serverado.app/health` | HTTP 200 | __ | __ |
| `scripts/verify_mcp.py` exit code | 0 | __ | __ |
| MCP `list_tools` returns ≥1 tool | yes | __ | __ |
| MCP tool call round-trip completes | yes | __ | __ |
| Neighbour nginx sites (pangeabot, obsidiancomments, n8n, baserow) | 200 (unaffected) | __ | __ |

**Phase A signed by:** _________________ **Date:** _________________

---

## Phase B — Full corpus load (operator, paid ~1h)

### Preconditions (all must be true before proceeding)

- [ ] Phase A complete and signed above.
- [ ] `workspace/acceptance/SP015_proof.md` is signed (9/9 archetypes, no TEMPLATE marker).
- [ ] `scripts/verify_mcp.py` exits 0 (the "deployed" half of the SP_015 gate).

### Operator run order

5. **Sign `SP015_proof.md`** if not already done (the machine proof
   `SP015_smoke_result.json` must show 9/9 PASS):
   ```
   # workspace/acceptance/SP015_proof.md — fill in the result table and sign.
   # Do NOT paste DATABASE_URL or passwords. Record DB name (helixpay_smoke) only.
   ```

6. **Run the governed full extraction locally** (this is the ONE sanctioned paid run):
   ```bash
   HELIXPAY_PROD_MCP_URL=https://helixpay.serverado.app/mcp \
     python scripts/full_run.py
   # Runs against the LOCAL DB. Calls the SP_015 gate:
   #   - re-derives 9/9 PASS from SP015_smoke_result.json (hash-checked)
   #   - confirms the live MCP endpoint is reachable
   # On permit: runs replay record ./data --cache-dir ./.replay-cache (~1h, Sonnet+Voyage)
   ```

7. **Validate the loss ledger on the full run** (44 docs — first full exposure since fixes):
   ```bash
   # The full_run.py already runs the ledger internally.
   # Check the output for any INCOMPLETE or FAIL rows.
   # Any unrepresented dense instance MUST fail loudly, not silently.
   ```

8. **Transfer to production** (`scripts/prod_seed.sh`):
   ```bash
   # LOCAL_DB and REMOTE_DATABASE_URL in .env or environment:
   REMOTE_DATABASE_URL=postgres://postgres:<pass>@helixpay.serverado.app:5432/helixpay \
     bash scripts/prod_seed.sh
   # Sequence: remote migration (CREATE EXTENSION vector) → pg_dump local → pg_restore remote
   # Uses --clean --if-exists (idempotent).
   # NEVER echoes DATABASE_URL or credentials.
   ```

### Phase B results (fill in)

| Check | Expected | Actual | Date |
|-------|----------|--------|------|
| `full_run.py` gate opens (9/9 + MCP OK) | yes | __ | __ |
| Full extraction completes (44 docs) | yes | __ | __ |
| Loss ledger: all 44 docs COMPLETE | yes | __ | __ |
| `prod_seed.sh` exits 0 | yes | __ | __ |
| Remote DB doc count | 44 | __ | __ |

**Phase B signed by:** _________________ **Date:** _________________

---

## Phase C — Live answer-quality gate (Rule 21 closure, operator, paid ~Opus pass)

### Operator run order

9. **Run the live eval against the deployed full-corpus system**:
   ```bash
   # Target the live system (not localhost):
   HELIXPAY_API_URL=https://helixpay.serverado.app \
     python -m eval.run --level 2
   # Level 2 = Opus synthesis over the golden questions.
   # Requires: ANTHROPIC_API_KEY (freshly rotated), VOYAGE_API_KEY, HELIXPAY_API_URL.
   ```

10. **Record the verdicts** in the table below.

11. **Sign this file** after all criteria pass.

### Success criteria (Rule 21 — recall + contradiction saga closure)

| Criterion | Target | Actual | Pass? |
|-----------|--------|--------|-------|
| Recall over `recall_bar:true` facts | ≥ 85% | __ | __ |
| Uncited claims in any answer | 0 | __ | __ |
| Planted contradiction 1 present in `AnswerBundle.contradictions` | yes | __ | __ |
| Planted contradiction 2 present in `AnswerBundle.contradictions` | yes | __ | __ |
| Two-Marias name trap: distinct (not collapsed) | yes | __ | __ |
| Two-Tans name trap: distinct (not collapsed) | yes | __ | __ |
| Live endpoint used (not localhost) | `helixpay.serverado.app` | __ | __ |

### Live endpoint evidence (fill in)

- **Endpoint:** `https://helixpay.serverado.app`
- **Eval run date:** ________________
- **Eval commit hash (HEAD at run time):** ________________
- **Recall result:** __ / __ facts recalled (__ %)
- **Uncited claims found:** __
- **Contradiction 1:** _________________ (topic: _________________)
- **Contradiction 2:** _________________ (topic: _________________)
- **SP_011/SP_012 merge status at run time:** ________________
  *(If SP_011/012 are not merged, record the as-deployed gap here.)*

### Phase C notes / caveats

*(Record any deviations, partial passes, or open risks here.)*

---

## Final sign-off

**All three phases (A + B + C) complete.**

This is the Rule-21 closure of the recall + contradiction saga (SP_010 → SP_016).
The live system at `https://helixpay.serverado.app` answers golden questions with
cited, `as_of`-stamped claims and surfaces contradictions over the full 44-doc corpus.

**Signed by:** _________________ **Date:** _________________

---

## Caveats and open risks (do not drop)

- **Compromised keys.** Any keys from this project's transcript history must not be
  used in production. Rotation is step 1 of Phase A; this file must record the
  rotation date (not the key value).
- **Types, not instances (carried from SP_015).** The SP_015 proof verified each
  document archetype; the full run is the first 44-doc exposure. If the loss ledger
  flags any INCOMPLETE rows on the full run, record them here and block Phase C until
  resolved.
- **SP_011/012 merge dependency.** The Phase C "zero uncited claims" and
  contradiction-surfacing criteria depend on the query/synthesis + provenance surface.
  If SP_011/012 are not on `main` at run time, record the as-deployed state and gap.
- **Advisory guard.** `make ingest`, `make ingest-record`, and `replay record ./data`
  still bypass `full_run.py`. The deploy decoupling (SP_016 Phase A) removes the
  most dangerous bypass (`deploy.sh`). The `make ingest` bypass is held by discipline
  until the enforcement chokepoint (open fork from SP_015 hand-off).
- **Shared box.** The droplet runs pangeabot/obsidiancomments/n8n/baserow behind the
  same system nginx. No nginx changes are made in SP_016. Verify neighbour sites are
  still 200 after Phase A deploy.
