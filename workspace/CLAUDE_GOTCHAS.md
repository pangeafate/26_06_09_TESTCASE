# CLAUDE Gotchas — Full Archive

This is the **full-fidelity archive** of the HelixPay "Gotchas" that were accumulated in
`CLAUDE.md`. The primary rulebook keeps a **condensed one-line** version of each (so it stays
under its 20,000-byte hard limit, `validators/validate_workspace.py`); this file holds the full
rationale. When a condensed gotcha in `CLAUDE.md` isn't enough, read the matching entry here.

Append the verbose form here **and** the condensed line in `CLAUDE.md` whenever Claude trips.

---

## Substrate / migration

- pgvector needs `CREATE EXTENSION vector;` before the schema (the migration does it first).
- A uniqueness key containing an expression (e.g. `COALESCE(as_of, …)`) must be a
  `CREATE UNIQUE INDEX`, **not** a table-level `UNIQUE (...)` constraint — the latter is a syntax
  error in Postgres. (Cost us a freeze re-run on `links`.)
- `migrate.py` applies the schema **statement-by-statement** (psycopg executes one command per
  `execute()`); keep `schema.sql` free of dollar-quoted bodies so the comment-strip + `;` split
  stays correct.
- MCP must run streamable-HTTP, not stdio, or it only works locally.
- HTML dashboards: capture the number **and** its as-of date — that's where contradictions hide
  (the planted Q1 revenue/ARR conflict).
- Ingestion is idempotent on `content_hash`; re-running on unchanged data is a no-op. Seeding and
  `add_claim` are idempotent on their natural keys, so re-seeding is safe.

## SP_019 — metric attribution & dashboard as_of

