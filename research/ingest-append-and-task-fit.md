# HelixPay Ingest — Append Model, Task Fit & `already_ingested` Optimization

**Scope:** How HelixPay's ingestion behaves as an **append / non-destructive**
operation, how that maps to the `opencodos/test-task` requirements, and the one
optimization that makes re-ingest cheap (`already_ingested`) — including the contract
gap that currently blocks it.

**Companion to:** `extraction-design-and-best-practices.md` and
`query-design-and-best-practices.md`. Research only — planning/implementation is left
to other agents. All `file:line` refs are the main tree unless noted.

---

## TL;DR

- Ingest is **append-only and non-destructive end to end**. There is **no `DELETE`**
  anywhere in `repository.py`, `pipeline.py`, `contradict.py`, `resolve.py`, `embed.py`.
- The test task **never names "append-only / idempotent" as a requirement.** Append is
  *our* choice — but it's the substrate that makes the task's *explicit* asks
  achievable: surfacing planted contradictions, source attribution, and "future live
  ingestion without major rewrites."
- The smart bit is the **supersede-within-source / contradict-across-source** split: a
  newer value from the *same* file supersedes (keeps history); disagreement *across*
  files stays live and becomes a contradiction row.
- **Data-layer is idempotent; the compute layer is not, by default.** A second run on
  unchanged data writes zero rows but still re-embeds (Voyage) and re-extracts
  (Anthropic, ×`glean_passes`) every chunk — unless the caller wires `already_ingested`.
- **Wiring `already_ingested` to the DB needs a small contract addition** — the frozen
  `Repository` has no hash-existence read. That's the one thing to fix to unlock the
  optimization.

---

## Part 1 — The Append Model

### 1.1 Every write path, and what it does on conflict

| Table | Natural key | On conflict | Destructive? |
|---|---|---|---|
| `documents` | `content_hash` (sha256 of **normalized** text) `UNIQUE` | `DO NOTHING` | No |
| `chunks` | `(document_id, ordinal)` | `DO NOTHING` | No — embedding never rewritten |
| `claims` | `(subject, predicate, object_value, source_chunk)` UNIQUE INDEX | `DO NOTHING` | No — `add_claim` never mutates |
| `claims` (supersede) | — | `UPDATE SET superseded_by, valid_to` | **No — old row kept** |
| `links` | `(from, to, type, COALESCE(as_of,'0001-01-01'))` UNIQUE INDEX | `DO NOTHING` | No |
| `contradictions` | `(claim_a, claim_b)` normalized to `(min,max)` | `DO NOTHING` | No |
| `entities` | `(canonical_name, entity_type)` | `DO UPDATE`: `attributes \|\|= `, `seeded OR=` | Additive merge only |
| `entity_aliases` | `(entity_id, alias)` | `DO NOTHING` | No |
| `metric_vocab` | `canonical_key` | `DO UPDATE` overwrites display/aliases | Seed-owned controlled vocab (intentional) |

The only non-additive write is `metric_vocab`'s display-name/alias overwrite, and that
table is a version-controlled controlled vocabulary owned by the seed — not
user/document-contributed facts. No claim, chunk, document, link, or contradiction is
ever overwritten or deleted.

### 1.2 What makes the idempotency robust (not just "ON CONFLICT everywhere")

- **`content_hash` is sha256 of *normalized* text** (`ingest/loaders/base.py:62`):
  line-endings → `\n`, per-line trailing whitespace stripped, leading/trailing blank
  lines stripped. Trivial reformatting does **not** masquerade as new data.
- **`tsv` is a Postgres generated column** (`db/schema.sql:37`,
  `GENERATED ALWAYS AS (to_tsvector('english', text)) STORED`) and embeddings are passed
  in by the pipeline — Python never writes the lexical vector, so re-ingest can't
  desync lexical vs text.
- **Within-run de-dup** (`pipeline.py:106`): a `seen_hashes` set skips the same content
  encountered twice in one run before any DB call.

### 1.3 The temporal append: supersede vs contradict

This is the design's load-bearing decision. After every `add_claim`, `_maybe_supersede`
(`pipeline.py:212`) fires **only** when all five hold:

1. new claim has a concrete `as_of`;
2. existing claim is not already superseded;
3. existing `as_of` is **strictly earlier**;
4. the values genuinely differ (`values_conflict`);
5. **same `source_uri`** (intra-source only).

