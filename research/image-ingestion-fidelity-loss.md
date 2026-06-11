# HelixPay Ingest — Image Fidelity Loss in the Loaders Slice

**Scope:** Why the SP_002 loaders reduce every image to a single prose caption,
what structured data that destroys, and why the four `data/images/*.jpeg` files are
the *worst* sources in the corpus to degrade this way. Includes the second, separate
"skip": **no test exercises the real images end-to-end.**

**Companion to:** `extraction-design-and-best-practices.md` (Agent 2 consumes the
`Chunk`s this describes) and `ingest-append-and-task-fit.md`. Research only —
planning/implementation is left to other agents. `file:line` refs are the
`sprint/SP_002-loaders` worktree (`.claude/worktrees/SP_002/`) unless noted.

---

## TL;DR

- **Images are not skipped at discovery or load.** `ImageConnector.discover()` finds
  all 4 JPEGs and `load()` returns a contract-valid `Document` + one `Chunk` each.
- **The loss is a deliberate scope cut *inside* the loader:** the image degrades to a
  single ~1024-token prose **vision caption** — "deep figure OCR is an explicit scope
  cut" (`helixpay/ingest/loaders/image.py:3-4`). The caption becomes **one chunk**
  via `to_chunks([text])` (`image.py:115`), bypassing the boundary-aware chunker that
  keeps every *text* table/message atomic.
- **A second, real skip: verification.** The real-image smoke test self-skips without
  `ANTHROPIC_API_KEY` (`test/unit/loaders/test_smoke.py:91`), the non-image smoke test
  explicitly `continue`s past images (`test_smoke.py:57`), and the fast units stub the
  caption with fake bytes. **No test ever runs the 4 real images end-to-end.**
- **The 4 images are disproportionately high-value:** they carry the org `reports_to`
  graph (entity-resolution backbone), a financial reconciliation table with a known
  discrepancy, and the revenue series that intersects the planted Q1 contradiction.
  These are exactly the structures a prose caption flattens and a vision model
  mis-reads — and nothing tests the result.
- **Net:** per-image *existence* is fine (discovered, byte-hashed, idempotent). All
  *internal structure* — graph edges, table cells, axis-precise numbers — collapses
  into one unverified paragraph. For the highest-value files in `data/`, the
  caption-only path is the weakest link in the entire ingest.

---

## Part 1 — What the loader actually does

### 1.1 The path, step by step (`helixpay/ingest/loaders/image.py`)

| Step | Code | Effect |
|---|---|---|
| discover | `discover()` globs `images/*.{jpeg,jpg,png}` (`image.py:85-89`) | all 4 files found; **not skipped** |
| read | `Path(path).read_bytes()` (`image.py:93`) | bytes in memory; `OSError` → `LoaderError` |
| caption | `caption_fn(data, media_type)` (`image.py:100`) | one Anthropic vision call, **`max_tokens=1024`** (`image.py:69`) |
| hash | `compute_bytes_hash(data)` (`image.py:112`) | idempotency over **bytes**, not the (non-deterministic) caption — correct |
| date | `extract_iso_date(caption, fallback_path=path)` (`image.py:111`) | as_of scraped from the **model's prose**; silently falls back to filename |
| chunk | `to_chunks([text])` (`image.py:115`) | **single chunk** — no `chunk_segments`, no atomic-table/segment handling |

### 1.2 Where the loss is — three compounding flattenings

1. **Structure → prose.** The caption prompt asks for a *factual caption* that
   "transcribe[s] every visible number" (`image.py:37-42`) — but a table's row/column
   topology and a graph's edge set have no faithful prose encoding. A `reports_to`
   tree becomes sentences; a 24-cell ledger becomes a paragraph.
2. **Many units → one chunk.** Every *text* source runs through `chunk_segments`,
   which keeps each table and each chat/email message atomic and ordinal. Images skip
   it entirely (`to_chunks([text])`, `image.py:115`): the whole image is **chunk 0**,
   so downstream retrieval can't isolate "the Brasil row" or "the Daniel Tan node."
3. **1024-token cap.** `max_tokens=1024` (`image.py:69`) bounds the caption. A dense
   table or a 20-node org chart transcribed verbatim can exceed it and truncate
   silently — no error, no WARNING (unlike the chunker's over-budget atomic-unit
   WARNING for text).

