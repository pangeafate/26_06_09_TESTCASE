---
sprint_id: SP_002
tier: Standard
features: [ingest-loaders, source-connectors, chunking]
user_stories: []
schema_touched: false
structure_touched: true
status: In Progress
isolation: git-worktree
branch: sprint/SP_002-loaders
worktree: .claude/worktrees/SP_002
agent_owner: "Agent 1 (loaders)"
touches_paths:
  - helixpay/ingest/loaders/**
  - test/unit/loaders/**
fix_type: ""
touches_checklist_items: [loader-md, loader-pdf, loader-html, loader-image, loader-slack, loader-email, loader-code, loader-registry, loader-chunking]
---

# SP_002: Loaders / Ingestion Normalization

## Sprint Goal

Turn each raw file in `data/` into a contract-valid `Document` + ordered `Chunk`s via
one `SourceConnector` per format (md, pdf, html, image, slack, email, code), plus a
boundary-aware chunker and a registry so the pipeline can discover every connector.
This is Agent 1 of `HELIXPAY_BUILD_SPEC.md` §5 (`fanout/AGENT_1_loaders.md`). The slice
**normalizes bytes into the `Chunk` contract only** — it does not extract claims, embed,
resolve entities, or touch the DB (those are Agent 2). It depends on `helixpay.contracts`
alone. The output is consumed by Agent 2's pipeline through the frozen `Chunk`/`Document`
types — Agents 1↔2 meet only at that contract.

## Current State

- The Phase 0 gate (SP_001) is frozen on `main`: `helixpay.contracts` exports the frozen
  models + the `SourceConnector` Protocol (`source_type`, `discover(root)`, `load(path)`);
  `helixpay.config` pins `EXTRACTION_MODEL=claude-sonnet-4-6` for the vision pass.
- `data/` holds 44 files across 7 logical types. Several logical types use `.md`
  (interviews, slack, email, code), so discovery must claim **by directory**, not by
  extension, or a `.md` file would be claimed twice.
- No `helixpay/ingest/` package exists yet; no loader, no chunker, no registry.
- Parsing libraries (`pdfplumber`, `beautifulsoup4`, `anthropic`) are not yet in the
  shared `pyproject.toml` — declared here under `## Dependencies`; the orchestrator
  consolidates them at merge (fanout rule — do not edit `[project].dependencies`).

## Desired End State

- `helixpay/ingest/loaders/` provides one `SourceConnector` impl per `source_type` with
  **disjoint, directory/content-based discovery** (no file claimed twice) and a registry:
  `all_connectors()` and `discover_all(root)`.
- Each connector parses the **real** files in its column into a contract-valid `Document`
  (`source_uri`, `source_type`, `content_hash`, `as_of` from the document's own date when
  present, `title`/`author` where parseable, `raw_text`) plus ordered `Chunk`s
  (`ordinal` set; `document_id=None`, assigned at persist time by the pipeline).
- `content_hash` is a stable sha256 of normalized content so re-ingest is idempotent.
- Chunking targets ~500–800 tokens and **preserves speaker/section/table boundaries** —
  never splits mid-turn or mid-table.
- HTML dashboard chunks carry **both the metric value and its as-of date** (that is where
  the planted contradictions hide).
- Image captioning runs through an **injectable** function (default = Anthropic vision,
  `claude-sonnet-4-6`) so unit tests stub it — **no network/secret in unit tests**.
- `discover_all('data')` claims all 44 files exactly once (asserted in a `smoke` test).
- `uv run pytest test` green; `uv run mypy helixpay/ingest/loaders` clean.

## What We're NOT Doing

- No claim/relation extraction, embeddings, entity resolution, contradiction detection, or
  DB writes — that is Agent 2 (`helixpay/ingest/extract/**`, `pipeline.py`, `embed.py`).
  This slice stops at `Document` + `Chunk`.
- No deep figure OCR on JPEGs — vision is a **caption-level** pass (explicit scope cut per
  the brief; degrade to caption, not a structured figure parse).
- No edits to `helixpay/contracts/**` (frozen), `pyproject.toml [project].dependencies`,
  `CLAUDE.md`, or meta-docs — those collide at merge and are orchestrator-owned.
- No `tsv`/`embedding` on `Chunk` — they are downstream storage concerns by contract.

## Technical Approach

1. **`loaders/base.py` — shared substrate (pure, no I/O beyond reading the given file):**
   - `compute_content_hash(text)` → sha256 of normalized text (normalize line endings,
     strip trailing whitespace) for idempotent re-ingest.
   - `estimate_tokens(text)` → chars/4 heuristic (no tokenizer dependency).
   - `chunk_segments(segments, *, max_tokens=800, target_tokens=650)` → greedily packs
     **atomic** segments into chunk texts, never splitting an atomic segment; oversize
     non-table segments soft-split on paragraph then sentence boundaries; **table segments
     are never split**. Returns chunk strings.
   - `to_chunks(texts)` → `list[Chunk]` with `ordinal` assigned, `document_id=None`.
   - `extract_iso_date(text, *, fallback_path=None)` → first explicit document date
     (ISO `YYYY-MM-DD`, `DD Month YYYY`, RFC-2822 `Date:` header, "As of YYYY-MM-DD"),
     falling back to a `YYYY-MM-DD` embedded in the filename.
   - `LoaderError` + a module `logging` logger (GL-ERROR-LOGGING; native logging is
     acceptable for this straightforward parse layer). Parse failures are logged with the
     file + format and re-raised — **never swallowed**; secrets/keys are never logged.
2. **One connector per `source_type`, disjoint discovery (claims by directory):**
   - `markdown.py` `MarkdownConnector(source_type="md")` — discover `data/*.md`
     (non-recursive) + `data/interviews/**/*.md`; segment by headings, keep tables atomic,
     preserve section order; title from H1, `as_of` from header/filename.
   - `pdf.py` `PdfConnector(source_type="pdf")` — discover `data/*.pdf`; pdfplumber text +
     `extract_tables()`; a pure `render_page(text, tables)` renders tables as pipe-tables
     (unit-tested on a stub page; real parse covered by smoke). Tables carry the figures.
   - `html.py` `HtmlConnector(source_type="html")` — discover `data/dashboards/*.html`;
     BeautifulSoup (stdlib `html.parser`, no `lxml` dep). Each KPI card/section row →
     a chunk that carries the metric value **and** the doc's as-of date (parsed from the
     `As of YYYY-MM-DD` subtitle / export stamp).
   - `slack.py` `SlackConnector(source_type="slack")` — discover `data/chat/*.md`; parse
     `**<Day Mon DD HH:MM> — speaker**` message boundaries; each message is one atomic
     segment (speaker + timestamp preserved), multilingual text passed through verbatim.
   - `email.py` `EmailConnector(source_type="email")` — discover `data/email/*.md`; parse
     `From/To/Cc/Date/Subject` headers; `as_of` from `Date`; body chunked on paragraphs
     with the subject kept as chunk context.
   - `code.py` `CodeConnector(source_type="code")` — discover `data/code/*.md`; same
     markdown segmenter, tables (repo/contributor refs) kept atomic so file/author
     references stay intact.
   - `image.py` `ImageConnector(source_type="image")` — discover `data/images/*.jpeg`;
     `caption_fn: Callable[[bytes, str], str]` injectable (default lazily builds an
     Anthropic client and calls `config.EXTRACTION_MODEL` vision); one caption `Chunk`.
3. **`loaders/__init__.py` — registry:** `all_connectors()` returns every impl;
   `discover_all(root)` iterates them, raising `LoaderError` if two connectors claim the
   same path (disjointness guard), returning `list[tuple[SourceConnector, str]]`.
4. **Types/mypy:** third-party untyped imports carry `# type: ignore[import-untyped]`;
   `anthropic` imported lazily inside the default caption fn so the module imports (and
   unit tests run) without it. `mypy helixpay/ingest/loaders` must be clean.

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `helixpay/ingest/__init__.py` | Create | Package marker |
| `helixpay/ingest/loaders/__init__.py` | Create | Registry: `all_connectors`, `discover_all` |
| `helixpay/ingest/loaders/base.py` | Create | hash, token estimate, chunker, date extraction, `LoaderError`, logging |
| `helixpay/ingest/loaders/markdown.py` | Create | `MarkdownConnector` (md) |
| `helixpay/ingest/loaders/pdf.py` | Create | `PdfConnector` (pdf) + `render_page` |
| `helixpay/ingest/loaders/html.py` | Create | `HtmlConnector` (html) — value + as_of |
| `helixpay/ingest/loaders/slack.py` | Create | `SlackConnector` (slack) |
| `helixpay/ingest/loaders/email.py` | Create | `EmailConnector` (email) |
| `helixpay/ingest/loaders/code.py` | Create | `CodeConnector` (code) |
| `helixpay/ingest/loaders/image.py` | Create | `ImageConnector` (image) — injectable vision |
| `test/unit/loaders/test_base.py` | Create | hash stability, token estimate, chunker (table/message preservation), date extraction |
| `test/unit/loaders/test_markdown.py` | Create | headings/tables/title/as_of on inline md |
| `test/unit/loaders/test_pdf.py` | Create | `render_page` table rendering on a stub page |
| `test/unit/loaders/test_html.py` | Create | chunk carries metric value + as_of |
| `test/unit/loaders/test_slack.py` | Create | message-boundary preservation, multilingual |
| `test/unit/loaders/test_email.py` | Create | header parse + as_of from Date |
| `test/unit/loaders/test_code.py` | Create | file/author refs preserved |
| `test/unit/loaders/test_image.py` | Create | injected stub caption → Document + caption Chunk, no network |
| `test/unit/loaders/test_registry.py` | Create | discovery disjointness; overlap raises |
| `test/unit/loaders/test_smoke_loaders.py` | Create | `smoke`: real `data/` — all 44 claimed once, each connector parses |

## Dependencies

The orchestrator consolidates these into `pyproject.toml` at merge (do **not** edit
`[project].dependencies` in the worktree — fanout shared-file rule):

- `pdfplumber` — PDF text + table extraction (pure-Python; pulls `pdfminer.six`, `pypdfium2`).
- `beautifulsoup4` — HTML parsing (uses the stdlib `html.parser`; no `lxml` required).
- `anthropic` — vision caption pass for JPEGs (`claude-sonnet-4-6`); imported lazily and
  stubbed out of unit tests.

## Testing Strategy

Following `practices/GL-TDD.md`, red→green per unit. Two layers:

1. **Unit (no network, inline fixtures):**
   - `base`: `compute_content_hash` is stable and normalization-insensitive to CRLF/trailing
     space; `estimate_tokens` monotonic; `chunk_segments` respects `max_tokens`, never splits
     a table segment, never merges across a message boundary into an oversize chunk;
     `extract_iso_date` parses ISO / `DD Month YYYY` / RFC-2822 / filename fallback.
   - `markdown`: inline md with H1 + sections + a pipe table → chunks preserve the heading,
     keep the table intact, set `title` from H1 and `as_of` from the filename date.
   - `pdf`: `render_page(text, [[...]])` emits a pipe-table containing the figures (pure
     function; no real PDF needed at unit level).
   - `html`: inline dashboard html → at least one chunk contains both a metric **value** and
     the **as-of date**; document `as_of` parsed from the subtitle.
   - `slack`: inline export → each message kept whole with speaker + timestamp; a Portuguese
     line passes through verbatim.
   - `email`: inline thread → `From/To/Subject` parsed onto the `Document`; `as_of` = `Date`.
   - `code`: inline contributor-analysis md → repo/owner table kept atomic (file/author refs
     intact).
   - `image`: `ImageConnector(caption_fn=stub)` → one Document + one caption `Chunk`,
     `source_type="image"`, no network call.
   - `registry`: on a temp tree, `discover_all` returns disjoint pairs; a deliberately
     overlapping fake connector pair raises `LoaderError`.
2. **Smoke (`@pytest.mark.smoke`, excluded from the fast unit suite, runs the real `data/`):**
   - `discover_all('data')` returns exactly 44 unique paths; per-connector columns match the
     expected file set.
   - Each non-image connector `load()`s its real files → contract-valid `Document` + non-empty
     `Chunk`s; mypy/pydantic validation holds.
   - At least one real HTML dashboard chunk carries both a metric value and an as-of date.
   - The image smoke test skips when `ANTHROPIC_API_KEY` is unset (network/secret-gated, same
     pattern as the `db`-marked tests).

## Success Criteria

- [ ] One `SourceConnector` per `source_type`; `discover_all('data')` claims all 44 files exactly once
- [ ] Each connector returns contract-valid `Document` + ordered `Chunk`s on the real files
- [ ] `content_hash` stable across re-reads (idempotent re-ingest); `as_of` set from the doc's own date when present
- [ ] Chunking preserves speaker/section/table boundaries (no mid-turn/mid-table splits)
- [ ] HTML dashboard chunks carry the metric value **and** its as-of date
- [ ] Image vision call is injectable and stubbed in unit tests (no network/secret in units)
- [ ] `uv run pytest test` green; `uv run mypy helixpay/ingest/loaders` clean
- [ ] Stays within `touches_paths`; `helixpay/contracts/**` untouched

### Doc Reconciliation Checklist

Meta-docs are orchestrator-owned and reconciled at integration (fanout rule); this slice
records changes in its delivery report rather than editing shared meta-docs in the worktree.

- [ ] Delivery report lists the connector→path map, any file that resisted clean parsing, and new gotchas
- [ ] `CLAUDE.md` "Gotchas" additions proposed in the delivery report (orchestrator appends)

## Rule Conflict Note

`fanout/README.md` lists `PROGRESS.md` among meta-docs not to edit in a worktree, while
AGENTS.md Stage 2 and `validate_sprint.py`'s active-sprint detection require a
`**Current:** SP_002` pointer in `PROGRESS.md`. Resolution: the pointer is set in the
**worktree working tree only** to satisfy the local pre-impl gate and is **not committed**
(kept out of `touches_paths`); the orchestrator reconciles `PROGRESS.md` at integration.
Recorded per AGENTS.md repository-contract rule 3.

## Review Log

### Pre-Implementation Review

- **Iteration 1** (2026-06-09): architect-reviewer (independent sub-agent) found 0 CRITICAL, 1 HIGH, 3 MEDIUM, 2 LOW. Files reviewed: workspace/sprints/SP_002_loaders.md, fanout/AGENT_1_loaders.md, helixpay/contracts/models.py, helixpay/contracts/connector.py, fanout/README.md, data/ tree. Verdict: discovery 44/44 disjoint & complete; layer boundaries clean; contract fidelity correct.
- **Iteration 2** (2026-06-09): code-reviewer (independent sub-agent) found 3 CRITICAL, 5 HIGH, 5 MEDIUM, 3 LOW. Files reviewed: workspace/sprints/SP_002_loaders.md, fanout/AGENT_1_loaders.md, helixpay/contracts/models.py, practices/GL-ERROR-LOGGING.md, practices/GL-TDD.md, test/conftest.py, test/unit/seed/test_roster.py, and the real data/ files (overview.md, all-hands, board-update, interviews, dashboards, email, code, PDF).

**Resolution — all CRITICAL and HIGH addressed (verified against the real files):**

1. **C1 (smoke uses CWD-relative `'data'`)**: smoke tests compute an absolute
   `DATA = Path(__file__).resolve().parents[2].parent / "data"` (mirrors test_roster.py) and
   pass `str(DATA)` to `discover_all` — never a bare `'data'`.
2. **C2 (interview `Completed: 2026-04-10 10:14` is date+time)**: `extract_iso_date` is
   **substring**-based — `re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)` — so a trailing
   time component is ignored. Unit-tested on `"2026-04-10 10:14"` → `date(2026,4,10)`.
3. **C3 (`sales-pipeline-2026-04-21.html` subtitle has no "As of")**: confirmed — its
   subtitle is `"Hybrid view … · 2026-04-21 09:00 SGT"`. `HtmlConnector` as_of chain:
   first ISO date in `.subtitle` text → first ISO in `.stamp` text → ISO in filename. The
   generic first-ISO scan covers all three dashboards (`As of 2026-04-21`, `As of 2026-01-15`,
   and the bare `2026-04-21`). Tested on all three real dashboards in smoke.
4. **H1/H5 (`all-hands` and `board-update` are heading-light/heading-less)**: the markdown
   segmenter splits on **blank-line blocks** (a heading line attaches to the following block),
   so a heading-less transcript/email-md degrades to paragraph/turn segments rather than one
   giant segment. `title` is `None` when no H1 (board-update). Unit tests added for both a
   heading-less transcript (speaker turns) and a heading-less email-shaped `.md` (title None,
   as_of from the `Date:` line).
5. **H2 (image smoke would hit the real API without a key)**: the image smoke test self-skips
   when `ANTHROPIC_API_KEY` is unset (`pytest.skip`, same spirit as the `db` gate) — conftest is
   NOT edited (shared file). A separate unit test exercises the **real JPEG bytes** with a
   stubbed `caption_fn` (proves discovery + byte read + media-type detection, no network).
6. **H3/M1 (`"April 15, 2026"` month-name dates)**: `extract_iso_date` also parses
   `Month DD, YYYY` and `DD Month YYYY`; precedence = explicit ISO/As-of > month-name >
   RFC-2822 `Date:` > filename. Unit-tested on `"April 15, 2026"` → `date(2026,4,15)`.
7. **H4 / architect-MEDIUM-2 (atomic segment can exceed `max_tokens`)**: the rule is made
   explicit — an atomic (table / single message) segment is emitted as its own chunk even if it
   exceeds `max_tokens`; the budget is best-effort, atomicity is hard. `chunk_segments` emits a
   `logger.warning(...)` (file path + size) for an oversize atomic segment. The `base` test
   asserts "no chunk exceeds max_tokens **unless** it is a single atomic segment."
8. **architect-HIGH-1 (boundary preservation must be testable)**: the chunker operates on a
   typed `Segment(text, splittable: bool)` end-to-end — table & Slack-message segments are
   `splittable=False` and provably never divided; only `splittable=True` prose is soft-split
   (paragraph → sentence). Tests assert the exact atomic segment text appears whole in one chunk.
9. **architect-MEDIUM-1 (`source_type` literal vs `SourceType` enum)**: each connector sources
   its literal from `SourceType.<x>.value`; a registry test asserts
   `{c.source_type for c in all_connectors()} == {e.value for e in SourceType}`.

**Resolution — MEDIUM/LOW (folded in, non-blocking):**
- **M2 (multiple `Date:` headers in a thread)**: confirmed `customer-acai-express-thread.md`
  has 5 `Date:` lines; `EmailConnector` takes the **first** (outermost/most-recent) `Date:`
  as `as_of`. Tested.
- **M3 (`test/unit/loaders/__init__.py`)**: omitted deliberately — existing `test/unit/seed`
  and `test/unit/contracts` have no `__init__.py` and collect fine (unique test basenames).
- **M4 (`warn_unused_ignores` vs bs4 stubs)**: resolved empirically — run mypy on the bs4
  import first; add `# type: ignore[import-untyped]` **only** if mypy reports it, so no
  unused-ignore is ever emitted. `types-beautifulsoup4` is NOT added to dev deps.
- **M5 (disjointness guard)**: `discover_all` raises `LoaderError` on the **first** duplicate
  path, message naming the path + both `source_type`s; tested.
- **L1 (smoke file name)**: smoke lives in `test/unit/loaders/test_smoke.py`.
- **L2 (`raw_text` vs hashed bytes)**: `Document.raw_text` holds the **normalized** text — the
  exact bytes fed to `compute_content_hash` — so a re-hash of `raw_text` reproduces `content_hash`.
- **L3 (`to_chunks([])`)**: returns `[]`; boundary-tested.
- **architect-LOW-1 (PROGRESS pointer uncommitted)**: flagged in the delivery report so the
  orchestrator does not read its absence from the diff as a missed step.
- **architect-LOW-2 (lazy-anthropic safety)**: `anthropic` is imported inside the default
  caption fn only; a unit test asserts the loaders package imports with no network and
  constructing `ImageConnector()` performs no API call until `load()`.

### Post-Implementation Review

- **Iteration 1** (2026-06-09): code-reviewer (independent sub-agent, **plan-blind**) found 1 CRITICAL, 2 HIGH, 2 MEDIUM, 3 LOW. Files reviewed: helixpay/ingest/loaders/{base,markdown,pdf,html,slack,email,code,image,__init__}.py and test/unit/loaders/*.
- **Iteration 2** (2026-06-09): security-auditor (independent sub-agent, **plan-blind**) found 0 CRITICAL, 1 HIGH, 0 MEDIUM, 2 LOW. Files reviewed: helixpay/ingest/loaders/{base,image,html,pdf,slack,email,markdown,code,__init__}.py. Verified clean: no secret/API-key reaches a log/exception/Chunk; date + email regexes linear; file handles closed; malformed input raises clean LoaderError.

**Resolution — all CRITICAL and HIGH addressed (verified by new regression tests + full suite green):**

1. **C1 (data loss: `segment_markdown` dropped a heading when two headings had no body between them)**: confirmed every interview file (`# Interview: <name>` then `## Meta`) lost the interviewee name from chunk text. Fixed: consecutive heading / bold-label lines now **accumulate** into `pending_label` and attach to the following block, so both survive. Regression test `test_segment_markdown_consecutive_headings_are_not_dropped` + a real-file check (`Interview: Maria Silva` now appears in chunks).
2. **H2 → escalated to HIGH ReDoS (iteration 2): slack `_MSG_HEADER_RE` backtracked quadratically on a hostile unclosed bold line** (~1.2 s on a 42 KB line). Fixed with an O(1) pre-check (`_is_msg_header`: bounded length + `**`-delimited) before the regex and `[^*\n]` classes. Regression test `test_slack_header_detection_is_not_redos_prone` (< 1 s on the adversarial input). This also fixes the original H2 (a bold inline phrase containing a dash no longer false-matches a message boundary — a clock time is required).
3. **H3 (ImageConnector.discover only globbed `.jpeg`, silently skipping `.jpg`/`.png` that `_MEDIA_TYPES` supports)**: discovery now iterates every supported extension.

**Resolution — MEDIUM/LOW:**
- **M4 (registry test couldn't detect a duplicate connector — set collapses it)**: added `len(all_connectors()) == len(SourceType)`.
- **M5 (40-char labelled-date window could truncate a verbose `As of …` date)**: widened to 60.
- **L6 (`normalize_text` strips leading blank lines too — undocumented)**: documented the intent (idempotent hashing).
- **L (SDK/pdf exception text in log/LoaderError)**: confirmed no secret is present in those messages (the key is read from env by the SDK and never referenced here); left as-is with the `type(exc)`-truncation note for a future hardening pass.
- **L8 (missing test for the consecutive-heading case)**: added (see C1).
