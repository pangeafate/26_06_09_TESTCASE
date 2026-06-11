# HelixPay Query — Design & Best-Practices Report

**Scope:** How HelixPay answers questions (the SP_004 query/retrieval layer), measured
against the 2024–2026 state of the art in hybrid retrieval, GraphRAG, grounded
generation, citation enforcement, and contradiction/temporal-aware QA.

**Companion to:** `extraction-design-and-best-practices.md` (the ingest side). Same
method: deep-read our actual code, deep-read the field, compare, recommend.

**Status:** SP_004 lives in the worktree `.claude/worktrees/SP_004/helixpay/query/`;
not yet merged to the main tree. All `file:line` references below are in that worktree.

---

## TL;DR

HelixPay's query layer is **well-built and, on two axes — first-class contradictions
and a no-uncited-claims generation guard — ahead of essentially every open-source RAG
framework.** The retrieval spine (RRF hybrid over pgvector + Postgres FTS), the
recursive-CTE org graph, the freshest-wins temporal resolver, and the forced
structured-output `ask()` are all canonical, correct choices.

The gaps are not correctness gaps; they are **recall and precision headroom**:

1. **No reranker** between RRF fusion and the LLM — the single highest-ROI add (HIGH).
   Recommended default vendor is **Voyage `rerank-2.5`** (same key/SDK as embeddings),
   not Cohere — see §2.4 for the reasoning.
2. **Chunk-only-grounded sentences are always dropped** → answers can collapse to the
   fallback string even when a retrieved excerpt genuinely supports them (HIGH — a
   correctness/UX gap forced by a frozen-contract hole).
3. **`freshest-wins` is weaker than query-time temporal scoring** for explicit
   date-range questions (MEDIUM).
4. **Contradictions are surfaced but not typed** — labeling conflict type before
   `ask()` measurably improves how the LLM articulates them (MEDIUM).
5. **No retrieval/answer evaluation harness** (Recall@k, RAGAS faithfulness) (MEDIUM).

None of these block the demo. #1 and #2 are the two worth doing.

---

## Part 1 — How HelixPay Query Actually Works

The module is ten files under `helixpay/query/`. The engine wires submodules; each
submodule is pure and independently tested.

| File | Responsibility | LoC |
|---|---|---|
| `engine.py` | `HelixQueryEngine` — the `QueryEngine` impl; `ask/get_entity/get_org_chart/find_contradictions` | 182 |
| `planner.py` | Lexical route classifier → `Plan(route, wants_*)`; no LLM, no DB | 99 |
| `retrieval.py` | `reciprocal_rank_fusion()` + `hybrid_search()`; `RRF_K=60` | 67 |
| `graph.py` | `org_chart()` + `entity_detail()`; role enrichment | 65 |
| `temporal.py` | `order_by_freshness` / `freshest_per_predicate` / `as_of_coverage`; `ROSTER_AS_OF=2026-04-15` | 81 |
| `contradictions.py` | `find()` + `relevant()`; subject + canonical-predicate collection | 77 |
| `synthesis.py` | `build_grounding` / `render_prompt` / `enforce_citations`; `SYNTH_SCHEMA` | 166 |
| `clients.py` | `Embedder`/`Synthesizer` Protocols + Voyage/Anthropic impls (lazy) | 102 |
| `prompts/ask_synthesis.md` | Named synthesis prompt, `{question}`/`{grounding}` slots | 35 |
| `__init__.py` | PEP-562 lazy export — importing the package pulls in no SDK | 27 |

### 1.1 Hybrid retrieval (RRF)

`hybrid_search()` (`retrieval.py:51`) embeds the query **once** via
`embedder.embed_query`, then calls `repo.search_semantic(qvec, k)` (pgvector cosine)
and `repo.search_lexical(query, k)` (Postgres `ts_rank`). Raw scores are discarded —
only rank order feeds fusion:

```python
RRF_K = 60
def reciprocal_rank_fusion(rankings, k=RRF_K):
    scores = {}
    for ranking in rankings:
        for rank, chunk in enumerate(ranking, start=1):
            cid = chunk.id if chunk.id is not None else id(chunk)
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    ordered = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return [(chunks[cid], score) for cid, score in ordered]
```

