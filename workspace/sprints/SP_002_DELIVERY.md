# SP_002 Delivery Report — Loaders / Ingestion Normalization (Agent 1)

**Branch:** `sprint/SP_002-loaders` · **Worktree:** `.claude/worktrees/SP_002` ·
**Status:** Complete · **Tier:** Standard

## What shipped

One `SourceConnector` per `source_type` plus a registry, normalizing every raw
`data/` file into a frozen `Document` + ordered `Chunk`s. **No DB, no extraction,
no embedding** — the slice stops at the `Chunk` contract (Agent 2's input).

- `helixpay/ingest/loaders/base.py` — shared substrate: `normalize_text` +
  `compute_content_hash`/`compute_bytes_hash` (idempotency), `estimate_tokens`
  (chars/4), `Segment` + `chunk_segments` (boundary-aware packer; tables and
  chat/email messages are `splittable=False` and never split), `segment_markdown`,
  `extract_iso_date` (labelled-stamp → `Date:` → plain → filename precedence),
  `render_table`, `to_chunks`, `LoaderError`, module logger.
- Seven connectors: `markdown`, `pdf` (pdfplumber text+tables), `html`
  (BeautifulSoup/stdlib parser), `slack`, `email`, `code`, `image` (injectable
  vision caption).
- `helixpay/ingest/loaders/__init__.py` — `all_connectors()` + `discover_all(root)`
  with a disjointness guard (raises `LoaderError` on any double-claimed path).

## Connector → path map (44 files, each claimed exactly once)

| source_type | discovery rule | files |
|---|---|---|
| `md` | `data/*.md` (non-recursive) + `data/interviews/**/*.md` | 29 |
| `pdf` | `data/*.pdf` | 2 |
| `html` | `data/dashboards/*.html` | 3 |
| `slack` | `data/chat/*.md` | 3 |
| `email` | `data/email/*.md` | 2 |
| `code` | `data/code/*.md` | 1 |
| `image` | `data/images/*.{jpeg,jpg,png}` | 4 |

Discovery is **directory-scoped**, not extension-based — that is what keeps the
shared `.md` extension (interviews vs chat vs email vs code) from being
double-claimed. `board-update-2026-04-22.md` is email-shaped but top-level, so it
is owned by `md` per the brief's map (handled: no H1 → `title=None`, `as_of` from
its `Date:` header).

## Tests / checks (run with the worktree venv + declared deps)

- `uv run pytest test` → **79 passed, 12 skipped** (skips: DB-gated + the live
  image-vision smoke without a key).
- `uv run pytest -m smoke test/unit/loaders` → **5 passed, 1 skipped**: real
  `data/` — all 44 files claimed once, per-connector counts exact, every
  non-image file parses to a contract-valid `Document` + non-empty `Chunk`s,
  idempotent `content_hash`, dashboard chunks carry value+as-of.
- `uv run mypy helixpay` → **clean** (26 files).
- Gates: pre-impl ✓, post-impl ✓, worktree-isolation ✓, sprint-overlap ✓.

## Files that resisted clean parsing / judgement calls

- **PDFs have several dates.** `q1-2026-results.pdf` mentions the reporting period
  (`1 January 2026 – 31 March 2026`) *and* `Issued: 15 April 2026`; `board-deck`
  carries the board-meeting date `12 May 2026`. `extract_iso_date` prefers a
  **labelled** stamp (Issued/Generated/As-of/…) over an unlabelled period-start
  date, so q1-results → 2026-04-15 and board-deck → 2026-05-12. Document-level
  `as_of` is a coarse default; per-claim `as_of` is Agent 2's job.
- **`sales-pipeline-2026-04-21.html`** has no `As of` label (subtitle is
  `"Hybrid view … · 2026-04-21 09:00 SGT"`); the HTML connector falls back to the
  first ISO date in the subtitle/stamp/filename, so it still dates correctly.
- **Image vision is untested against the live API** here (no `ANTHROPIC_API_KEY`).
  The caption seam is exercised in units with a stub on the **real JPEG bytes**
  (discovery + byte read + media-type), and the live path self-skips. The default
  caption fn lazily imports `anthropic` so the package imports without the SDK/key.

## New gotchas (for the orchestrator to fold into CLAUDE.md §7)

- **Image `content_hash` is over the image bytes, not the caption** — a vision
  caption is non-deterministic, so hashing it would break idempotent re-ingest.
- **Discovery must be by directory, not extension** — interviews/chat/email/code
  all use `.md`; a recursive `**/*.md` would double-claim. `md` uses non-recursive
  `*.md` + `interviews/**`.
- **The chunker preserves atomicity over budget** — a single table or chat message
  larger than `max_tokens` is emitted whole (and logged WARNING), never split.
- **`segment_markdown` accumulates consecutive headings** (`# Interview: X` +
  `## Meta` with no body between) so the heading text (e.g. the interviewee name)
  is never dropped from chunk text — a Stage-5 plan-blind review caught the
  original drop-bug.

## Coordination / merge notes for the orchestrator

1. **Dependencies** (declared, not added to `pyproject` per the fanout rule —
   please consolidate at merge): `pdfplumber`, `beautifulsoup4`, `anthropic`.
   `beautifulsoup4` and `pdfplumber` ship inline types — **do not** add
   `types-beautifulsoup4` (would make the (absent) ignore comments unused; none
   are present). No `lxml` needed (stdlib `html.parser`).
2. **`helixpay/ingest/__init__.py`** — I created the parent-package marker (a
   4-line docstring) because the `loaders` subpackage needs it to import. Agent 2
   (`helixpay/ingest/extract/**`, `pipeline.py`, `embed.py`) also needs this exact
   file; treat it as shared scaffolding — the merge is trivial (identical intent).
3. **Meta-docs left for orchestrator reconciliation** (fanout rule — not edited in
   the worktree): `FEATURE_LIST.md` (features `ingest-loaders`,
   `source-connectors`, `chunking`), `CODEBASE_STRUCTURE.md`
   (`helixpay/ingest/loaders/` layout), `PROGRESS.md`. The dev-gateway's
   doc-freshness stage flags these (F-2/F-4) by design in the parallel model.
4. **`PROGRESS.md` pointer is intentionally uncommitted** — set to `**Current:**
   SP_002` in the worktree only to satisfy the local pre-impl gate's active-sprint
   detection (commit-subject + PROGRESS). Its absence from my diff is deliberate,
   not a missed step.
5. **Pre-existing gateway Stage-A failures** reference *other* agents' future paths
   (`SP_003/6/7`, `helixpay/ingest/pipeline.py`, `helixpay/ingest/embed.py`,
   `test/golden/facts.yaml`) from the sibling `fanout/AGENT_*.md` briefs — out of
   this slice's scope.

## Hand-off to Agent 2

Consume `(connector, path)` from `discover_all('data')`, then `connector.load(path)`
→ `(Document, list[Chunk])`. `Chunk.document_id` is `None` (assign at persist time);
`ordinal` is set. Chunks preserve section/speaker/table boundaries and HTML metric
value+as-of pairings — the substrate your claim/contradiction extraction reads from.