- **Metric-as-subject (SP_019):** the extractor sometimes stores a dashboard KPI with the
  *metric* as the claim subject (`metric|Q1 2026 Revenue`) instead of the company, so the value
  is unfindable as "HelixPay's revenue". `helixpay/ingest/repair.py` re-attributes known
  **company** metrics to the seeded company before resolution; milestone predicates
  (`ga_target`/`completion_target`) are deliberately **excluded** (their domain is a project/
  product, e.g. Project Confluence's GA), and regional metrics (`HelixPay Brasil revenue`) are
  left distinct so they never falsely merge into the company.
- **Dashboard `as_of` is NOT the metric's `as_of` (SP_019):** a "Q1 2026 Revenue" card is
  `as_of` the **quarter end** (2026-03-31), even if the dashboard header says "As of
  2026-04-21". The grader (`eval/run.py`) matches the value's reporting period — a baked-wrong
  as_of in the extraction cache can **only** be fixed by a re-record, never by post-processing
  (this is why the deterministic attribution fixes don't move golden recall at $0).

## SP_010 / SP_020 — dual-type mint & replay hygiene

- **A named account mentioned with two subject_types mints a duplicate (SP_010 → SP_020):** an
  external account (e.g. `Açaí Express SP`) tagged both `customer` and `other` mints **two**
  unseeded rows → its bare name is ambiguous → an `owns`-link endpoint resolves to `None` and the
  link is **dropped** at ingest. SP_010 worked around it by *seeding the account* (a per-account
  hardcode); **SP_020 removed that hardcode and fixed the class at MINT time**: `resolve_mention`
  snaps an open-class mention to an existing same-name row when **one side is the catch-all
  `other`** (`_other_compatible`), so the duplicate is never created and the link resolves at
  ingest — for *every* account, no seed. Guards: `resolve_entity` returns `None` on a 2+-row tie
  (never snaps across an existing dup); two *specific* distinct types are never bridged; seeded
  persons (two Marias) are non-creatable and never reach the snap. (Pre-existing cross-run dupes
  in a long-lived DB are out of scope — that's the only case a post-ingest merge would add.)
- **The replay/seed CLI from `eval/smoke/` uses the BAKED image code unless `PYTHONPATH=/app` is
  set (SP_020):** with the host repo mounted at `/app`, `python -m helixpay.ingest.replay …` run
  with CWD `/app/eval/smoke` imports the **installed** (baked) `helixpay`, NOT your edited
  `/app/helixpay`, because `-m` puts the CWD (not `/app`) on `sys.path`. A resolution/pipeline
  code change then silently does nothing on replay. Always pass `PYTHONPATH=/app` (and
  `HELIXPAY_PROMPTS_DIR=/app/prompts` for prompt changes) on any host-mounted run from a subdir.
  `run_seed` from `-w /app` is unaffected (CWD `/app` is already on the path).
- **Adding a `METRIC_VOCAB` key silently widens `repair.KNOWN_KEYS` (SP_010 final-mile):**
  `repair.py` builds `KNOWN_KEYS` as *every* vocab key minus `_NON_COMPANY_KEYS`. A new key whose
  subject is NOT the company (e.g. `top_contributor`, a repo attribute) must be added to
  `_NON_COMPANY_KEYS` too, or `repair_metric_subject` will re-attribute a metric-typed claim
  canonicalizing to it onto `HelixPay`. Keep the two in lock-step.
- **The $0 replay must run from `eval/smoke/` (SP_010 final-mile):** the replay cache keys on the
  `source_uri` string. `python -m helixpay.ingest.replay replay data` from the repo root walks the
  **full** corpus (source_uri `data/all-hands…` → cache miss on non-smoke docs). Run it with CWD
  `eval/smoke` (where `data/` is the 9-doc smoke subset) so source_uris match the cache the smoke
  harness recorded. `replay` mode uses a `_ConstantEmbedder` (no Voyage) and `ReplayExtractor`
  (raises on miss) → genuinely $0; `run_smoke.py --record` is NOT $0 (it re-embeds via Voyage).

## SP_021 — image/chart extraction & golden oracle

- **Image/chart extraction is structured now, but graded by SOURCE (SP_021):** the image vision pass
  (`helixpay/ingest/loaders/image.py` `_CAPTION_PROMPT`, still Sonnet) transcribes each chart **series** and its
  per-period values (actual vs plan via solid/dashed), and `extract_claims.md`'s "Charts & figures"
  section maps a region series → one `revenue` claim per region/period (`subject = HelixPay <Region>`;
  regions stay distinct, never collapsed onto `HelixPay`). A golden fact sourced to the jpeg is only
  FOUND if the satisfying claim **carries the image `source_uri`** (`run.py:_check_claim_fact`
  source-match) — the same value present in text (e.g. Brasil 4.8M in the interview) will NOT satisfy
  an image fact. That is the *feature*: an image-sourced recall-bar fact proves the image was
  extracted. Three traps: (1) **line-chart reads are approximate** — grade only **text-corroborated**
  datapoints (Brasil 4.8M ↔ interview golden; SEA 9.4M ↔ 14.2 total−4.8), and a `9.40`/`9.3` read
  MISSES under `normalize_value` (trailing zero ≠ substring) — an honest fidelity signal, never
  re-rig the prompt with the answer. (2) **doc `as_of` is "first ISO wins"** (`extract_iso_date`): keep
  the period-end ISO date on the caption's **header line only**, not on per-series lines, or an early
  quarter (Q1'25) becomes the doc as_of. (3) **the $0 replay cache predates this prompt**, so it reports
  the image facts MISSING — only a **paid single-image re-extraction** validates them; `HelixPay SEA` is
  **minted** at ingest (not seeded), so confirm exactly one `HelixPay SEA` row after the run.
- **`test/golden/facts.yaml` is the MASTER oracle; `eval/smoke/facts.yaml` + `eval/sample/facts.yaml`
  are GENERATED (SP_021):** edit the master, then re-run `python -m eval.smoke.build_smoke` (and
  `eval.sample.build_sample`) — never hand-edit the generated subsets (they carry "do not hand-edit"
  banners). The smoke builder filters by `manifest.py` source_uris; the **sample** manifest does NOT
  include the image, so image facts only land in smoke. A guard (`test/golden/test_golden.py`) pins the
  image **caption** fact to `recall_bar:false` while allowing structured datapoint facts to be graded.

## SP_011 — seeded edges undated

- Seeded `reports_to`/`dotted_line_to` edges are **undated** (`as_of=None`, SP_011) so the export-dated
  `org-chart.md` edge doesn't dedupe away on the links natural key (`COALESCE(as_of,'0001-01-01')`). A DB
  seeded *before* this must be **re-seeded fresh** (changing `as_of` changes the key → a re-seed adds an
  undated twin, not a no-op). Fresh `make up && seed` unaffected.

## SP_028a / SP_028b — contradiction precision & adjudication

- **Contradiction precision: the recompute sweep is the canonical post-ingest step (SP_028a):**
  inline ingest-time `detect()` writes raw, inflated rows; `scripts/recompute_contradictions.py`
  is the single-writer **clear-then-rewrite** sweep that produces the deployed set, and MUST run
  after ingest (it took the live `helixpay_full` from **266 → 115** at $0). It applies two
  deterministic precision levers without touching `detect()`/`detect_link_conflicts()` (a thin
  `_DedupWriter` wraps the repo): (1) **cardinality skip** — a claim group whose predicate is
  explicitly `set_valued` in `helixpay/ingest/predicate_cardinality.py` (pain_point, weekly_activity,
  …) is skipped (multiplicity is legitimate); applied to the CLAIM loop ONLY (links keep their
  `_SINGLE_VALUED_LINK_TYPES` gate); unknown/functional/breakdown all KEEP (safe default — never
  silently drop a real conflict; `breakdown` like `gross_revenue` is classified-but-not-skipped
  because it's also a real company metric). (2) **value-pair dedup** — one row per distinct
  normalized value-pair (claims) / to-entity pair (links), collapsing the pairwise inflation
  (ga_target 86 = one story × many source-combos). The residual (distinct *phrasings* of one
  semantic conflict, e.g. "end of Q3" vs "Sep 30") is left for SP_028b's LLM pass. Normalizer
  sign-fix (`normalize.py` step 6b: `(?<=-)\s+(?=\d)`) lets `-SGD 2.1M` parse like `SGD -2.1M` so
  the ebitda sign/currency-order spurious class agrees. **Do NOT** add date-format or rounding
  equivalence to the shared `normalize.py` — it has 8 callers incl. the eval matcher, and
  `2026-05-12 ≡ May 12` drops the year → cross-year false-equality suppresses real conflicts.
- **LLM contradiction adjudication = the PAID refiner on the SP_028a sweep (SP_028b):**
  `helixpay/ingest/adjudicate.py` + `scripts/adjudicate_contradictions.py` — a post-ingest,
  single-writer clear-then-rewrite pass (run AFTER `recompute_contradictions.py`) that judges each
  subject's **cluster** with one Opus(temp-0) call: DROPS same-fact-different-words lexical
  candidates (precision) and ADDS cross-predicate claim pairs + solid-vs-dotted link pairs (recall),
  never resolving (schema has NO winner field). Baked-in rules (Stage-3/5 findings): **two labeled
  blocks** CLAIM `C1..Cn` + LINK `L1..Lm` (reports_to+dotted_line_to); a pair is `block`+two indices
  INTO that block, so a claim↔link pair (which `Contradiction` can't represent) is structurally
  impossible; out-of-range/self index drops. **Content-hash cache** keyed on `(model, PROMPT_VERSION,
  NORM_VERSION, sorted member signatures)` — NOT ids, `source_uri` EXCLUDED → re-sweep of an
  unchanged store is **$0**; bump NORM_VERSION/PROMPT_VERSION on a normalize/prompt change or a stale
  verdict is reused. **Fallback:** verdict ABSENT → SP_028a deterministic floor (shared
  `helixpay/ingest/dedup.py` `DedupWriter`); PRESENT-but-empty → authoritative (no floor, else the
  dropped pair returns). Members are **signature-sorted** before numbering (read+write) so re-seed
  ids don't move the map. `--dry-run` is print-only/$0. `MAX_CLUSTER_MEMBERS=40` → oversized subject
  (HelixPay) falls to the floor (no cross-predicate recall) and is LOGGED. Prompt uses ONLY synthetic
  values (year 2099) so the SP_027 leak guard stays green. All code+unit+db tests are $0 (stub
  client); paid Opus is the gated CLI only. Temperature seam additive: `AnthropicClient(temperature=…)`
  omits the kwarg when `None` → pre-SP_028b callers byte-identical. Live result (Sonnet, 2026-06-11):
  115 → 67 contradictions; oracle 1/8 → 2/8. Remaining 6 oracle misses are entity-fragmented
  (Northwind e252/e298, Cosmos e182/e81, HX-LOY-487 e227/e232) → conservative entity-merge = SP_029.

## SP_027 — extraction prompt de-leak

- **The extraction prompt was leaking ground truth, and a guard now blocks it (SP_027):** SP_019's
  "re-record prompt surgery" (and later SP_021/SP_026) built few-shot examples from **real graded
  corpus facts** — `extract_claims.md` literally showed the model `HelixPay revenue SGD 14.2M @
  2026-03-31`, `Project Confluence → ga_target → end of Q3 2026`, `412` net-new merchants,
  `Sara Wijaya → helixpay/core top_contributor`, etc. (15 golden bar-fact values + 3 graded
  subjects). That coaches the extractor with answers it's later graded on (DEV_RULES §12), so the
  recall number can't be trusted. SP_027 replaced every example with **synthetic** subjects/values
  (year-shifted to 2027, fictional `Project Atlas`/`Ledger migration`/`acme/core`/`J. Okafor`) that
  teach the identical shape, and added `test/unit/ingest/test_prompts.py::
  test_golden_values_and_subjects_do_not_leak_into_prompts` — it loads `eval.run.load_golden`
  bar-fact **values AND subjects**, allowlists only the structural `{HelixPay, HelixPay SEA,
  HelixPay Brasil}`, and word-boundary-scans every `prompts/*.md`. Removing the
  `Confluence platform → Project Confluence` hint is safe: `helixpay/seed/roster.py` already seeds those
  surface aliases, so canonicalization lives in the seed, not the prompt. **The de-leak only
  changes FUTURE extractions; the existing `helixpay_full` DB / `.replay-cache` were recorded under
  the leaked prompt, so a paid re-record is required to learn the true uncoached recall.**

## SP_022 / SP_023 — MCP retrieval & graph/temporal tools

- **MCP tools live on `ExposureEngine`, NOT frozen `QueryEngine` (SP_022/SP_023):** 12 = 4 frozen + 8
  optional on `ExposureEngine`+`HelixQueryEngine`, found by `_retrieval` `getattr` (`QueryEngine`-only →
  `{available:false}`); additive pure-read `Repository` reads (SP_009). SP_022:
  `search`/`fetch`/`get_sources`/`list_entities` (`search.source_as_of`=**document** date, provenance by
  chunk id not zip; `fetch`=full text, bad id→`found:false`). SP_023:
  `get_timeline`/`get_relationships`/`list_metrics`/`get_claims_by_predicate` (+`MetricVocab`; `get_links`
  +`to_entity_id`=incoming). `get_claims_by_predicate` canonicalize-matches in the **db layer** (alias set
  + period-strip `regexp_replace` `[[:space:]/-]+`; no POSIX `\b`, so `*` over-strips glued
  `"fy2026 ebitda"`→`"ebitda"`). `get_timeline` reuses via `subject_id`; `source_as_of`=**claim** period.

## SP_024 — drop taxonomy gate

- **Drop taxonomy gate (SP_024, eval-only):** `helixpay/ingest/extract/ledger.py` splits dropped
  extractions into **LOSSY** (`validation_error`/`unmappable_enum`/`unparseable_as_of`) vs
  **INTENTIONAL** (`hypothetical`/`ungrounded`); `eval/smoke/check_smoke.py:doc_verdict` gates the
  SP_015 proof on `lossy_drops` only, so benign non-assertions no longer make `items_dropped==0`
  unreachable (the paid `full_run.py` gate was structurally un-openable). **Fail-safe:** an unknown
  reason ⇒ LOSSY (computed by *exclusion* from `INTENTIONAL_DROP_REASONS`, never an allow-list — so a
  new/unknown reason can only raise severity, never silently PASS). `ungrounded` is RESERVED (never
  emitted today; the extractor penalises confidence + keeps the claim).

## SP_025 — coercion recovery & the entity-collapse guard

- **Coercion recovery (SP_025, schema):** an out-of-vocab `subject_type` coerces to `other`; an
  out-of-vocab verb coerces to `mentions` + records the original on an **additive nullable
  `links.raw_verb` column** that is **OUT of the natural key** (`(from_entity_id, to_entity_id,
  link_type, COALESCE(as_of,'0001-01-01'))`) → first-verb-wins dedup; keying `mentions` on
  `raw_verb` is an accepted follow-up. **CRITICAL fix:** the `other` fallback was feeding the SP_020
  entity-snap (`_other_compatible`), so a file/repo named like a `product`/`customer` would
  **collapse** onto it. Fix: `coerce.py` records a transient `ClaimOut.raw_subject_type`;
  `resolve_mention(allow_snap=False)` for fallback subjects (skips the seeded/other bridge, still
  dedups same-name `other`); the pipeline passes `allow_snap=claim_out.raw_subject_type is None`.
  The SP_020 *genuine*-other snap is preserved. Accepted residual (test-pinned): a fallback named
  exactly like a SEEDED `other` (company/region) still attaches to it (the SP_019 seeded-snap
  intent). `raw_verb` is surfaced in `get_relationships`.

## SP_026 — contradiction comparator & extraction robustness

- **Comparator + extraction robustness (SP_026):** `helixpay/ingest/normalize.py` strips
  letter-bearing annotation parens in the **numeric path only** (digit-only accounting negatives are
  deliberately preserved; the text copy is untouched) so "same number, different annotation" stops
  registering as a contradiction. `helixpay/ingest/extract/llm.py` raised `_MAX_TOKENS`
  `8192 → 16384` to stop the empty-on-dense-chunk truncation drop (pay-per-generated-token, so no
  cost on small chunks). `extract_claims.md` gained a sales-pipeline/CRM section. NOTE: SP_026 was
  implemented without a persisted Stage-2 plan (the as-built rationale lives in
  `research/contradiction-recall-and-extraction-delta.md`); a plan stub was back-filled at the
  SP_024–028 merge gate. The `add_link` `raw_verb` INSERT in `62e6906` predates its `ALTER TABLE`
  column in `bac2f0f`, so that single commit is not independently bisectable against the DB —
  harmless at HEAD where both coexist.

## SP_029 — extraction-quality audit subsystem

- **The audit is read-only and advisory (SP_029):** `python -m helixpay.audit` / `make audit` judges
  what landed in the DB after an ingest/replay — the integrity/precision census the 41-fact golden
  recall oracle structurally can't give. It checks provenance chain (claim→chunk→document), grounding
  (evidence supports the value), resolution honesty (subject resolved or honestly NULL), predicate
  canonicalization; runs planted known-answer traps that pinpoint which layer broke; and prints a
  deterministic suspicious-oversampled sample to read by eye. Read-only by construction (driver
  `read_only` session, proven by an integration test that asserts a write raises). It is ADVISORY,
  NOT a CI gate (`--strict` exit-1 is opt-in) — on the full corpus there's a known ~50-ERROR +
  ~136-WARN floor, so a hard gate would be permanently red.
- **Evidence grounding is THREE-way, not exact-vs-absent (SP_029):** the shared
  `helixpay/audit/invariants.py` `evidence_grounding(evidence, chunk_text)` returns `exact`
  (byte-verbatim substring → clean), `normalized` (matches only after `casefold` + whitespace-collapse
  → **WARN `evidence_not_verbatim`**), or `absent` (not present even normalized → **ERROR
  `evidence_not_in_chunk`**). It is the single source of truth for `check_evidence`, `is_suspicious`,
  and `report._sample_flags` (they must never drift). The helper `_normalize_span` is pinned to case +
  whitespace ONLY — deliberately stricter than the producer's `grounding._norm_text` (which also folds
  punctuation) and never the shared `ingest.normalize` (8 callers incl. the eval matcher) — so a
  genuinely-wrong span (`14.2M` vs `14.3M`) can never launder into a WARN; it stays an ERROR. The
  `offsets_mismatch_evidence` ERROR is gated INSIDE the byte-exact branch, so a cosmetic claim (whose
  raw offsets point at the differently-cased chunk text) does not double-ERROR. Live `helixpay_full`
  went 322 ERROR → 50 ERROR (genuine) + 136 `evidence_not_verbatim` WARN + 0 offset-ERROR with this fix.
- **Producer non-verbatim evidence is real tech-debt the audit only SURFACES (SP_029):**
  `helixpay/ingest/pipeline.py` persists `evidence=claim_out.evidence` (the model's quote) and
  `grounding.locate_span` anchors a case/whitespace-tolerant span (`\s+`/`IGNORECASE`) returning RAW
  chunk offsets — so a lower-cased / re-spaced evidence string lands with valid offsets but is not a
  byte-exact substring. `grade()` returns `GRADE_EXACT` for such deviations (it normalizes through the
  looser `_norm_text`), so there's NO confidence penalty and NO `grounding_grade` column: the audit's
  `evidence_not_verbatim` WARN is the ONLY durable signal of it. Closing the loop (store the grade, or
  re-slice the matched raw span back into `evidence` so storage is byte-verbatim) is a future pipeline
  sprint, gated behind a paid re-record. SP_009 *aspires* to byte-verbatim spans; the shipped pipeline
  does not guarantee it.
- **Audit traps are calibrated for the 9-doc fixture (SP_029):** `no_false_revenue_contradiction` is
  INFORMATIONAL on the full corpus — real regional (SGD vs R$) / quarterly / plan-vs-actual revenue
  values legitimately contradict, so the trap correctly reports revenue contradiction rows exist (their
  precision is SP_028a/SP_028b's concern, not a pipeline bug). `confluence_ga_surfaces` and
  `two_marias_distinct` hold on both fixture and full corpus. `fetch_claim_rows` materializes the full
  claims table — fine for a bounded corpus, add a server-side cursor for 100k+.

## SP_031 — serving-path production hardening (sequenced after the SP_030 CI gate)

- **dev-gateway project interpreter (I1):** `scripts/dev-gateway.py:_project_python(root)` resolves
  the interpreter for every Python child step (pytest, validators) with precedence
  `$VIRTUAL_ENV/bin/python` → `<root>/.venv/bin/python` → `sys.executable`. The 15-entry bypass log
  had ONE root cause: the gateway was invoked under a system `python3` lacking `bs4`/`psycopg`, so
  every child step `ImportError`ed and was waived. Path-existence is the gate (a real import-probe
  would cost a subprocess); the venv is created by `uv sync --extra dev` before the gateway runs.
  Fixing the gateway's interpreter propagates to all sub-validators because `run_all.py` itself
  spawns each via its own `sys.executable` (now the venv python). macOS/Linux only (`bin/python`,
  not Windows `Scripts/python.exe`).
- **Per-`ask()` resolution memo (I4) — honest scope:** `query/engine.py` `ask()` builds a FRESH local
  dict each call and threads it into `_resolve_subjects`, which memoizes `resolve_entity` keyed on
  `term.strip().lower()`. It MUST be per-call, never an instance attribute — a long-lived engine memo
  would serve a stale `None`/entity across requests after an ingest (a real correctness bug). But
  `_candidate_terms` already dedups terms case-sensitively (`dict.fromkeys`, `_WORD_RE` preserves
  case), so the memo only collapses **case/whitespace-variant** lookups ("Revenue" vs "revenue") —
  NOT the dominant cost of many distinct names. The true 40→1 collapse needs a batch
  `Repository.resolve_entities(terms)`, which is a **frozen-contract change → Foundational, deferred**
  (propose-don't-fork). The memo key is valid only because this call site passes neither
  `entity_type` nor `context`.
- **assert→raise on infra post-conditions (I2):** the 6 `assert row is not None` guards in
  `db/repository.py` (add_document/add_chunks/upsert_entity/add_claim) + `db/audit_queries.py`
  (count(*) rows) are `raise RuntimeError(...)` — they guard real dereferences and would vanish under
  `python -O`. CI-verified by the integration job (they sit on already-covered count(*)/hash paths).
- **`_as_of_filter` helper (I5):** the org `as_of` validity clause lives in ONE
  `PostgresRepository._as_of_filter(as_of) -> (sql_fragment, params)` reused by `_org_root_id`,
  `_reports_to_edges`, `_dotted_reports_map`. Replaced `_org_root_id`'s f-string SQL; the fragment is
  a fixed constant, all values `%s`-parameterized. `_org_root_id` embeds the clause twice (main +
  NOT IN subquery) → `params + params` (4 placeholders). Behavior-identical.
- **Audit layer-break is INTENTIONAL (I6/D1):** `audit/run.py` reaches `db.audit_queries` directly,
  bypassing the frozen `Repository` Protocol. In-bounds ONLY under two invariants documented at the
  import site: (1) READ-ONLY (read-only session, never mutates), (2) CENSUS/INTROSPECTION not domain
  serving (count(*), schema-column checks, raw fact rows the Protocol doesn't expose). A future
  mutating or domain-serving call there is OUT of bounds — route it through `Repository`. NOT a code
  change — accepted-and-documented (adding census reads to the frozen Protocol would fork it for a
  one-off consumer).
- **Org `as_of` xfails were stale tests, not bugs (I9/D3):** undated seeded `reports_to`/`dotted_line_to`
  edges (SP_011, `as_of=None`) have NO temporal lower bound, so they correctly remain visible under any
  `as_of`. The xfailed tests asserted an early `as_of` *empties* the chart — the wrong temporal model.
  Fix was the TEST, never `get_org_subtree` (filtering undated edges would regress SP_011's
  export-dedup). The repository test pins BOTH halves now: undated persists AND a genuinely dated edge
  (isolated `reports_to` queried by explicit `root_id`) IS filtered before its `as_of`.
- **Live-detector skip guards the missing relation (I9/D4):** on an empty CI pgvector with no schema,
  `get_contradictions` raises `relation "contradictions" does not exist` (and aborts the txn) BEFORE
  any row-count skip. Guard with `SELECT to_regclass('public.contradictions')` (NULL when absent,
  never raises) and `pytest.skip`.
- **Combined coverage is ADVISORY, the gate flip is DEFERRED (I8):** the unit (`gateway`) and db
  (`integration`) jobs each emit a `.coverage.*` artifact; a third `continue-on-error` `coverage` job
  combines them → `coverage.xml` (advisory artifact). It does NOT gate deploy. Flipping
  `.validators.yml` `coverage.require_report: true` (80% enforcing) is deferred until the COMBINED
  number is observed ≥80% in CI — gating on an unverified threshold would red every PR (Stage-3
  CRITICAL). Unit-half measured at 85% locally, so the union clears 80% comfortably; the flip is a
  low-risk one-liner follow-up.