Equal weights, `k=60`, deterministic ascending-id tie-break. A chunk in both lists
accrues two terms and outranks single-list chunks. Result sliced to `[:k]` (default 8).

### 1.2 Graph queries

`org_chart()` (`graph.py:38`) calls `repo.get_org_subtree(root_id=None, as_of=…)` (the
recursive CTE lives in `helixpay.db`, honoring no-raw-SQL-outside-db). `_enrich_roles()`
walks the returned tree and back-fills each node's `role` via
`repo.resolve_entity(name, entity_type="person")`. The solid-line hierarchy
(`children`) and functional dotted-lines (`dotted_reports`) are **separate fields** on
`OrgNode`, mirroring the `reports_to` vs `dotted_line_to` link-type split — the query
layer trusts the tree shape rather than re-deriving it. `entity_detail()` resolves the
name, pulls `get_claims`, and filters `get_links` in Python.

### 1.3 Temporal resolution

`order_by_freshness()` (`temporal.py:28`) sorts by `(as_of or date.min, -id)` reversed —
undated claims sort last and never crash on `None < date`.
`freshest_per_predicate()` does `setdefault` over that order = freshest-wins per
predicate. `as_of_coverage()` returns `{earliest, latest, sources{uri:iso}, stale}`
where `stale = latest < 2026-04-15` (the roster date). Computed over **citations**
(post-`enforce_citations`), not raw claims.

### 1.4 Contradiction surfacing

