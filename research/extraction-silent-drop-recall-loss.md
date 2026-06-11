# HelixPay Extraction — Silent Recall Loss (two defects: empty-on-dense + validate-without-repair)

**Scope:** Why the SP_010 paid extraction silently produced **zero** claims/relations
for the highest-value structured documents (both HTML dashboards, the markdown
org chart) **and** dropped ~24% of everything the model emitted everywhere else. Why
both are invisible at run time, and why they bake a recall loss into the production
`pg_dump` seed unless fixed before the seed is frozen.

**Surfaced from:** the SP_010 `make ingest-record` run (container
`helixpay-app-run-819183e4a73a`, 2026-06-10, all 44 docs / 98 chunks cached, exit 0),
while root-causing an empty `org-chart.md` cache entry. Research only — no code
changed. `file:line` refs are the main working tree.

**Companion to:** `image-ingestion-fidelity-loss.md` (a *third*, different loss —
caption-only image flattening). Note the irony in Part 1: that doc worried the
vision-captioned org chart would lose the graph; in this run the **image** org chart
extracted richly (38 claims / 17 relations) while the **clean markdown** org chart
extracted **nothing**.

---

## TL;DR

Two independent defects, both in the post-LLM extraction path, both silent:

- **Defect A — dense chunks come back empty.** The 3 most fact-dense, highest-value
  docs cached `{"claims":[],"relations":[]}`: `data/dashboards/april-2026-kpi-dashboard.html`,
  `data/dashboards/sales-pipeline-2026-04-21.html`, and `data/org-chart.md` (both
  chunks). Chunking and the prompt are fine; the chunks are clean and ISO-dated.
  Leading cause: the extraction call is capped at `max_tokens=4096` (`llm.py:26`); a
  fact-dense chunk's JSON answer overflows, fails to parse, the single repair attempt
  overflows again, and `call_structured` returns `None` → `extract()` returns an empty
  `ExtractionOut` (`extractor.py:83-84`). The **image** org chart survives precisely
  because its caption is pre-capped to 1024 tokens of prose (fewer facts → fits).
- **Defect B — valid items are dropped, never repaired.** `_validate_items`
  (`extractor.py:209-220`) strict-validates each item and **drops** on any
  `ValidationError`, with no per-item coercion. Measured ≈**24% loss** (≈20% of
  claims, ≈37% of relations) from natural emissions the schema rejects (non-ISO
  `as_of`, off-enum `subject_type`/`link_type`).
- **Impact:** at least **7 `recall_bar` golden facts are at risk** — the two org
  reporting links + headcount (org-chart.md empty), and the dashboard revenue + NPS
  (april-kpi empty). The **NPS-framing contradiction** loses its dashboard side (47),
  so it may not be detectable at all.
- **The cache stores only post-loss results; raw model output is not saved.** The lost
  items are **unrecoverable without re-extraction**. This run — and the `pg_dump`
  intended as the DigitalOcean seed — carries both losses unless fixed and the
  affected docs re-recorded first. Neither defect blocks local SP_009/010 closure;
  both should gate the **production seed**.

---

## Part 1 — Defect A: dense chunks return empty (the high-value docs)

### 1.1 What's empty (full run, 44 docs)
Per-doc survivor counts from the cache:

| doc | chunks | claims | rel | |
|---|---:|---:|---:|---|
| `dashboards/april-2026-kpi-dashboard.html` | 1 | **0** | **0** | ← revenue 14.2M, NPS 47, full segment table |
| `dashboards/sales-pipeline-2026-04-21.html` | 1 | **0** | **0** | ← pipeline table |
| `org-chart.md` | 2 | **0** | **0** | ← reports_to graph + headcount 274 |
| `images/org-chart-snapshot.jpeg` | 1 | 38 | 17 | the *same* org chart, vision-captioned — **works** |
| `q1-2026-results.pdf` | 2 | 44 | 2 | chunk 0 empty, chunk 1 rescued it |
| `board-deck-q1-2026.pdf` | 1 | 41 | 4 | fine |
| `all-hands-2026-04-15.md` | 3 | 48 | 29 | fine (prose) |

The pattern is **density**, not format: the docs that are essentially one dense table
(HTML dashboards, the markdown org roster) come back empty; prose and lighter chunks
extract. Dense docs with a *lighter sibling chunk* (q1-results) survive in that
sibling.

### 1.2 Why — it is not chunking, prompt, or `as_of`
The HTML loader hands the extractor a pristine chunk (reproduced via
`HtmlConnector().load(...)`, 1326 chars, every value ISO-dated):

```
Q1 2026 Revenue (SGD) — 14.2M — −11% vs plan · +5% YoY (as of 2026-04-21)
Net New Merchants Q1 — 412 — 108% of plan (as of 2026-04-21)
Aggregate NPS — 47 — +1 vs Q4 (as of 2026-04-21)
…
NPS by segment — Q1 2026 (as of 2026-04-21)
| Segment | NPS | n | vs Q4 |
| SEA enterprise | 62 | 47 | +9 |
| Aggregate | 47 | 786 | +1 |
…
```

