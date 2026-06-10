# Agent 1 — Loaders / ingestion normalization (SP_002, Standard)

You are Agent 1. You turn each raw file in `data/` into a `Document` + ordered
`Chunk`s via one `SourceConnector` per format. You do **not** extract claims, embed,
or touch the DB — you normalize bytes into the `Chunk` contract. Read `CLAUDE.md`,
`AGENTS.md`, and `HELIXPAY_BUILD_SPEC.md` §5 (Agent 1) before starting, then read
`fanout/README.md` for the isolation protocol and shared-file rules.

## Setup
- Worktree: `git worktree add .claude/worktrees/SP_002 -b sprint/SP_002-loaders main`
- Sprint plan: `workspace/sprints/SP_002_loaders.md` — `tier: Standard`,
  `isolation: git-worktree`, `touches_paths: [helixpay/ingest/loaders/**, test/unit/loaders/**]`.
- Run the Standard lifecycle (pre-impl gate + ≥2 review iterations + TDD + post-impl review).

## Owns (write only here)
- `helixpay/ingest/loaders/**` — one module per connector + a registry.
- `test/unit/loaders/**`.

## Codes against (frozen — import, never redefine)
```python
from helixpay.contracts import Document, Chunk, SourceConnector, SourceType
# SourceConnector(Protocol): source_type: str
#   discover(self, root: str) -> list[str]          # the paths THIS connector owns
#   load(self, path: str) -> tuple[Document, list[Chunk]]
# Document(source_uri, source_type, title?, author?, lang?, as_of?, content_hash, raw_text?)
# Chunk(document_id?, ordinal, text)     # NO embedding/tsv here — that's downstream
```
`content_hash` must be a stable hash of normalized content (e.g. sha256 of `raw_text`)
so re-ingest is idempotent. Set `as_of` from the document's own date when present.

## Build — one connector per `source_type`, disjoint discovery

The dataset mixes formats AND uses `.md` for several logical types, so **`discover()`
must claim by directory/content, not just extension** (no file claimed twice):

| source_type | Owns (discover) | Notes |
|-------------|-----------------|-------|
| `md` | `data/*.md` (overview, org-chart, all-hands, board-update, weekly-review) + `data/interviews/**/*.md` | general markdown; preserve section headings |
| `pdf` | `data/*.pdf` (board-deck-q1-2026, q1-2026-results) | extract text **and tables**; tables carry the figures |
| `html` | `data/dashboards/*.html` | **capture each number AND its as-of date** — that's where contradictions hide |
| `image` | `data/images/*.jpeg` | vision caption pass (caption-level only; deep figure OCR is an explicit scope cut) |
| `slack` | `data/chat/*.md` | preserve speaker + timestamp boundaries |
| `email` | `data/email/*.md` | preserve thread/subject/participants |
| `code` | `data/code/*.md` | contributor-analysis doc; keep file/author references intact |

Chunking: ~500–800 tokens, **preserve speaker/section boundaries** (don't split mid-turn
or mid-table). Set `ordinal` per chunk; `document_id` stays `None` (assigned at persist
time by the pipeline). Provide a registry so the pipeline can discover all connectors:
```python
# helixpay/ingest/loaders/__init__.py
def all_connectors() -> list[SourceConnector]: ...   # every impl, disjoint discovery
def discover_all(root: str) -> list[tuple[SourceConnector, str]]: ...
```

## Dependencies (declare in sprint plan; do NOT edit pyproject)
Likely: `pypdf` or `pdfplumber` (pdf), `beautifulsoup4`/`lxml` (html), `markdown-it-py`
optional. Image captioning uses the Anthropic vision API (`claude-sonnet-4-6`) — keep
the vision call behind a small injectable function so unit tests can stub it (no real
API in unit tests).

## Conventions
- Cross-module types only from `helixpay.contracts`. No DB access (that's the pipeline).
- Secrets from env. No network in unit tests — stub the vision call.
- Structured severity/logging per `GL-ERROR-LOGGING`; never swallow a parse failure
  silently (log which file/format failed).

## Done when
- Each connector parses the **real** files in its column and returns contract-valid
  `Document` + `Chunk`s (assert against `data/` in a `smoke`-marked test; unit tests use
  small inline fixtures).
- `discover_all('data')` claims all 44 files exactly once, no overlaps, no misses.
- HTML dashboard chunks carry both the metric value and its as-of date.
- Tests green; mypy clean over `helixpay/ingest/loaders`.

## Hand-off
Your `Chunk`/`Document` output is consumed by Agent 2's pipeline (`helixpay/ingest/pipeline.py`).
In your delivery report: the connector→path map, any file that resisted clean parsing,
and any new gotchas (for the orchestrator to fold into `CLAUDE.md`).