Plus two reliability gaps: the caption is **non-deterministic** (re-runs differ; only
the byte-hash is stable, so the *Document* is idempotent but its *text* is not), and
`as_of` depends on the model emitting the date — if it doesn't, the date degrades to
the filename with no signal that it happened.

---

## Part 2 — The verification gap (the real "skip")

Three facts in the test suite mean **the 4 real images are never validated end-to-end**:

- `test_every_non_image_file_parses_to_valid_document_and_chunks` **explicitly
  `continue`s** when `source_type == image` (`test/unit/loaders/test_smoke.py:54-57`).
- `test_real_images_caption_via_vision` **`pytest.skip`s** unless `ANTHROPIC_API_KEY`
  is set (`test_smoke.py:90-92`) — and even when it runs, it asserts only that a
  non-empty chunk exists, **not** that any specific number/edge survived.
- The fast unit tests inject a stub `caption_fn` over *fake* bytes
  (`test/unit/loaders/test_image.py:19-34`), so they prove the *plumbing* (media-type,
  single chunk, date-from-caption, byte-hash) but never touch real image content.

So the suite proves the connector *wires up* correctly and self-skips the only test
that would catch a bad caption. This is the behavior most likely read as "the loader
skips images."

---

## Part 3 — What's in the four files (and why degrading them hurts most)

I opened all four. Ranked by structure-loss severity:

### 3.1 `org-chart-snapshot.jpeg` — CRITICAL (graph data)
Header "HelixPay Org Chart Explorer · Snapshot · 2026-04-15." A full `reports_to`
tree: **Wei Chen** (CEO) → **Priya Raman** (COO), **Lim Boon Hock** (CFO),
**Arjun Kapoor** (CTO), **Sofia Almeida** (CRO / Head of Sales); **Daniel Tan**
(VP Engineering) under CTO; ~14 leaf reports including **Maria Silva** (Head of Sales,
Brasil), **Rafael Costa** (MD, HelixPay Brasil), Sara Wijaya, Luiz Ferreira, Ahmad
Rashid, Aisha Yusof, Lin Xinyi, Vikram Patel, plus COO's VPs (Hannah Park, Marco
Bianchi, Rajesh Iyer, Sarah Ng). Footer: **"Headcount: 274 · Excludes 12 contractors
· Functional dotted-lines not shown · Exported via Notion → PNG → JPEG re-encode."**