This is trivially extractable (clean lines, ISO dates → Defect B can't apply here), yet
it produced zero. The remaining lossy stage is `call_structured` →
`extract()`'s `if base is None: return ExtractionOut()` (`extractor.py:83-84`).

**Leading mechanism — output-token truncation:**
- The extraction response is capped at `_MAX_TOKENS = 4096` (`llm.py:26`).
- `org-chart.md` chunk 0 alone implies ~22 people × (reports_to + title + location)
  ≈ 60+ items × ~80 tok ≈ **>4096 output tokens** → the JSON is truncated.
- `_extract_json_object` (`llm.py:64-72`) then grabs `text[first "{" : last "}"]`; a
  truncated object has no closing brace for the outer object, so this yields malformed
  JSON → `_try_parse` fails → one repair turn (`llm.py:125`) re-asks and **truncates
  again** → `call_structured` returns `None` → empty `ExtractionOut`.
- The dashboards are borderline on size; for them an **empty model reply** (dense KPI
  grid read as a "summary") is also possible. Both routes converge on the same
  `None → empty` path.

**Confirm cheaply:** one `--force` re-extract of a single empty chunk (cents) with the
raw reply logged distinguishes "truncated/parse-fail" from "model returned empty". The
run's own logs are gone (the `--rm` container was removed on exit), so this is the only
way to nail the exact route.

### 1.3 Why it was invisible
`call_structured` logs a `WARNING` on drop-after-repair, but the pipeline emits **no
end-of-run summary** of empty chunks or dropped counts, so three fully-empty
high-value docs sailed through a clean `exit 0`.

---

## Part 2 — Defect B: validate-without-repair drops ~24%

### 2.1 The drop path
`ChunkExtractor._validate_items` (`extractor.py:209-220`) runs each model item through
strict Pydantic and **drops** on `ValidationError` — no coercion, no per-item repair.
The pipeline's "repair" (`call_structured`, `llm.py:97`) only fixes the JSON
**envelope** (`RawExtraction.claims: list[dict]`, `schemas.py:140`); a well-formed dict
with an off-schema field decodes fine, then dies in `_validate_items`. Grounding
(`extractor.py:96,198`) only *penalises confidence*, never drops (correct);
hypotheticals are dropped by design (correct). The only non-deliberate loss is
`_validate_items`.

### 2.2 What valid output the schema rejects (proven against the live models)
The enums equal the prompt's advertised values
(`EntityType = person|team|customer|product|metric|other`,
`LinkType = reports_to|dotted_line_to|owns|member_of|mentions`); the loss is the model
paraphrasing them, plus non-ISO dates the prompt itself invites:

| Model emits (natural for the corpus) | Verdict | Field |
|---|---|---|
| relation `link_type: "manages" / "leads" / "part_of"` | **DROP** | not in `LinkType` |
| relation `link_type: "reports_to" / "member_of"` + ISO | PASS | — |
| claim `subject_type: "company" / "organization"` (HelixPay headcount) | **DROP** | not in `EntityType` |
| claim `subject_type: "role" / "title"` | **DROP** | — |
| claim `as_of: "Q1 2026" / "2026" / "April 2026"` | **DROP** | `_iso_as_of` |
| claim `headcount` + `subject_type: other` + ISO | PASS | — |

**Self-own:** `extract_claims.md:30` offers *"tables say Q1 2026"* as an `as_of`
example, but `ClaimOut._iso_as_of` (`schemas.py:69-74`) rejects exactly that. And
`subject_type` is `Optional` — a bad *label* discards the whole grounded claim rather
than just nulling the label.

### 2.3 Measured rate (partial reading at 37/44 docs, before logs were lost)
| | Survived | Dropped | Rate |
|---|---:|---:|---:|
| Claims | 1,547 | 398 | **20%** |
| Relations | 378 | 225 | **37%** |
| Total | 1,925 | 623 | **~24%** |

Final run survivors (44 docs): **1,935 claims + 516 relations = 2,451**. The final drop
totals are ≥623 (the container logs were removed with `--rm`, so the exact final count
is not recoverable — a reason Part 5 #5 matters).

---

## Part 3 — Golden-fact / contradiction impact

Eval matches a fact to a claim by **source basename** (`eval/run.py:114`), so a fact
must be cited by a claim from *its own* source document.

| Golden fact (`recall_bar: true`) | Source | Status |
|---|---|---|
| `org-daniel-reports-arjun` | `org-chart.md` | **FAIL** — doc empty; interview edges cite wrong basename; image edges cite the `.jpeg` |
| `org-sara-reports-daniel` | `org-chart.md` | **FAIL** — same |
| `org-headcount` (274) | `org-chart.md` | **FAIL** — "274" lives only here (overview.md says "~275") |
| `html-dashboard-revenue` (14.2M) | `april-…-kpi-dashboard.html` | **FAIL** — chunk empty |
| `html-dashboard-nps` (47) | `april-…-kpi-dashboard.html` | **FAIL** — chunk empty |
| `pdf-results-revenue` / `…-net-new-merchants` (412) | `q1-2026-results.pdf` | likely OK — chunk 1 kept 44 claims (verify 14.2M / 412 present) |

**Contradiction risk:** the **NPS-framing** contradiction (aggregate 47 vs SEA-enterprise
62) loses its dashboard **47** side (april-kpi empty); the all-hands **62** side
survived. A one-sided contradiction is not detectable → the planted trap may silently
no-op. The Confluence GA-timeline contradiction is unaffected (its sources —
all-hands, board-deck, board-update — all extracted).

---

## Part 4 — Production-seed implication

The replay cache stores only the surviving `ExtractionOut`; raw model output is gone, so
recovering either loss requires **re-extraction**, not a replay. As-is, this run and the
`pg_dump` planned as the production seed carry: 3 high-value docs at zero, the
NPS-framing contradiction one-sided, and ~24% of everything else dropped. This should
**gate the production seed**; it does not block local SP_009/010 closure (the surviving
2,451 items are valid and replayable for the dev loop).

---

## Part 5 — Options (for the orchestrator / extractor owner; nothing changed here)

1. **Defect A — stop losing dense chunks.** Any of, ideally all:
   - raise extraction `max_tokens` (4096 → 8192+) so dense answers fit;
   - on truncation/parse-fail, **retry with a smaller chunk** (split and re-extract)
     instead of returning empty;
   - shrink the chunker's `target/max_tokens` for table-dominant chunks so fact density
     per chunk stays within the output budget.
2. **Defect B — repair-then-validate in `_validate_items`.** Coerce before raising and,
   for `Optional` fields, prefer null-the-field over drop-the-item:
   - `as_of`: normalise quarter/partial dates → ISO (`Q1 2026` → `2026-03-31`;
     `2026`/`April 2026` → doc `as_of` / month-start); else null it.
   - `subject_type`: map synonyms (`company`/`organization` → `other`) or null it.
   - `link_type`: map onto the enum (`manages`/`oversees`/`leads` → `reports_to` w/
     `from`/`to` swapped; `works_for` → `reports_to`; `part_of` → `member_of`).
   - Invariant: a bad value on one field must not discard a well-grounded item.
3. **Prompt fix** (`extract_claims.md:30`): stop offering `Q1 2026` as an `as_of`
   example, or document quarter→quarter-end normalisation.
4. **Make loss loud (defence-in-depth):** emit an end-of-run pipeline summary of empty
   chunks + dropped claim/relation counts (and the failing field name on each drop), so
   a 24% loss + 3 empty high-value docs can never again pass a clean `exit 0`.
5. **Recover & validate cheaply:** after the fixes, `--force` re-record. Prove on the
   curated 11-doc sample (`eval/sample/`, already built for these traps — it includes
   org-chart, april-kpi, q1-results) — ~5–6 min, cents — and confirm the 7 at-risk facts
   + the NPS-framing contradiction return before deciding a full corpus re-record ahead
   of the production seed.

These are recommendations only; the extractor + extraction prompt sit on the Agent-2
boundary and belong in a planned slice, not an ad-hoc edit.

---

## Appendix — Evidence index

| Claim | Location / evidence |
|---|---|
| extraction call capped at 4096 output tokens | `helixpay/ingest/extract/llm.py:26` |
| `None` from `call_structured` → empty `ExtractionOut` | `extractor.py:83-84`; `llm.py:111-135` |
| truncated JSON grabbed first`{`→last`}` then fails | `llm.py:64-72` (`_extract_json_object`), `75-85` (`_try_parse`) |
| single repair attempt only | `llm.py:124-135` |
| per-item validate-and-drop, no repair | `extractor.py:209-220` (`_validate_items`) |
| grounding penalises, never drops | `extractor.py:96,198-206` |
| `as_of` strict ISO / `subject_type` / `link_type` enums | `schemas.py:69-74, 62-67, 101-106` |
| enums = prompt's advertised values | `helixpay/contracts/models.py:35,44` |
| prompt invites `Q1 2026` as_of (self-own) | `prompts/extract_claims.md:30` |
| dashboard chunk is clean + ISO-dated, still empty | reproduced via `HtmlConnector().load("data/dashboards/april-2026-kpi-dashboard.html")` |
| empty docs: 2 dashboards + org-chart (both chunks) | `.replay-cache/` per-doc survivor scan (44 docs) |
| image org chart works (38 claims/17 rel) vs text org chart (0/0) | same scan |
| survivors 1,935 claim / 516 relation (44 docs) | sum over `.replay-cache/*.json` |
| drop reading 398 claim / 225 relation (~24%) at 37/44 | container logs before `--rm` removal |
| org facts pinned to org-chart.md, recall_bar | `test/golden/facts.yaml:206,222,236` |
| dashboard revenue/NPS golden facts | `test/golden/facts.yaml` (`html-dashboard-revenue`, `html-dashboard-nps`) |
| eval matches fact↔claim by source basename | `eval/run.py:114` |
| cache stores post-loss only (raw lost) | `replay.py` writes the filtered `ExtractionOut` from `ChunkExtractor.extract` |