```
same source, newer value   → supersede_claim(old, new, valid_to=new.as_of)
                             → old row KEPT (valid_to + superseded_by set), new is current
different sources disagree  → both stay live (superseded_by IS NULL)
                             → contradiction detection pairs them → contradiction row
```

`supersede_claim` (`repository.py:264`) is an `UPDATE`, never a `DELETE`; superseded
claims remain queryable (`get_claims` has no `superseded_by IS NULL` filter; only
contradiction detection filters to live claims). **A naive "latest-wins" upsert would
pass the temporal case but fail the contradiction case** — which is exactly what the
dataset tests.

---

## Part 2 — Fit Against `opencodos/test-task`

### 2.1 What the task actually requires (verbatim asks)

The README lists, under **Key Requirements**: agent-friendly interface; cross-source
queries **with source attribution**; **architecture supporting future changes without
major rewrites**; production-ready (non-local) deployment. Under **Evaluation**:
architecture thoughtfulness, runnable setup, strategic LLM usage, documented tradeoffs.
`overview.md` instructs: *"when other documents disagree with this, trust the
documents"* — and the dataset is **engineered with planted conflicts** (June-vs-Sept
Confluence GA; 62/47/31 NPS; Q4 15.4M vs Q1 14.2M revenue; public-vs-internal launch
status).

**"Idempotent / append-only / re-runnable" appears nowhere in the README.** It is an
implicit architecture-quality signal, not a named requirement.

### 2.2 Why append-only is nonetheless the right substrate

| Task's explicit ask | Why it *requires* a non-destructive model |
|---|---|
| "Surface contradictions, trust the documents" | You cannot show "Source A says X, Source B says Y" if ingest overwrote A with B. Conflicting claims must **coexist**. |
| "Source attribution" | Every claim keeps `source_chunk_id` + `document_id` + `as_of`; an overwrite would erase provenance. |
| "Future live ingestion without major rewrites" | Re-running on a grown `data/` is a no-op on unchanged files and a clean append+supersede on changed ones — no backfill, dedup script, or migration. |
| Temporal snapshots (Q4-2025 vs Apr-2026 dashboards, same metric, different value) | Append + supersession preserves the time series; a destructive upsert collapses it. |

**The framing for SOLUTION.md:** append-only isn't a checkbox the task lists — it's the
property that makes the task's contradiction + attribution + future-ingestion
requirements achievable at all. Lead with that, not with "we were told to be idempotent."

---

## Part 3 — Ingestion Optimization: `already_ingested`

### 3.1 The gap: data-idempotent ≠ compute-idempotent

Trace of a **second run on identical data** (`pipeline.py:104`):

1. Loaders re-load each file → identical `content_hash`.
2. `seen_hashes` only de-dups *within* a run, so it doesn't help across runs.
3. **If `already_ingested` is not wired**, `upsert_document` is called (`DO NOTHING`,
   returns existing id) and `_ingest_document` runs in full:
   - `embedder.embed([...])` → **Voyage API call for every chunk** (`pipeline.py:149`);
   - `extractor.extract(...)` → **Anthropic call for every chunk, ×`glean_passes`**
     (production default `ChunkExtractor(AnthropicClient(), glean_passes=1)` =
     two passes/chunk) (`pipeline.py:97, 157`).
4. All resulting `add_chunks`/`add_claim` calls hit `DO NOTHING` → **zero DB writes**.

**Net: a re-run mutates nothing but pays full Voyage + Anthropic cost.** On a corpus
this is the dominant re-ingest expense, and it scales with `glean_passes`.

### 3.2 The fix: the `already_ingested` seam

The pipeline already exposes the hook (`pipeline.py:75`, `:110`):

```python
already_ingested: Optional[Callable[[str], bool]] = None
...
if already_ingested is not None and already_ingested(doc.content_hash):
    report.skipped_documents += 1
    continue   # ← before upsert, before embed, before extract
```

When it returns `True`, the document is skipped **before any embed or LLM call** — the
expensive work is never started, and `skipped_documents` records it. This is the
intended optimization path; it's simply **not wired by default**.

### 3.3 The blocker: no hash-existence read on the frozen contract