- **Why loss is worst here:** this is the **reporting backbone** for entity resolution
  — the `reports_to` edges and the disambiguation context (two Tans, two Marias).
  Edge structure has no faithful prose form, and the image has **crossing lines**
  (Sofia's reports cross toward Maria Silva / Rafael Costa) that vision models
  routinely mis-attribute. A single prose chunk can't preserve the graph, and nothing
  verifies which edges survived.
- Note: dotted-line/functional links are **explicitly absent** from this image, so
  `dotted_line_to` cannot be sourced here regardless of fidelity.

### 3.2 `merchant-reconciliation-bug.jpeg` — HIGH (dense financial table + bug metadata)
"HelixPay Merchant Portal — Reconciliation Report," merchant **Açaí Express SP**,
Period **2026-03-01 → 2026-03-31**, Generated **2026-04-04 02:11 BRT**. A table of **4
source rows** (HelixPay Core (cards), POS, Tap, Loyalty earn) × {Gross, Refunds, Net,
Loyalty redeemed} R$, then 3 summary rows: **TOTAL (per app)** R$191,390.00 Net vs
**TOTAL (per bank statement)** R$189,250.00 Net, and **DELTA +R$2,140.00** (Gross
192,660.00 ties on both sides — the gap is isolated to the Net column). A discrepancy
callout: loyalty redemptions double-counted on Net; **Issue HX-LOY-487 · Open since
2025-11-14 · ETA TBD (queued behind Confluence).**

- **Why loss matters:** ~28 body cells (4 source + 3 summary rows × 4 money columns)
  plus the app-vs-bank Net pair (191,390 vs 189,250) and an issue-ID/date that a text
  loader would keep as an atomic table chunk. Under the 1024-token caption cap and
  prose flattening, partial transcription — and loss of the exact Net pair or the
  bug-ID/date pairing — is likely.

### 3.3 `revenue-trend-q1-2026.jpeg` — HIGH (label-less line chart, feeds a planted contradiction)
"HelixPay — Revenue by region (SGD M)," Source "FP&A · Q1 2026 close." Four series
(SEA actual/plan, **Brasil actual (SGD eq)**/plan) across **5 quarters** — Q1'25, Q2'25,
Q3'25, Q4'25, Q1'26 — i.e. **20 data points**. **No data labels** — values must be read
off gridlines (Q1'26 SEA ≈ 9.3M, Brasil ≈ 4.8M; both actuals dip *below* their plan
lines at the final quarter).

- **Why loss matters most subtly:** because there are no labels, the vision model
  *also* eyeballs the numbers. This series intersects the **planted Q1 revenue/ARR
  contradiction** that the project exists to surface (CLAUDE.md §Gotchas). Approximate
  caption figures can **manufacture a false contradiction** against the dashboard's
  `14.2`, or **miss a real one** — and there is no test to catch either.

### 3.4 `nps-by-segment-q1-2026.jpeg` — MEDIUM (bar chart *with* labels)
"HelixPay — Q1 2026 NPS by segment." Five labelled bars: SEA enterprise **62**, SEA
SMB **41**, Brasil enterprise **53**, Brasil SMB **31**, Aggregate **47**; fintech
benchmark line at **40**; Source "Gainsight, n=786 (Q1 close)."

- **Why loss is lower:** the data labels are legible, so a caption recovers the five
  values. Residual risk: no structured `(segment, metric=NPS, value, as_of)` rows, and
  the `n=786` / benchmark=40 metadata is easy to drop.

---

## Part 4 — Why this is the weakest link for *this* project

The ontology's whole point is preserving conflicting facts with source + as-of, and
keeping the two-Marias/two-Tans entities distinct (CLAUDE.md §Ontology rules). Three of
the four images carry exactly that high-value substrate:

- **org chart** → the `reports_to` graph + disambiguation context (entity resolution),
- **reconciliation** → a hard financial table with a live discrepancy,
- **revenue trend** → a series feeding the planted Q1 contradiction.

All three are reduced to one unverified prose chunk apiece, and the only test that
would catch a degraded caption self-skips. So the corpus's **highest-value,
contradiction-bearing sources** ride the loader's **lowest-fidelity, least-tested**
path.

---

## Part 5 — Options (for the orchestrator / Agent 2; nothing changed here)

Cheapest first:

1. **Loader-side, low cost (in SP_002 scope):** raise `max_tokens` (1024 → ~4096) and
   change `_CAPTION_PROMPT` (`image.py:37`) to demand a **verbatim structured
   transcription** — a markdown table for tabular images, an indented `A → B` edge
   list for the org chart — then run the existing `segment_markdown` over the result so
   tables/edges become atomic chunks like every other source. Small diff; reuses
   substrate already in `base.py`.
2. **Close the verification gap (no key needed):** add a unit that feeds a realistic
   multi-line caption through `load()` and asserts the table rows / edge lines survive
   into chunks. Catches a future prompt/segmentation regression without a live call.
3. **Hand-off note:** record that the 4 images are the lowest-fidelity sources and that
   Agent 2's extractor should treat their numbers/edges as **low-confidence claims**
   until figure-level OCR is funded.

These are recommendations only; image extraction depth sits on the SP_002 ⇄ Agent-2
boundary and belongs in a planned slice, not an ad-hoc edit.

---

## Appendix — Evidence index

| Claim | Location |
|---|---|
| scope cut: caption, not OCR | `helixpay/ingest/loaders/image.py:3-4` |
| caption prompt | `image.py:37-42` |
| `max_tokens=1024` | `image.py:69` |
| as_of from caption, filename fallback | `image.py:111` |
| byte-hash idempotency | `image.py:112` |
| single chunk, no chunker | `image.py:115` |
| discovery globs all media types | `image.py:85-89` |
| non-image smoke `continue`s past images | `test/unit/loaders/test_smoke.py:54-57` |
| real-image smoke self-skips on no key | `test_smoke.py:90-92` |
| unit stubs caption over fake bytes | `test/unit/loaders/test_image.py:19-34` |
| 4 real JPEGs on disk | `data/images/*.jpeg` |
