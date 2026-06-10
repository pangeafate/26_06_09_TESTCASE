---
sprint_id: SP_011
tier: Standard
features: [evidence-persist, link-provenance, link-contradictions, org-chart-ingest]
user_stories: []
schema_touched: false
structure_touched: true
status: Complete
isolation: git-worktree
branch: sprint/SP_011-provenance-persist
worktree: .claude/worktrees/SP_011
agent_owner: "Agent C (provenance-persist)"
fix_type: ""
dependencies: []
dev_dependencies: []
touches_paths:
  - helixpay/ingest/pipeline.py
  - helixpay/ingest/contradict.py
  - helixpay/ingest/extract/grounding.py
  - helixpay/seed/**
  - test/unit/ingest/test_pipeline.py
  - test/unit/ingest/test_contradict.py
  - test/unit/ingest/test_grounding.py
  - test/unit/seed/test_run_seed.py
  - test/integration/ingest/**
touches_checklist_items: [persist-evidence-through-pipeline, persist-char-offsets, persist-link-document-id, persist-org-chart-edges, persist-link-contradiction-sweep]
---

# SP_011: Provenance Persist (ingest side) — make the pipeline *produce* provenance

> **Depends on SP_009** (consumes `Claim.evidence`/offsets, `Link.document_id`,
> `Contradiction` link refs, and the extended `add_claim`/`add_link`). Branch from the
> post-SP_009 commit. Does **not** edit `helixpay/contracts/**`, `schema.sql`, or
> `helixpay/db/repository.py`.

## Sprint Goal

Close gaps 1–4 of `research/provenance-evidence-and-ux-pipeline-design.md` on the
**write path**, so provenance is a native output of ingestion — not a manual DB
backfill that the next ingest silently loses:

1. **Persist the evidence span.** `ChunkExtractor` already emits `ClaimOut.evidence`;
   thread it (and `char_start`/`char_end` from the grounding step) through
   `pipeline._ingest_document` into the `Claim` it builds, so `add_claim` stores it.
   ~3 lines of plumbing + offset capture in `grounding.py`. No new LLM cost.
2. **Link provenance.** Set `Link.document_id` alongside `source_chunk_id` when
   building links, so relationship answers have a direct document join (gap 3).
3. **Corroborate org-chart edges with cited extracted ones (recall-safe).** `data/org-chart.md`
   is a real source and already flows through extraction (top-level `*.md`), but extracted
   reporting edges currently **collide** with the seeded edges on the links natural key
   (`from,to,link_type,COALESCE(as_of,…)`): seeding stamps `reports_to`/`dotted_line_to`
   with `ORG_CHART_AS_OF` (2026-04-15), which is exactly the `as_of` extraction assigns to
   `org-chart.md` edges, so `add_link`'s `ON CONFLICT DO NOTHING` keeps the citation-less
   seeded row and drops the cited one. Fix: **seed the reporting edges with `as_of=None`**
   so the cited extracted edge coexists (different natural key) and supplies provenance,
   while the seeded edge stays as the deterministic org-tree backbone. Closes the "47/77
   reports_to have no provenance" hole **without** regressing org-chart recall (extraction
   misses → seeded edge still present). *(Operator decision, Stage-3: corroborate, not
   replace — outright removal of the seeded backbone is Foundational/unverifiable here.)*
4. **Contradiction sweep over links.** After the claim sweep, run a per-`(from_entity,
   link_type)` pass flagging incompatible **`reports_to`** edges (same `from`, *different*
   `to`, overlapping validity) as `Contradiction` rows via the SP_009 link refs, so graph
   conflicts surface the same way value conflicts do (gap 4). **Note:** the current corpus
   has *no* real reporting conflict (every source agrees Daniel Tan→Arjun Kapoor→Wei Chen,
   `eval/questions.yaml:q-hierarchy-head-of-eng`); this is infrastructure that must fire on
   a synthetic conflict and stay silent (zero rows) on the real, consistent chart.

## Current State

- `pipeline._ingest_document` builds `Claim(... source_chunk_id, document_id)` but drops
  `claim_out.evidence`; builds `Link(... source_chunk_id)` with no `document_id`.
- Org reporting lines come from the seed roster stamped `ORG_CHART_AS_OF`; an extracted
  org-chart edge gets the same `as_of`, so its cited row dedupes away against the seeded
  (citation-less) one → 47/77 `reports_to` carry no `source_chunk_id`.
- `contradict.detect` runs over claims only; there is no link/graph contradiction pass.
- The corpus reporting graph is internally consistent (no real conflicting edge today).

## Desired End State

- New claims carry `evidence` + offsets; new links carry `document_id`; org-chart edges
  get a cited extracted twin (seeded backbone retained, `as_of=None`, no longer colliding);
  the link-contradiction sweep is wired and fires on a synthetic conflict while leaving the
  real (consistent) chart at zero rows; `Contradiction` rows can now pair links (the query
  side surfaces them — SP_012).
- Verifiable **now, unit-level, $0** (no DB / no LLM): grounding offset capture, pipeline
  plumbing of evidence/offsets/link-`document_id`, the link sweep on stub edges, and the
  seed `as_of=None` change all run in the fake-repo suites. Full end-to-end provenance over
  the real corpus is a later **SP_010 replay** confirmation (needs a live DB + a recorded
  cache); this sprint does not depend on it.

## Scope

In: write-path plumbing in `pipeline.py`, offset capture in `grounding.py`, the
org-chart extraction wiring, and the link-contradiction sweep in `contradict.py`.
Out: the schema/contract/repository changes (SP_009); surfacing/citing provenance in
answers (SP_012); eval assertions on it (SP_013).

## Technical Approach

- **Evidence + offsets** — `ClaimOut` carries `evidence` but **no** offset fields, and
  grounding runs *inside* the extractor (returns a `ClaimOut`), so the pipeline never sees
  grounding's offsets (Stage-3 M2). Rather than expand scope into `schemas.py`, add a pure
  `locate_span(evidence, chunk_text) -> Optional[tuple[int,int]]` to `grounding.py` that
  re-locates the verbatim span in the chunk (exact, then case/whitespace-tolerant regex
  yielding **raw** chunk offsets); `pipeline` calls it and threads `evidence`,
  `char_start`, `char_end` into `Claim`. A paraphrased (`value_only`) span that isn't a
  contiguous substring → `None` offsets; the claim still persists with its `evidence` text.
  `add_claim` (SP_009) persists all three.
- **Link `document_id`** — pass `document_id=doc_id` into every `Link(...)`.
- **Org chart** — org-chart.md already flows through extraction; the only change is the
  seed-side `as_of=None` on `reports_to`/`dotted_line_to` so the cited extracted edge no
  longer dedupes away against the seeded one (see Sprint Goal #3). Self-loop + cycle guards
  already exist; seeded `member_of` is unchanged.
- **Link sweep** — a *separate* `detect_link_conflicts(repo, from_entity_id, link_type)`
  mirroring `detect`, with link-specific semantics (Stage-3 H1/H3/H4, M1):
  - allowlist is **exactly `{"reports_to"}`** — never `member_of`/`dotted_line_to`/`owns`
    (multi-valued or distinct-by-design); a non-allowlisted type returns 0;
  - its **own** `_link_window`: `lo=as_of`, `hi=valid_to` with `None`=open (+∞) — must
    **not** reuse claim `_window` (which collapses `hi` to `as_of` and would mis-handle an
    open-ended reporting line); reuse `windows_overlap`'s None-as-open comparison;
  - fires only on same-`from`, **different**-`to` edges with overlapping windows;
  - `kind` via a small link `classify`: `source_disagreement` when the two edges have
    *different* `document_id`, else `value_conflict` (no new enum value — H4);
  - `subject_entity_id = from_entity_id`, `predicate = link_type`, `link_a_id`/`link_b_id`
    set; idempotent via a `seen_pairs` set read from `get_contradictions(from_entity_id)`
    on the **link** columns (not claim columns — H3), plus the DB partial unique index.
  - **No automatic link supersession exists** (links have no `superseded_by`), so a genuine
    re-org succession modeled by leaving both edges open *would* surface as a contradiction;
    that is the intended "surface, don't silently resolve" behavior and is acceptable —
    closing an old line's `valid_to` is future work, out of scope here.
  Wired into `run()` over a new `IngestReport.touched_link_groups`.

## Testing Strategy

- `test/unit/ingest/test_grounding.py` — `locate_span` returns correct **raw** `(start,
  end)` for an exact span, a case/whitespace-differing span, and `None` for a paraphrase
  that isn't a contiguous substring or for empty/None evidence.
- `test/unit/ingest/test_pipeline.py` — a stub extractor returning a claim with `evidence`
  yields a persisted `Claim` carrying `evidence` + the located offsets (and `None` offsets
  when the span isn't locatable, claim still persisted); every persisted `Link` carries
  `document_id`. A run with two stub `reports_to` edges from one subject to *different*
  managers raises `report.contradictions` (link sweep wired); a single consistent edge
  leaves it at 0.
- `test/unit/ingest/test_contradict.py` — `detect_link_conflicts`: two `reports_to` edges
  (same `from`, different `to`, overlapping windows) → one link `Contradiction`
  (`link_a_id`/`link_b_id` set; `kind` = `source_disagreement` cross-doc, `value_conflict`
  same-doc); same manager → 0; one solid + one `dotted_line_to` → 0 (allowlist); a closed
  earlier edge + a later open edge (disjoint windows) → 0; re-run writes nothing new
  (idempotent).
- `test/unit/seed/test_run_seed.py` — `seed_all` over the real `data/` emits `reports_to`
  and `dotted_line_to` links with `as_of=None` (no longer `ORG_CHART_AS_OF`); `member_of`
  unchanged; the golden Daniel→Arjun edge is still seeded.
- `test/integration/ingest/**` (`db`-marked, auto-skips without `DATABASE_URL`) — seed +
  ingest over `org-chart.md`: at least one `reports_to` edge carries a `source_chunk_id`
  (cited extracted twin survives), the full seeded backbone is still present (no recall
  regression), and the consistent chart yields **zero** link contradictions.

## Risks & Mitigations

- *`contradict.py` overlap with SP_010 (normalize wiring)* → resolved: branched from
  post-SP_010 HEAD, so SP_010's normalize util is already integrated; the link sweep is a
  new function, no edit to `detect`/`values_conflict`.
- *Over-firing link contradictions* → allowlist is exactly `{"reports_to"}`; `member_of`
  (legitimately multi-valued) and `dotted_line_to` (distinct by design) are never swept;
  same-`to` edges and disjoint windows don't fire.
- *Org-chart extraction regresses seeded reporting facts* → **corroborate, not replace**:
  seeded edges stay (now `as_of=None`), so a missed extraction never drops a backbone edge;
  the cited extracted edge is additive. Unit-asserted via `test_run_seed`; the integration
  test additionally checks the backbone count on a live DB.
- *Seed `as_of=None` changes org-tree temporal semantics* → seeded reporting edges become
  timeless (always-valid under the `as_of IS NULL OR …` filter) rather than dated
  2026-04-15; the freshest-wins resolver then prefers the dated cited extracted edge, which
  is the desired outcome. Operator-accepted in the Stage-3 decision.

## Success Criteria

- New claims carry `evidence` + offsets; new links carry `document_id`; the link sweep is
  first-class (`detect_link_conflicts`), fires on a synthetic conflict, and is silent on the
  real consistent chart — all unit-verified ($0, no DB).
- Seeded `reports_to`/`dotted_line_to` edges are emitted `as_of=None` so the cited extracted
  org-chart edge coexists; the deterministic backbone (incl. golden Daniel→Arjun) is intact.
- `uv run pytest test` green; `uv run mypy helixpay` clean.
- *(Deferred, not blocking)* end-to-end provenance + cited-edge survival over the real
  corpus confirmed on the **SP_010 replay tier** once a live DB + recorded cache exist
  (`make ingest-record` then `make ingest-replay`); the `db`-marked integration test encodes
  that gate.

### Pre-Implementation Review

> Standard tier — floor = 2. Branched from post-SP_010 HEAD (SP_009 contract surface +
> SP_010 normalize util both present).

- **Iteration 1** — architect-reviewer (independent), plan-blind: 2 CRITICAL + 4 HIGH/MEDIUM, NOT-GO → re-planned. Files reviewed: SP_011 plan, contradict.py, pipeline.py, grounding.py, schemas.py, run_seed.py, roster.py, repository.py, eval/questions.yaml, data/org-chart.md.
  - C1 — the promised Daniel→Wei/Arjun link conflict does **not** exist in the corpus
    (every source agrees Daniel→Arjun→Wei) → reframed item 4 as infrastructure that must stay
    silent on the consistent chart, with a synthetic unit fixture.
  - C2 — outright-removing the 47 seeded `reports_to` edges is Foundational/high-blast-radius
    (feeds `_org_root_id`) and unverifiable here → operator re-decided to **corroborate**
    (seed `as_of=None`), keeping the backbone.
  - H1 link windows must treat `valid_to=None` as open (+∞), not reuse claim `_window`; H3
    link sweep `seen_pairs` reads `link_a_id/link_b_id` + sets `subject_entity_id=from_entity_id`;
    H4 derive `kind` from `document_id` equality, not a hardcoded `source_disagreement`;
    M1 allowlist exactly `{"reports_to"}`; M2 compute offsets in `pipeline` via a new
    `grounding.locate_span` (no `schemas.py` scope expansion); M3 integration test asserts the
    backbone set. All folded into the design above.
- **Iteration 2** — author re-review vs the revised design (Reviewer: architect-reviewer iter-1 findings checklist): 0 CRITICAL/HIGH remaining, GO. Files reviewed: SP_011 plan, contradict.py, pipeline.py, grounding.py, run_seed.py.
  - Confirmed: no edit to `contracts/`, `schema.sql`, or `repository.py`; `touches_paths`
    expansion is one test file (`test/unit/seed/test_run_seed.py`, ≪50%); link semantics,
    allowlist, `kind` classification, and idempotency all addressed.

### Post-Implementation Review

- **Iteration 1** — code-reviewer (independent, plan-blind over the diff): 1 HIGH (fixed) + 2 MEDIUM (triaged), 0 blocking. Files reviewed: grounding.py, contradict.py, pipeline.py, run_seed.py, test_grounding.py, test_contradict.py, test_pipeline.py, test_run_seed.py, test_pipeline_integration.py.
  - HIGH (fixed): `locate_span`'s regex fallback used `re.search` (leftmost match) — a span
    whose normalized token sequence repeats in the chunk could anchor offsets to the wrong
    occurrence. Fixed with a uniqueness guard (`re.finditer`; commit an offset only when the
    match is unique, else `None`); regression test added
    (`test_locate_span_ambiguous_repeated_whitespace_span_returns_none`).
  - MEDIUM (pre-existing, no action): same-`as_of` same-type re-`add_link` keeps the first
    row's `document_id` (links natural key) — an existing schema property, not new here.
  - MEDIUM (ops, documented): re-seeding a DB previously seeded with the `ORG_CHART_AS_OF`
    stamp inserts a *second* (undated) reporting edge rather than a no-op, because the
    natural key's `COALESCE(as_of,…)` value changed. Fresh seed is clean; an existing DB
    needs a re-migrate/re-seed. Captured as a deploy gotcha (below + CLAUDE.md).
- **Iteration 2** — re-verify on runtime evidence: 0 CRITICAL/HIGH outstanding. Files reviewed: full pytest suite (320 passed / 36 db-smoke skipped) + mypy (clean) over helixpay/ and test/.
  - Link-sweep, offset-capture, and seed behaviors asserted in the fake-repo suites; the
    link-pair SQL path + cited-edge coexistence asserted in the `db`-marked integration suite
    (runs when a DB is present).
- **Iteration 3** — PR #2 cloud review (ultrareview) follow-up: 2 HIGH + 1 MEDIUM/LOW, all resolved; re-verified green (324 passed / 36 skipped, mypy clean). Files reviewed: grounding.py, contradict.py, test_grounding.py, test_contradict.py, test_run_seed.py.
  - H-1 (fixed, TDD red→green in separate commits): `locate_span`'s **exact**-match path
    (`str.find`) had no uniqueness guard — a verbatim string repeated in the chunk (a figure
    in two table rows) anchored to the first occurrence, misdirecting SP_012 highlight-to-verify.
    Now both locators commit an offset only on a unique match (`count==1`); a repeat → `None`.
  - H-2 (verified, no code change): `test/unit/seed/test_run_seed.py` is committed + tracked
    on the branch (not gitignored), so merging PR #2 carries the undated-edge guard forward;
    a manual cherry-pick must include it.
  - MEDIUM/LOW: added `detect_link_conflicts` zero-edge and single-edge no-op tests; clarified
    that `_classify_link` deliberately stays `value_conflict` when a `document_id` is absent
    (under-claim rather than fabricate a cross-source disagreement).

> **Deploy note (re-seed migration):** the seed `as_of` change alters the seeded reporting
> edges' natural key. On a DB seeded *before* SP_011, run a fresh re-seed (or drop the
> stamped `reports_to`/`dotted_line_to` rows) so the old dated edges don't linger alongside
> the new undated ones. A fresh `make up && seed` is unaffected.

## Hand-off (to SP_012)

- Evidence/offsets and link `document_id` are now populated; the query side can cite the
  exact span and route link citations through `get_link_sources`.
- Link `Contradiction` rows now exist; `AnswerBundle.contradictions` should surface them.
