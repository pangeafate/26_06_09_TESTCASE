---
sprint_id: SP_028b
tier: Foundational
features: []
user_stories:
  - "As the operator, genuine cross-document contradictions that the lexical comparator gets WRONG are corrected by a post-ingest LLM adjudication pass: it judges each candidate cluster of related claims/links and (a) DROPS deterministic rows that are the same fact in different words ('end of Q3 2026' ≡ 'Sep 30 2026'), and (b) ADDS cross-predicate/semantic conflicts the same-predicate comparator never compares — always surfacing BOTH sides with cited claim/link ids, never resolving to one value."
  - "As the operator, the adjudication is reproducible and $0 on replay, because every cluster verdict is cached on a CONTENT hash of (model, prompt_version, norm_version, sorted member semantic-signatures) — not surrogate row ids — so a re-sweep of an unchanged store issues zero LLM calls and survives a re-seed/re-ingest."
  - "As the operator, the paid pass is a single explicit, gated CLI step with a --dry-run that prints cluster counts and the estimated number of LLM calls before any money is spent; and if the LLM is unavailable or drops a cluster, that cluster falls back to the SP_028a deterministic verdict so a real conflict is never lost."
schema_touched: false
structure_touched: false
status: Complete
isolation: branch-only
branch: sprint/SP_028b-llm-adjudication
worktree: ""
agent_owner: "main (operator-directed)"
dependencies: [SP_009, SP_026, SP_027, SP_028a]
dev_dependencies: []
touches_paths:
  - prompts/adjudicate_contradictions.md
  - helixpay/ingest/adjudicate.py
  - helixpay/ingest/dedup.py
  - helixpay/ingest/extract/llm.py
  - scripts/adjudicate_contradictions.py
  - scripts/recompute_contradictions.py
  - test/unit/ingest/test_adjudicate.py
  - test/unit/ingest/test_llm_temperature.py
  - test/integration/db/test_adjudicate_integration.py
  - eval/contradiction_recall.py
  - test/golden/contradictions.yaml
  - test/golden/test_contradiction_recall.py
  - CLAUDE.md
  - USER_STORIES.md
  - workspace/sprints/SP_028b_llm_adjudication.md
touches_checklist_items: [adjudicate-cluster-gen, adjudicate-prompt, adjudicate-schema, adjudicate-llm-seam-temperature, adjudicate-content-cache, adjudicate-write-singlewriter, adjudicate-fallback-floor, adjudicate-cli-dryrun, adjudicate-oracle-score, claude-md-adjudication-gotcha]
---

# SP_028b: LLM contradiction adjudication — refine precision, add semantic/cross-predicate recall

## Sprint Goal

Layer a **post-ingest LLM adjudication pass** onto the SP_028a deterministic precision sweep.
SP_028a took the live `helixpay_full` from 266 → 115 contradictions at $0 by killing the
format/multi-valued/breakdown spurious classes. The **residual 115** are mostly *distinct
phrasings of one semantic conflict* ("end of Q3" vs "Sep 30 2026") plus the genuine conflicts the
same-predicate lexical comparator structurally cannot see (**cross-predicate**, e.g. the Maria
solid-line vs dotted-line case). An LLM judging each candidate cluster:

- **raises precision** — drops a deterministic candidate pair the model judges to be the same fact
  in different words (no new conflict row);
- **raises recall** — emits genuine cross-predicate / semantically-incompatible pairs the
  comparator never compared;
- **never resolves** — the output schema has NO winner field; both claims/links coexist and are
  cited (CLAUDE.md ontology rule). `AnswerBundle.contradictions` stays present-and-empty, never
  hidden.

Measured blind against `test/golden/contradictions.yaml` (the 8-item SP_027 oracle) via the
existing `eval/contradiction_recall.py` scorer.

## Where it runs (placement) — unchanged from SP_028a

A **single-writer clear-then-rewrite sweep AFTER full ingest**, over the whole store. This is the
SP_028a `scripts/recompute_contradictions.py` model; SP_028b adds the LLM stage as a refiner on
top of the deterministic candidate set, inside the SAME single writer — so the
`UNIQUE(claim_a_id, claim_b_id)` table never sees two competing writers (Stage-3 C1 fix).