`_collect()` (`contradictions.py:33`) unions two paths:
- **By subject** — `get_contradictions(subject_id=sid)` for each resolved entity.
- **By topic** — canonicalize every topic via `canonical_predicate`, pull all
  contradictions, keep those whose predicate is in the canonical set. *This is the path
  that catches a metric conflict when no entity resolves* (e.g. "What was Q1 revenue?"
  where "Revenue" isn't an entity).

Both sides are attributed: `_gather_claim_facts()` (`engine.py:160`) fetches each
contradiction's `claim_a`/`claim_b` subject claims so synthesis can cite both with
`[C#]` markers. **Present-and-empty guarantee:** `bundle.contradictions = relevant`
(`engine.py:96`) is unconditional, and the field defaults to `[]` on the model — never
absent, never `None`.

### 1.5 Query planner

Pure lexical classification (`planner.py:72`), no LLM, no DB. Builds boolean flags by
substring match (`_HIERARCHY`, `_OWNERSHIP`, `_CONTRADICTION`, `_METRIC`, `_FRESHNESS`)
plus a proper-noun scan, then:

1. hierarchy-only, no freshness/contradiction/ownership → `structured`
2. any of hierarchy / ownership / contradictions / proper-noun → `both`
3. else → `retrieval`

**Metric questions always probe contradictions:**
`wants_contradictions = _any(_CONTRADICTION) or _any(_METRIC)` (`planner.py:76`), and
`_METRIC` includes `revenue, arr, ebitda, burn, runway, churn, headcount, margin, kpi,
"how much", "what was", growth`. Any metric term forces `Route.both`. A hierarchy
question with a freshness cue ("as of", "latest", "currently") also escalates to
`both` so the staleness path runs.

### 1.6 Grounded `ask()`

Named prompt `prompts/ask_synthesis.md`, rendered with a **single-pass** regex
substitution so injected content from one slot can't be re-expanded by the other
(`synthesis.py:97`). Grounding indexes claims as `[C1…]` `(claim)` and chunks as
`[S1…]` `(source excerpt)`.

Generation is **forced structured output** (`clients.py:78`): `claude-opus-4-8`,
`tools=[emit_answer]`, `tool_choice={type:tool}` — no free-form prose path.
`SYNTH_SCHEMA` = `{sentences:[{text, cites:[…]}], confidence}`.

**No-uncited-claims guard** — `enforce_citations()` (`synthesis.py:108`):
1. Type-defensive parse (every level `isinstance`-checked).
2. Keep only `cites` that are `[C#]` markers present in `facts` **and** of kind
   `claim` — chunk markers `[S#]` are rejected.
3. A sentence survives only if it has non-empty text **and** ≥1 surviving claim cite.
4. If nothing survives → `FALLBACK_ANSWER` ("I could not find sufficient cited
   evidence to answer that.").
5. Resolve survivors to `Citation` objects via `repo.get_sources`.

Answer = `" ".join(kept)` — only claim-backed sentences.

### 1.7 Injectable seams

`Embedder`/`Synthesizer` are `@runtime_checkable` Protocols (`clients.py:26`). Concrete
Voyage/Anthropic impls import their SDK lazily on first call (`importlib.import_module`,
keys from env only). `build_default_engine` imports them inside the function body, and
`__init__.py` uses PEP-562 `__getattr__` — so importing `helixpay.query` pulls in no
SDK and tests run with zero keys.

### 1.8 Tests

7 unit files (no DB, no keys) covering RRF math + tie-break, all 7 planner shapes,
None-safe freshness + staleness boundary, dual-path contradiction collection,
citation keep/drop + 6 adversarial malformed-output shapes, graph enrichment. Plus
`test/integration/query/` (marked `db`, auto-skip without `DATABASE_URL`): real
migrate+seed+pgvector, LLM/embeddings stubbed. The acceptance test asserts the planted
14.2M-vs-13.9M revenue conflict surfaces with both sides + two as_of-stamped citations,
`as_of_coverage.latest == "2026-03-31"`, and org root = Wei Chen. **87 pass with a live
container; 66 pass / 16 skip without one. `mypy` clean.**

### 1.9 Honest friction the code documents about itself

- `EntityDetail.aliases` is always `[]` — frozen `Repository` has no `get_aliases`
  (`graph.py:46`).
- `entity_detail` filters all links in Python — no `from_entity_id` filter on
  `get_links`.
- **Chunk-only sentences are always dropped** (`synthesis.py:16`) — no
  `get_chunk_sources` read exists, so a sentence grounded only in an `[S#]` excerpt
  can't become a spec `Citation`, and is dropped rather than emitted uncited. **A
  genuinely source-grounded answer with no claim cite returns `FALLBACK_ANSWER`.**
- `_resolve_subjects` calls `resolve_entity` one term at a time (no batch read).
- `find("ARR")` won't surface the planted **revenue** conflict — `arr` and `revenue`
  are distinct canonical keys. Correct behavior (honest vocab), but worth knowing.

---

## Part 2 — The Field (2024–2026)

### 2.1 Hybrid retrieval & fusion
- **RRF** (Cormack et al., SIGIR 2009) fuses on *rank*, sidestepping the cosine-vs-BM25
  scale mismatch; `k≈60` is the robust default. HelixPay matches the canonical recipe.
- **pgvector + FTS + RRF** is now a documented best-practice stack (Jonathan Katz's
  two-CTE pattern, `k=50`): hybrid+RRF lifts precision from ~62% (vector-only) to ~84%.
- Every major engine ships RRF (Elastic, OpenSearch, Weaviate, Qdrant, Vespa). Weaviate
  2.0 even learns the dense/sparse weight; Qdrant offers DBSF as an alternative.
- **Best practice we don't yet follow:** pull a *larger* pre-fusion candidate set
  (top 20–50 each) when a reranker sits downstream.

### 2.2 GraphRAG query patterns
- **Microsoft GraphRAG** — local (entity-seeded) vs global (map-reduce over community
  summaries) vs **DRIFT** (primer + follow-up). Route to global for
  theme/summary/trend questions, local for named-entity questions.
- **LightRAG** — dual-level (low: entity/attribute; high: thematic) retrieval.
- **HippoRAG** — Personalized PageRank seeded from query concepts; single-shot
  multi-hop at ~10–20× lower cost than iterative.
- **Graphiti/Zep** — bi-temporal edges `(valid_start, valid_end, ingested, superseded)`;
  three parallel signals (semantic + keyword + graph).
- **postgres-graph-rag / SQL:2023 PGQ** — recursive CTEs are the right tool for
  fixed-schema hierarchies (exactly our org chart); reserve a graph DB for schemaless
  graphs. **HelixPay's CTE choice is validated.**

### 2.3 Query routing
- **RAGRouter-Bench (2026):** a **TF-IDF + SVM** router hits 93% accuracy and lexical
  features *beat* embeddings for query-type routing by 3.1 macro-F1 — query type is a
  surface-form signal. **This directly validates HelixPay's keyword planner** over an
  LLM router for this job.
- **Adaptive-RAG / Self-RAG / CRAG** add complexity tiers, in-model retrieve tokens,
  and a retrieval-quality corrective loop respectively.

### 2.4 Reranking — the layer HelixPay is missing
- Standard production shape is **two-stage**: recall (hybrid+RRF, top 50–200) →
  precision (cross-encoder rerank, top 5–20). HelixPay stops at stage 1.
- Options: **Voyage rerank-2.5 / rerank-2.5-lite** (API), **Cohere Rerank 3.5** (API,
  +up-to-25% on hard tasks), **bge-reranker-v2-m3** (self-host, ~80–200 ms/100 docs),
  **ColBERTv2** late interaction (cache-efficient, native in Qdrant). Never run a
  cross-encoder over the whole index — only the fused shortlist.
- **Vendor fit for HelixPay → Voyage, not Cohere.** Confirmed against the Voyage docs
  and SDK source: `rerank-2.5` / `rerank-2.5-lite` reuse the **same `voyageai.Client`,
  the same `VOYAGE_API_KEY`, and the same dep** the project already uses for
  embeddings — `vo.rerank(query, documents, model="rerank-2.5", top_k=8)` returns
  `.results[].{index, relevance_score}`. Cohere would add a **4th vendor and a 4th
  secret** (`COHERE_API_KEY`), touching the env allowlist, `helixpay.config`, deploy
  secrets, and CI — for no quality gain: on Voyage's own NDCG@10 benchmarks (93
  datasets) `rerank-2.5` is **+7.94%** over Cohere Rerank v3.5 (+12.7% on MAIR
  instruction-following), with a **32K** combined query+doc context (8× Cohere's) and
  up to 1,000 docs/call. Pricing $0.05/M tokens (`-lite` $0.02/M), first 200M tokens
  free. *(Caveat: those are Voyage's own published numbers; no independent BEIR/MTEB
  reproduction at that scale was found — but vendor fit alone already decides it.)*

### 2.5 Grounded generation & citation — where HelixPay is strong
- **ALCE** (EMNLP 2023) is the citation benchmark; joint inline citation beats post-hoc.
- **ReClaim / "Ground Every Sentence"** — interleaved per-sentence cite → 90% citation
  accuracy. Our per-sentence `{text, cites}` schema is the same shape.
- **FRONT / LongCite** — *quote-grounded* (verbatim span) citations are
  string-match-verifiable, stronger than doc-level IDs.
- **Anthropic Citations API** — guaranteed-valid span pointers, near-zero source
  hallucination. **Key constraint: mutually exclusive with Structured Outputs.** Since
  HelixPay needs the typed `AnswerBundle`, we correctly chose structured output; the
  field's recommended workaround is to parse citation blocks into the schema app-side.
- **"Correctness ≠ Faithfulness" (2412.18004):** up to 57% of RAG citations are
  *post-rationalized* (answer from parametric memory, citation bolted on). NLI catches
  unsupported claims; only model-internals methods (MIRAGE/FACTUM) catch
  post-rationalization. HelixPay's guard is a *structural* check (cite must exist and
  resolve), which is stronger than prompt-only but doesn't yet verify entailment.

### 2.6 Contradiction & temporal QA — HelixPay's strongest axis
- **No published framework ships a typed `AnswerBundle.contradictions` required field.**
  Closest: ConflictRAG (annotations in prose), PaperTrail (UI claim-evidence map),
  Paper-QA `contracrow` (claim-as-query mode). **HelixPay's present-and-empty
  first-class contradictions list is ahead of the field.**
- **DRAGged into Conflicts (2506.08500):** a 5-way conflict taxonomy (no-conflict /
  complementary / opinion / outdated / misinformation). Telling the LLM the *conflict
  type* before generation adds **+5–9 pp** (auto) to +24 pp (oracle) on correct
  handling. HelixPay surfaces conflicts but doesn't type them.
- **MRAG (EMNLP 2025):** decompose query into `(content, temporal_constraint)`, score
  `semantic × temporal` — multiplicative, so a relevant-but-wrong-period passage scores
  ~0. Stronger than `freshest-wins` for explicit date-range questions.
- **TG-RAG / Graphiti:** time is a structural dimension; facts are versioned edges with
  validity intervals — which is exactly HelixPay's `valid_to`/`superseded_by` data
  model, here surfaced as `as_of_coverage` + staleness.

### 2.7 Evaluation — the missing harness
- **Retrieval:** Recall@k is the metric that matters most (generation collapses when
  the right chunk isn't retrieved); target Recall@10 ≥ 0.8, then nDCG@10.
- **Generation:** **RAGAS** faithfulness (claims supported / total; HHEM backend skips
  the 2nd LLM call) for CI; **RAGChecker** to split retriever vs generator blame;
  **ARES** (domain-finetuned judges + PPI) for production.
- HelixPay has excellent *example-based* tests but no *metric-based* eval over a query
  set.

---

## Part 3 — Where HelixPay Already Matches or Beats the Field

| Capability | HelixPay | Verdict |
|---|---|---|
| Hybrid RRF (k=60, rank-only, det. tie-break) | ✅ canonical | **Matches best practice exactly** |
| Org graph via recursive CTE | ✅ | **Validated** (postgres-graph-rag, SQL/PGQ) |
| Keyword query router | ✅ lexical flags | **Validated** (RAGRouter-Bench: lexical > embeddings) |
| Per-sentence `{text, cites}` structured answer | ✅ forced tool-call | **Matches ReClaim/ALCE gold shape** |
| No-uncited-claims structural guard | ✅ drop-or-fallback | **Ahead of most OSS** (prompt-only is the norm) |
| Contradictions first-class, present-and-empty | ✅ | **Ahead of the entire field** |
| Bi-temporal data → as-of + staleness in answers | ✅ | **Ahead of most OSS** (peers: Graphiti/TG-RAG) |
| Lazy SDK seams / keyless tests | ✅ | Clean engineering |

---

## Part 4 — Recommendations (prioritized)

| # | Priority | Recommendation | Why | Touches |
|---|---|---|---|---|
| 1 | **HIGH** | **Add a rerank stage** after RRF: pull top ~30 each → fuse → rerank → top 8 to the LLM. Make it an injectable `Reranker` seam (mirror `Embedder`), no-op default so tests stay keyless. **Default impl = `VoyageReranker` (`rerank-2.5`)** — reuses the existing `voyageai.Client` + `VOYAGE_API_KEY`, no new vendor/secret (see §2.4). Keep a `CohereReranker` documented as a drop-in alternative, not the default. | Two-stage recall→precision is the single most established RAG win; measurable precision lift for ~100–200 ms. Voyage default keeps the project on its existing 3-secret vendor surface. | `retrieval.py`, `clients.py`, `engine.py` |
| 2 | **HIGH** | **Close the chunk-citation hole.** Propose a `Repository.get_chunk_sources(chunk_ids)` read so `[S#]`-grounded sentences can become real `Citation`s instead of being dropped to `FALLBACK_ANSWER`. (Contract change — propose, don't fork.) | Today a genuinely source-grounded answer with no claim cite returns the fallback string — a real UX/correctness gap forced by a frozen-contract hole. | `contracts/repository.py` (proposal), `synthesis.py`, `engine.py` |
| 3 | **MEDIUM** | **Type the contradictions** before `ask()`: classify each surfaced conflict as `temporal | value | opinion` and pass the type into the synthesis prompt (DRAGged-style). | +5–9 pp on how correctly the LLM articulates the conflict, at near-zero cost. | `contradictions.py`, `synthesis.py`, `prompts/ask_synthesis.md` |
| 4 | **MEDIUM** | **Query-time temporal scoring** for date-range questions: when the planner detects an explicit period, decompose to `(content, temporal_constraint)` and rank `semantic × temporal` instead of relying only on freshest-wins. | MRAG: +7.7–13.9% top-5 recall on temporally-constrained questions; freshest-wins can't answer "as of Q1". | `planner.py`, `temporal.py`, `retrieval.py` |
| 5 | **MEDIUM** | **Add an eval harness:** a small gold query set + Recall@k on retrieval and RAGAS faithfulness (HHEM backend) on `ask()`, run in CI alongside the example tests. | Moves quality from anecdote to metric; catches regressions the 7 example tests can't. | `test/eval/**` |
| 6 | **LOW** | **Verbatim-span citations:** have synthesis emit the exact supporting substring per claim (FRONT/LongCite), enabling string-match faithfulness verification. | Makes citation auditing cheap and model-independent. | `synthesis.py`, `SYNTH_SCHEMA` |
| 7 | **LOW** | Larger pre-fusion candidate set (top 20–50 per sub-query) once #1 lands; batch `resolve_entity`; add `get_links(from_entity_id=…)` filter. | Recall headroom for the reranker + two documented perf papercuts. | `retrieval.py`, `engine.py`, `contracts/` |
| — | **DON'T** | Don't swap the keyword planner for an LLM router. | RAGRouter-Bench shows lexical beats embeddings here — the planner is the *right* design, not tech debt. | — |
| — | **DON'T** | Don't auto-resolve contradictions to a single value. | First-class surfacing is the project's whole point and ahead of the field. | — |

**If only two things ship: #1 (reranker) and #2 (chunk-citation hole).** The first is
pure precision upside; the second removes a real failure mode where good answers
silently become the fallback string.

---

## Part 5 — Reference Notes

- **RRF:** Cormack et al., SIGIR 2009. pgvector recipe: jkatz05.com hybrid-search post.
- **GraphRAG:** arXiv:2404.16130 + microsoft/graphrag; DRIFT (MSR blog). **LightRAG:**
  arXiv:2410.05779. **HippoRAG:** arXiv:2405.14831. **Graphiti/Zep:** arXiv:2501.13956.
  **postgres-graph-rag:** h4gen/postgres-graph-rag; SQL/PGQ (EDB).
- **Routing:** RAGRouter-Bench arXiv:2604.03455; Adaptive-RAG; Self-RAG arXiv:2310.11511;
  CRAG arXiv:2401.15884.
- **Rerank:** Voyage rerank-2.5 / rerank-2.5-lite (docs.voyageai.com/docs/reranker;
  blog.voyageai.com 2025-08-11 — same `voyageai.Client` + `VOYAGE_API_KEY` as
  embeddings); Cohere Rerank 3.5; BAAI bge-reranker-v2-m3; ColBERTv2 (RAGatouille).
- **Citation:** ALCE arXiv:2305.14627; ReClaim arXiv:2407.01796; FRONT arXiv:2408.04568;
  LongCite arXiv:2409.02897; Anthropic Citations API; VeriCite arXiv:2510.11394.
- **Faithfulness:** "Correctness ≠ Faithfulness" arXiv:2412.18004; MIRAGE
  arXiv:2406.13663; RAGAS arXiv:2309.15217; RAGChecker arXiv:2408.08067; ARES
  arXiv:2311.09476; RefChecker arXiv:2405.14486; FActScore arXiv:2305.14251.
- **Conflict/temporal:** DRAGged arXiv:2506.08500; ConflictRAG arXiv:2605.17301;
  ArbGraph arXiv:2604.18362; TruthfulRAG arXiv:2511.10375; MRAG arXiv:2412.15540;
  TG-RAG arXiv:2510.13590.
- **Eval/benchmarks:** BEIR arXiv:2104.08663; TREC-RAG 2024 (arXiv:2411.09607);
  CRAG benchmark; TempRAGEval (MRAG).
- **Survey:** "Attribution, Citation, and Quotation" arXiv:2508.15396 +
  HITsz-TMG/awesome-llm-attributions.

---

*Generated 2026-06-10. Code basis: `.claude/worktrees/SP_004/helixpay/query/` @ SP_004.*