To back `already_ingested` with the DB, you need to ask "have I seen this
`content_hash`?" — and the frozen `Repository` Protocol has **no such read**
(`contracts/repository.py`): `upsert_document` returns the same `int` whether the row
was new or pre-existing, so it **cannot tell you new-vs-existing after the fact**, and
CLAUDE.md forbids raw SQL outside `helixpay/db/`. So the pipeline can't cheaply check
existence today without a contract addition.

**Minimal contract change (propose, don't fork) — batch read is preferred:**

```python
# helixpay/contracts/repository.py  (proposed addition)
def known_content_hashes(self) -> set[str]:
    """All content_hashes already persisted — to skip unchanged docs on re-ingest."""
```

Then wiring is one call + a set membership (one query for the whole run, no N
round-trips):

```python
known = repo.known_content_hashes()
report = pipeline.run("data", repo, already_ingested=known.__contains__)
```

A single-hash `document_exists(content_hash: str) -> bool` is the smaller change but
costs one query per document; `known_content_hashes()` is one query per run and is the
better default for a batch ingest. (For very large corpora a future variant could take
the run's candidate hashes as an argument and return the subset already present.)

### 3.4 Optional second-order optimizations (lower priority)

- **Skip-aware reporting already exists** (`skipped_documents`) — surface it in the
  `make ingest` summary so re-runs visibly show "N skipped / M ingested."
- **Per-chunk hashing** would let a *partially* changed document re-embed only the
  changed chunks rather than re-chunking the whole file. Not needed at this corpus size;
  note it as future work, don't build it.
- **`glean_passes` is the cost multiplier on re-extraction** — wiring `already_ingested`
  matters *more* the higher `glean_passes` is set, since each skipped doc saves
  `chunks × (1 + glean_passes)` LLM calls.

---

## Part 4 — Honest Caveats (for SOLUTION.md)

1. **Compute idempotency depends on wiring `already_ingested`.** Out of the box, the
   data layer is idempotent but re-runs still spend on embeddings + extraction. This is
   the §3 optimization; it needs the §3.3 contract read.
2. **The claims natural key excludes `as_of`** (`schema.sql:106`): the key is
   `(subject, predicate, object_value, source_chunk)`. Two claims with the same tuple
   but different dates would collide on the key. In practice one chunk yields one value
   per predicate, so it never bites — but it's a latent assumption worth naming, not
   discovering.
3. **Supersession is intra-source and date-strict.** If a file's value changes but its
   `as_of` does **not** advance (equal dates), supersession does *not* fire
   (`pipeline.py:229`, `existing.as_of >= new.as_of`) — the two coexist and
   contradiction detection classifies them instead. Correct behavior, but worth knowing.

---

## Part 5 — Recommendations (research only; for the planning agent)

| # | Priority | Recommendation | Why | Touches |
|---|---|---|---|---|
| 1 | **HIGH** | Add `Repository.known_content_hashes() -> set[str]` (contract proposal) and wire `already_ingested=known.__contains__` as the default in the `make ingest` entrypoint. | Turns a re-run from "full Voyage+Anthropic spend, zero writes" into a near-free no-op. Biggest re-ingest cost win; compounds with `glean_passes`. | `contracts/repository.py`, `db/repository.py`, ingest entrypoint |
| 2 | **MEDIUM** | Surface `skipped_documents` in the ingest summary/CLI output. | Makes the idempotency observable; reassures the operator a re-run did the right thing. | ingest entrypoint, `pipeline.py` |
| 3 | **LOW** | Document the `as_of`-excluded claims natural key and the equal-date supersession behavior as known edge cases. | Pre-empts a future "why didn't this supersede?" investigation. | `SOLUTION.md` |
| — | **DON'T** | Don't add per-chunk hashing or content-diffing now. | Unneeded at this corpus size; note as future work. | — |
| — | **DON'T** | Don't make `add_claim` overwrite on conflict to "update" values. | Breaks append/history and the contradiction guarantee — the project's whole point. | — |

**If only one thing ships: #1.** It's the single change that makes re-ingestion
genuinely cheap, and it's the concrete realization of "future live ingestion without
major rewrites" — directly answering the rubric.

---

*Generated 2026-06-10. Code basis: `helixpay/ingest/`, `helixpay/db/`,
`helixpay/contracts/` @ main; supersession/idempotency confirmed by code read.*