## The pipeline (the SP_028a sweep + an LLM refiner stage)

A cluster carries **two independently-numbered, signature-sorted blocks** — `CLAIMS` (`C1..Cn`)
and `LINKS` (`L1..Lm`). The LLM I/O and the output schema name a pair by **block + two 1-based
indices into that block**, so a pair is ALWAYS homogeneous (two claims, or two links) and a
claim↔link pair — which the `Contradiction` row cannot represent — is structurally impossible
(Stage-3 C-1/C-2 fix).

```
if dry_run:                                          # H3: --dry-run is PRINT-ONLY (no clear, no writes)
    build all clusters; count cache MISSES; print {clusters, est_llm_calls, cache_hits}; RETURN

clear_contradictions()                               # single writer owns the table
for subject in subjects_with_claims_or_links:        # union(distinct_claim_groups, distinct_link_groups)
    claims = live non-set_valued claims for subject (CROSS-predicate), sorted by signature  # C-block
    links  = subject's reports_to + dotted_line_to edges, sorted by signature               # L-block
    if (len(claims) < 2 and len(links) < 2):         # no homogeneous pair possible
        deterministic_floor(subject); continue       # nothing for the LLM; floor is exact/empty
    if len(claims) + len(links) > MAX_CLUSTER_MEMBERS:   # bound; LOG the cap (no silent truncation)
        deterministic_floor(subject); continue
    key = sha256(ADJUDICATE_MODEL | PROMPT_VERSION | NORM_VERSION | sorted(member signatures))
    verdict = cache.get(key)
    if verdict is None:
        verdict = llm_adjudicate(cluster, client)    # Opus, temp 0; call_structured validate-or-drop
        cache.put(key, verdict)                       # verdict may be an empty pair list — still cached
    if verdict is None:                               # call_structured DROPPED (undecodable) → no LLM ran
        deterministic_floor(subject)                  # H2: verdict ABSENT → fallback (never lose a conflict)
    else:
        for pair in verdict.contradictions:           # H2: verdict PRESENT (even empty) → authoritative
            assert pair.block in {claim, link} and 1<=a,b<=len(block) and a!=b   # validate-and-drop
            map (block, a, b) -> (claim_a_id,claim_b_id) OR (link_a_id,link_b_id) -> write row
```

Key design points, each tied to a Stage-3 finding:

- **C-1 / C-2 — two labeled blocks, no mixed pair.** Claims and links live in separate index
  spaces; the schema's `block` field selects which. The writer maps a `claim` pair to
  `claim_a_id/claim_b_id` and a `link` pair to `link_a_id/link_b_id`; a pair whose `block` is
  absent/invalid or whose indices are out of range is **dropped** (zero-uncited guard). `dotted_line_to`
  is in the link block ON PURPOSE — `detect_link_conflicts` only sweeps `reports_to`, so the LLM
  link block is the ONLY place the dotted-vs-solid recall item (#6) can come from; the floor cannot
  catch it.
- **Member ordering is the signature, not the row id.** Each block is sorted by its full semantic
  signature tuple BEFORE numbering, on BOTH cache-write and cache-read, so a re-seed that renumbers
  surrogate ids yields the identical index→member mapping (Stage-3 C-1/M-1 fix). `get_claims`/
  `get_links` fetch order never determines a member's index.
- **C-2 — content-hash cache, not surrogate ids.** Signatures (kind-tagged, `source_uri` EXCLUDED —
  it can change on a re-record of the same fact, Stage-3 M-1):
  - claim: `("claim", subject_id, canonical_predicate, normalize_value(object_value)[0], as_of_iso)`
  - link:  `("link", subject_id, link_type, to_entity_id, as_of_iso)`
  The cache stores the verdict as block+index pairs (id-stable), re-mapped to live ids on read using
  the SAME signature sort.
- **H1 — temperature seam (additive, no Protocol change).** `AnthropicClient.__init__` gains an
  optional `temperature` (default `None` → the kwarg is OMITTED from `messages.create`, so every
  existing caller is byte-for-byte unchanged). Temperature rides on the INSTANCE and is read in
  `generate_with_meta`; `call_structured` and the `LLMClient` Protocol are untouched. The
  adjudicator constructs `AnthropicClient(model=SYNTHESIS_MODEL, temperature=0)` (Opus, pinned).
- **H2 — fallback arbitration (the precision/safety distinction).** `verdict is None` means the LLM
  never produced a parseable answer (drop / no-API) → write the deterministic floor (safe). `verdict`
  PRESENT with zero or fewer pairs is the **precision win** (the LLM overruled a lexical candidate) →
  authoritative, NO fallback (else the dropped pair is reinstated and precision is zero). A pair is
  written by exactly one path.
- **H4 — the floor uses value-pair dedup.** `deterministic_floor(subject)` runs `detect` over the
  subject's non-set_valued predicate groups and `detect_link_conflicts` over its link groups, each
  wrapped in the SAME value-pair `_DedupWriter` discipline as SP_028a — never raw `detect` (else the
  pairwise inflation the SP_028a sweep removed comes back).
- **C-3 — LLM note embeds both raw values verbatim.** An LLM-written row's `note` is
  `[llm] <kind>: '<value_a>' (<as_of_a>) vs '<value_b>' (<as_of_b>) — <rationale>` (links use the
  `→ <to> (<as_of>)` form), mirroring `detect`'s note. The `eval/contradiction_recall.py`
  unresolved-subject path (Açaí #4) substring-matches both `object_value` strings in the note, so the
  verbatim values — not the paraphrased rationale — keep that match working.
- **M-3 — `MAX_CLUSTER_MEMBERS` + logged cap.** Oversized → deterministic floor + a logged cap line
  naming the subject, so the operator sees any cross-predicate recall gap (HelixPay is the largest
  subject; the paid run reports whether it hit the cap). v1 cap is generous; tuned from the live count.

## Cost discipline (operator is cost-sensitive)

- **All code + unit + integration tests run at $0** with an injected stub adjudicator (mirrors the
  extraction `LLMClient` stub). No test calls a real model. The integration test is db-marked and
  uses the stub.
- The **paid** run is one explicit operator-invoked CLI step
  (`scripts/adjudicate_contradictions.py`) — same gating as the re-record. `--dry-run` prints the
  cluster count + estimated LLM calls (cache misses only) and spends nothing.
- Caching makes re-runs $0; the content-hash key means an unchanged store after re-seed is still a
  full cache hit.

## Contracts / boundaries

- **No frozen-contract change.** Reuse `Contradiction`, `Repository.{get_claims, get_links,
  get_contradictions, add_contradiction, clear_contradictions, distinct_claim_groups,
  distinct_link_groups, resolve_entity, canonical_predicate}` — all already present (SP_028a uses
  the concrete `PostgresRepository`). Adjudication provenance lives in `note` (prefix `[llm]` vs
  `[deterministic]`) and the existing `kind` vocabulary. **No new Repository method, no schema, no
  `models.py` change** — `repository.py` (852 lines) is not touched.
- `adjudicate.py` is ingest-shared-logic; the LLM seam reuses
  `helixpay/ingest/extract/llm.call_structured` (named prompt + schema + validate-or-drop).
- New prompt `prompts/adjudicate_contradictions.md` + a NEW local Pydantic output schema in
  `adjudicate.py` (not in `extract/schemas.py` — avoids path overlap). The prompt uses ONLY
  synthetic example values/subjects so the SP_027 leak guard
  (`test_prompts.py::test_golden_values_and_subjects_do_not_leak_into_prompts`, which scans every
  `prompts/*.md`) stays green — it now covers this prompt automatically.
- `NORM_VERSION` constant in `adjudicate.py` is bumped whenever `normalize.py` semantics change
  (cache-invalidation contract). `PROMPT_VERSION` is bumped on any prompt edit. Both are covered by
  the version-bump key test.
- **Logging hygiene (M-3 code):** `adjudicate.py`/the CLI log only subject id, cluster size, cache
  hit/miss, pair counts, and cap hits — NEVER a connection string or API key (the CLI builds the
  repo via `PostgresRepository.from_url()` and the client via env, same as SP_028a).

## TDD plan (Rule 1 — a failing test first for each unit)

1. `test_llm_temperature.py`: `AnthropicClient(temperature=0)` passes `temperature=0` to the
   captured `messages.create` kwargs; default `AnthropicClient()` omits the key entirely (existing
   callers unchanged). RED → add the param.
2. `test_adjudicate.py` (in-memory dict cache + scripted stub client; FakeRepo like SP_028a):
   - **cluster gen**: claims for one subject across two predicates form the CLAIM block; the
     subject's `reports_to` + `dotted_line_to` edges form the LINK block; a `set_valued` claim is
     excluded from the claim block.
   - **member-order stability (C-1)**: a FakeRepo returning the members in REVERSE fetch order
     yields the IDENTICAL block numbering and the SAME cache key (proves sort-by-signature, not by
     fetch order or row id).
   - **content key stability (C-2)**: re-deriving the key after re-numbering surrogate claim/link
     ids yields the SAME key; `source_uri` change does NOT change the key.
   - **version bump (`test_norm_version_change_invalidates_key`)**: bumping `NORM_VERSION` OR
     `PROMPT_VERSION` changes the key (cache-invalidation guard).
   - **precision drop**: a stub verdict returning an EMPTY pair list ⇒ zero rows written for that
     cluster, and NO deterministic fallback (verdict present-but-empty is authoritative — H2).
   - **cross-predicate claim add**: a stub citing two CLAIM indices under different predicates ⇒ a
     row with `claim_a_id/claim_b_id` set, `link_*` None; note carries both `object_value`s.
   - **link↔link add (Maria #6)**: a stub citing two LINK indices (solid vs dotted) ⇒ a row with
     `link_a_id/link_b_id` set, `claim_*` None.
   - **mixed-pair is impossible/dropped**: the schema has no cross-block pair; if a stub emits an
     out-of-range index in a block ⇒ that pair is dropped (zero-uncited guard), no row.
   - **note preserves oracle match (C-3)**: the written note for an LLM pair passes
     `eval.contradiction_recall._present` for BOTH oracle value strings.
   - **cache**: 1st `adjudicate_store` makes N stub calls (= cluster count after pre-filter); the
     2nd run on the unchanged store makes ZERO (assert call count).
   - **dry-run (H3)**: `dry_run=True` makes zero stub calls, writes NOTHING (table untouched), and
     returns the cluster/estimated-call counts.
   - **fallback floor (H2)**: a cluster whose stub `generate` returns undecodable text
     (call_structured → None) ⇒ the deterministic rows for that subject are written via the
     dedup'd floor (no real conflict lost).
   - **oversized cap (M-3)**: a cluster over `MAX_CLUSTER_MEMBERS` ⇒ deterministic floor + the cap
     is logged (assert via caplog).
3. `test_adjudicate_integration.py` (db-marked, $0 stub): seed a mini-store with (a) a planted
   same-period value conflict and (b) a `pain_point` multi-valued set; run `adjudicate_store` with
   a stub that confirms the planted pair and rejects nothing else; assert the planted conflict is a
   row and the multi-valued predicate is not.
4. **Oracle measurement** (a reported metric, not a unit assert): run the sweep with the stub over
   `helixpay_full` and print `eval.contradiction_recall` — confirms no regression below the
   SP_028a floor. The real catch-rate lift is confirmed only by the **paid** run (gated, operator).

## Acceptance

- Unit + integration suite green at $0 (stub); `uv run mypy helixpay scripts/...` clean.
- A second sweep on the unchanged store issues **0** LLM calls (content-cache hit) — proven by the
  unit call-count assertion and, on the paid run, by the CLI reporting 0 misses on re-run.
- Oracle catch-rate never drops below the SP_028a baseline floor; with the paid pass it is expected
  to rise toward the cross-predicate/semantic items (#2/#4/#6/#8). The paid lift is reported, not
  asserted (honest measurement — never re-rig toward the oracle).
- `ask()` / MCP still surface contradictions present-and-empty; both sides always cited; no winner
  field anywhere.

## Risk

- **Entity-fragment merging stays OUT of scope** (SP_029). v1 clusters only by existing
  `subject_entity_id` + cross-predicate within that subject + the subject's single-valued links.
  No fragment bridge → no two-Marias/two-Tans false-merge risk.
- **LLM nondeterminism / hallucinated citations** → temperature 0, structured output, every cited
  index validated against the presented cluster (drop on miss), content-cached. Same discipline as
  extraction.
- **Cache staleness on vocab/prompt/normalizer change** → the key includes `PROMPT_VERSION` +
  `NORM_VERSION`; both are bumped on the relevant edit (documented gotcha + a test that the key
  changes when the version changes).
- **Over-dropping a real conflict** (LLM false-merges two genuinely different values) → the
  rationale is recorded in `note`; the deterministic floor is the fallback on a dropped/empty
  verdict; the oracle ratchet test (`test_contradiction_recall`) fails CI if the live caught-count
  drops below baseline.
- **module size**: adds NO repository method; `repository.py` unchanged.

## Stage 3 / Stage 5 review

Foundational → ≥2 plan-review iterations (architect + code, plan-blind code at Stage 5) and ≥2
post-impl iterations. Reviewers named in Progress. Hard-stop at iteration five if CRITICAL/HIGH
remain.

## Technical Approach

See **The pipeline** and **Contracts / boundaries** above: a single-writer clear-then-rewrite
post-ingest sweep with an Opus (temperature 0) LLM refiner over two labeled, signature-sorted
claim/link blocks, content-hash cached, with a deterministic value-pair-dedup'd fallback floor. No
frozen-contract change, no new Repository method, no schema change.

## Testing Strategy

See **TDD plan** above. All unit + db-integration tests are $0 (an injected stub `LLMClient` +
in-memory cache; no network/API/Voyage). The integration test is `pytest.mark.db` (auto-skips
without `DATABASE_URL`). Gates: `uv run pytest test/unit test/golden` (760 passed, 4 skipped) +
the db-integration run against a live `PostgresRepository` (10 passed) + `uv run mypy helixpay
scripts/adjudicate_contradictions.py scripts/recompute_contradictions.py` (clean, 76 files).

## Success Criteria

See **Acceptance** above: $0 unit/integration suite green; a 2nd sweep on an unchanged store issues
0 LLM calls (content cache); oracle catch-rate never below the SP_028a floor; the output schema has
no winner field and both sides are always cited; a claim↔link pair is unrepresentable by
construction.

### Pre-Implementation Review

- **Iteration 1** (2026-06-11, architect-reviewer + code-reviewer, plan-blind to each other) — severity 1 CRITICAL + several HIGH; both PROCEED-WITH-FIXES, no split. CRITICAL: heterogeneous single-index cluster invites a claim↔link pair the frozen `Contradiction` cannot represent. HIGH: signature-sort for index stability; `[llm]` note must embed both values; verdict-absent vs present-but-empty arbitration; print-only `--dry-run`; dedup'd floor; drop `source_uri` from the cache key; name the version-bump test. Files reviewed: SP_028b_llm_adjudication.md, helixpay/ingest/contradict.py, helixpay/ingest/extract/llm.py, helixpay/contracts/models.py, eval/contradiction_recall.py, scripts/recompute_contradictions.py.
- **Iteration 2** (2026-06-11, revision re-reviewed vs iteration-1) — severity 0 CRITICAL / 0 HIGH remaining; revised to two labeled signature-sorted blocks (mixed pair impossible), content cache sans `source_uri`, verbatim-value note, verdict-absent/empty arbitration, print-only dry-run, dedup'd floor, `MAX_CLUSTER_MEMBERS` cap, + version-bump / member-order / oracle-note tests; cleared for implementation. Files reviewed: SP_028b_llm_adjudication.md.

### Post-Implementation Review

- **Iteration 1** (2026-06-11, code-reviewer, plan-blind, code+tests only) — severity 0 CRITICAL, 2 HIGH (`Cluster` frozen+mutable list → `tuple`; `_deterministic_floor` O(N×G) → fetch group lists once), 1 MEDIUM (cache-key separator → JSON), 2 missing drop tests; SHIP-WITH-FIXES, all applied. Files reviewed: helixpay/ingest/adjudicate.py, prompts/adjudicate_contradictions.md, scripts/adjudicate_contradictions.py, helixpay/ingest/extract/llm.py, test/unit/ingest/test_adjudicate.py, test/unit/ingest/test_llm_temperature.py, test/integration/db/test_adjudicate_integration.py.
- **Iteration 2** (2026-06-11, architect-reviewer, plan-blind) — severity 0 CRITICAL / 0 HIGH, 1 MEDIUM (de-duplicate `_DedupWriter` into the ingest layer — applied: new helixpay/ingest/dedup.py imported by both the SP_028a sweep and this floor) + 3 LOW follow-ups; SHIP-WITH-FIXES; never-resolve + claim↔link-unrepresentable + layer-boundary invariants verified against code. Files reviewed: helixpay/ingest/adjudicate.py, helixpay/ingest/dedup.py, scripts/recompute_contradictions.py, helixpay/ingest/extract/llm.py, test/unit/ingest/test_adjudicate.py, test/integration/db/test_adjudicate_integration.py.

## Progress

- **Stage 2 (plan)** 2026-06-11 — written (split out of SP_028 per the convergent Stage-3
  recommendation; SP_028a shipped the $0 deterministic layer; this is the paid LLM refiner with the
  C1/C2/H1-2 fixes already specified in the SP_028 review trail).
- **Stage 3 (plan review, iteration 1, 2 independent contexts)** 2026-06-11 — architect-reviewer +
  code-reviewer, plan-blind to each other. Both verdicts: **PROCEED-WITH-FIXES, no split.**
  Convergent CRITICAL: the heterogeneous single-index cluster (claims+links in ONE numbered list)
  invites a claim↔link pair that `Contradiction` cannot represent — and the TDD even asserted
  writing one. Other blocking findings: member-order must be signature-sorted for index stability
  (C-1 code); `[llm]` note must embed both raw values or the oracle unresolved-subject path breaks
  (C-3 code); fallback must distinguish verdict-absent (→fallback) from present-but-empty
  (→authoritative) (H-2 architect); `--dry-run` print-only vs writes-floor was contradictory (H-3
  code); floor must reuse value-pair dedup (H-4 code); drop `source_uri` from the cache signature
  (M-1 architect); name the version-bump test (H-1 code); cap-hit logging + HelixPay size (M-3);
  add the SP_027 leak guard for the new prompt (L-4). Sound as-is: single-writer clear-then-rewrite,
  content-cache concept, temperature seam, no frozen-contract change, no new Repository method,
  ontology "never resolve", entity-merge correctly out (SP_029).
- **Stage 3 (plan review, iteration 2 — revision)** 2026-06-11 — plan revised to adopt EVERY
  blocking fix: two labeled signature-sorted blocks (claim/link) with a `block`-tagged pair schema
  (mixed pairs structurally impossible); index stability via signature sort on read+write;
  verbatim-value `[llm]` note; verdict-absent vs present-but-empty arbitration; print-only
  `--dry-run`; dedup'd deterministic floor; `source_uri` excluded from signatures; `MAX_CLUSTER_MEMBERS`
  with logged cap; version-bump + member-order + oracle-note tests added to the TDD list; leak-guard
  + logging-hygiene called out. No CRITICAL/HIGH remain open → cleared for implementation.
- **Stage 4 (implementation, TDD)** 2026-06-11 — failing-test-first per unit. Temperature seam
  (`test_llm_temperature.py`), then `adjudicate.py` against `test_adjudicate.py` (15 cases:
  two-block cluster gen, member-order + content-key stability, version-bump invalidation,
  claim-pair / link-pair writes, out-of-range + self-pair + empty-link-block drops, verbatim-value
  note, empty-verdict authoritative, undecodable→floor, oversized→floor+cap, cache 0-call re-run,
  print-only dry-run), the prompt (synthetic only), and the gated CLI. db-integration
  (`test_adjudicate_integration.py`) verified end-to-end against a live `PostgresRepository` in the
  `helixpay_default` network ($0 stub): planted same-period revenue conflict surfaces as a claim
  pair, multi-valued `pain_point` does not, solid-vs-dotted line surfaces as a link pair, 2nd sweep
  is 0-call. `uv run pytest test/unit test/golden` → 760 passed, 4 skipped; integration → 10 passed;
  `uv run mypy helixpay scripts/...` → clean (76 files).
- **Stage 5 (post-impl review, 2 independent plan-blind contexts)** 2026-06-11 — code-reviewer +
  architect-reviewer, code+tests only. Both: **SHIP-WITH-FIXES, zero CRITICAL.** Invariants verified
  against the code: "never resolve" upheld (no winner field), the claim↔link mixed pair is
  unrepresentable BY CONSTRUCTION (two-block discriminant), layer boundary respected (ingest never
  imports db; `SweepRepository` structural extension is sound), Opus+temp-0 seam additive, prompt
  leak-free, single-writer / fallback-arbitration / dry-run / cache all correct. Fixes APPLIED:
  (H1) `Cluster` list fields → `tuple` (real immutability); (H2) `_deterministic_floor` takes the
  store-wide group lists fetched once in `adjudicate_store` (one scan, not O(subjects×groups));
  (architect MEDIUM) extracted the duplicated `_DedupWriter` into the shared `helixpay/ingest/dedup.py`
  — both the SP_028a sweep and this floor now import the SAME `DedupWriter` (can't drift); (M3)
  cache-key blob JSON-serialized (no separator-injection surface); (M1/M2) added empty-link-block
  + self-pair drop tests. Re-ran: 760 + 29 targeted + 10 integration green, mypy clean. LOW items
  (CLI smoke test, raw-predicate-to-detect inherited pattern) recorded as non-blocking follow-ups.
- **Stage 6 (documentation)** 2026-06-11 — CLAUDE.md gotcha appended (the SP_028b paid-refiner
  contract: two blocks, content cache + version-bump discipline, fallback arbitration, shared
  DedupWriter, print-only dry-run, MAX_CLUSTER cap, synthetic prompt). Sprint frontmatter reconciled
  (touches_paths +dedup.py +recompute_contradictions.py); USER_STORIES.md US-9 added. Validators:
  validate_sprint full-gate PASS, doc_reality/doc_freshness PASS. (Pre-existing non-blockers:
  `validate_workspace` flags CLAUDE.md > 20k — HEAD was already 23.2k, SP_024/025-deferred gotcha
  archival; the dev-gateway `python-tests` step uses system python3 which lacks `bs4` — the
  authoritative `uv run pytest` gate passes 762.)
- **Stage 7 (deploy)** 2026-06-11 — **branch-only** per operator (main is 99 commits behind and
  carries the HELD SP_024/025; not merged). Code pushed to
  `origin/sprint/SP_028b-llm-adjudication` (commits `ae809b3`, `227bc8b`). **Paid data sweep** run
  on the live `helixpay_full` with **Sonnet** (operator chose Sonnet over Opus for cost; the model
  rides in the cache key): 305 subjects → 164 clusters → **17 LLM-confirmed rows + 50 floor rows +
  5 capped → contradictions 115 → 67 (−42% precision)**. Oracle recall **1/8 → 2/8**: the
  cross-predicate `maria-santos-dual-line` (link↔link) is now caught — the genuine recall the
  same-predicate comparator structurally cannot see — with the `confluence-ga-target` baseline floor
  preserved (ratchet held). 164 verdict files cached; a re-sweep dry-run reports
  `estimated_llm_calls: 0` (content cache → $0 reproducibility verified). The remaining 6 oracle
  misses are entity-fragmented (bug-ticket `hxloy487`, etc.) → SP_029 (entity-merge), out of scope.
