# Extraction in HelixPay: Design Review + GitHub Best-Practice Report

> **Date:** 2026-06-09
> **Author:** Claude (research + codebase analysis)
> **Scope:** How HelixPay's Agent-2 extraction subsystem is designed, how the
> leading open-source KG/ontology-extraction frameworks and the 2024–2026
> research literature do the same job, and a prioritized set of recommendations.

---

## TL;DR

HelixPay's extraction design is genuinely strong. Its temporal + contradiction
handling puts it in the same small class as **Graphiti/Zep** and ahead of every
other framework surveyed (GraphRAG, LangChain, LlamaIndex, iText2KG, KGGen,
LightRAG, Cognee, fast-graphrag, TrustGraph). Its roster-first entity resolution
and predicate canonicalization avoid well-known failure modes that bite the
popular frameworks.

The two changes that will move the eval numbers most:

1. **Gleaning** — a single multi-pass extraction turn to recover missed claims
   (recall).
2. **Enforced evidence-span grounding gate** — require a verbatim source span and
   verify the claim is restorable from it (precision / faithfulness).

Two things to explicitly **not** do: don't gate/route on the LLM's self-reported
`confidence` (proven miscalibrated), and don't attempt automatic contradiction
resolution (~40% success even on frontier models — surfacing is correct).

---

## Part 1 — How HelixPay plans to do extraction

**Owner:** Agent 2 (`fanout/AGENT_2_extraction.md`), **Foundational** tier — the
critical-path / longest-pole of the 6-agent build. Code is already substantially
built in worktree `SP_003`.

### The pipeline

`helixpay/ingest/pipeline.py::run(root="data", repo=None)` — idempotent
end-to-end:

```
discover → load (Agent 1 connectors) → embed (Voyage 1024-dim)
→ add_chunks → per-chunk LLM extract → resolve entities → canonicalize predicate
→ persist Claim/Link → maybe-supersede same-source older claims
→ contradiction sweep over every (subject, canonical_predicate) touched
```

### Key design choices (all already implemented in SP_003)

| Concern | HelixPay's approach |
|---|---|
| Chunking | Owned by Agent 1 loaders, ~500–800 tokens, preserve speaker/section boundaries |
| Extraction unit | Per-chunk LLM call, `claude-sonnet-4-6` |
| Prompt | Named, versioned in `prompts/extract_claims.md` with `{{var}}` substitution — never hardcoded |
| Structured output | Lenient `RawExtraction` envelope → **validate-and-repair-once-or-drop** → per-item strict validation against `ClaimOut`/`RelationOut` (siblings survive an invalid item) |
| Output shape | `claims[]` (subject, predicate, object_value, as_of, confidence, evidence, hypothetical) + `relations[]` (from, to, link_type, as_of) |
| Entity resolution | **Roster-first**; Unicode accent-fold + honorific strip; context from `source_uri` (department); ambiguous bare name → `None` (no silent pick); person/team **never auto-created**, only customer/metric/product/other |
| Predicate canon. | `metric_vocab` table; unknown → returned unchanged, never raises |
| Contradictions | First-class rows; group by `(subject, canonical_predicate)`; numeric normalization (currency, K/M/B); **window-overlap** logic (two concrete different `as_of` ≠ contradiction); classified `value_conflict` / `temporal` / `source_disagreement` |
| Supersession | Same-source + newer `as_of` + conflicting value → set `valid_to` / `superseded_by`; **never delete** |
| Confidence | LLM self-reported `confidence` float, clamped [0,1] |
| Idempotency | `content_hash` doc key; natural-key claims/links; re-run is a no-op |

### Relevant frozen contracts (`helixpay/contracts/`)

```python
class Claim(BaseModel):
    subject_entity_id: Optional[int]
    predicate: str                  # canonicalized via metric_vocab
    object_value: Optional[str]
    object_entity_id: Optional[int]
    as_of: Optional[date]
    confidence: Optional[float]
    valid_from: Optional[date]
    valid_to: Optional[date]        # set on supersession
    superseded_by: Optional[int]
    source_chunk_id: Optional[int]
    document_id: Optional[int]

class Contradiction(BaseModel):
    subject_entity_id: Optional[int]
    predicate: Optional[str]
    claim_a_id: Optional[int]
    claim_b_id: Optional[int]
    kind: Optional[str]             # value_conflict|temporal|source_disagreement
    note: Optional[str]
    detected_at: Optional[datetime]
```

Protocols `SourceConnector`, `Repository`, `QueryEngine` are frozen at the gate.
All DB access goes through `Repository`; the ingest pipeline computes Voyage
embeddings and passes them to `Repository.add_chunks(chunks, embeddings)`; the
lexical `tsv` is a DB-generated column.

### Structured-output / validate-repair detail (`extract/llm.py`)

`call_structured(...)`:
1. LLM generates → parse against lenient `RawExtraction`.
2. On parse failure → **one** repair attempt (feed the error back).
3. On final failure → return `None` (never unvalidated output); logged with
   prompt name + outcome (`ok`/`repair`/`repaired`/`drop`).
4. After repair, each item is validated individually against strict
   `ClaimOut`/`RelationOut`; invalid items dropped, valid siblings kept.
5. Hypothetical/counterfactual claims dropped (never persisted as competing
   facts).

No secrets logged; `anthropic`/`voyageai` SDKs lazy-imported so unit tests need
neither SDK nor API key.

---

## Part 2 — What the GitHub frameworks and literature actually do

Surveyed: GraphRAG, LangChain `LLMGraphTransformer`, LlamaIndex
PropertyGraphIndex, **Graphiti/Zep**, iText2KG, KGGen, LightRAG, Cognee,
fast-graphrag, TrustGraph — plus 2024–2026 research on structured output, entity
resolution, contradiction/NLI, confidence calibration, and faithfulness.

### Comparison table (frameworks)

| Framework | Chunk Size | Extraction Mode | Gleaning | Entity Resolution | Temporal | Contradictions | Default Models |
|---|---|---|---|---|---|---|---|
| **GraphRAG** | 1,200 tok / 100 overlap | Few-shot, delimiter tuples | Yes (1 pass; CONTINUE+LOOP) | Name+type string match only | None (claims optional) | None | gpt-4.1 + text-embedding-3-large |
| **LLMGraphTransformer** | Caller-defined (~512 common) | Tool-calling (default) / few-shot JSON | None | Coreference prompt; strict_mode (id,type) dedup within call | None | None | Any LangChain LLM |
| **LlamaIndex PropertyGraph** | ~1,024 tok | Simple/Schema/Dynamic extractors | None | None built-in; post-process | None | None | Any via Settings.llm |
| **Graphiti (Zep)** | Episode-level | Structured output + Reflection pass | Yes (Reflection) | **3-stage: embedding + BM25 + LLM resolution** | **Bi-temporal (valid_at/invalid_at + created_at/expired_at)** | **LLM invalidation; t_invalid on contradiction** | gpt-4o-mini + BGE-m3 |
| **iText2KG** | Semantic blocks (schema-guided) | Zero-shot JSON | None | Embedding cosine (0.7), name+label dual embedding | None | None | GPT-4 + text-embedding-3-large |
| **KGGen** | Per-document | 2-stage (entities→relations) | None | **Iterative LLM clustering + LLM-as-judge** | None | None | GPT-4o via DSPy |
| **LightRAG** | 1,200 tok / 128 overlap | Few-shot, delimiter / JSON | Yes (1 pass, aggressive) | Name-match dedup + LLM merge | None | Descriptions merged | bge-m3 + configurable |
| **Cognee** | ~4,000 tok | Instructor/BAML Pydantic | None | OWL + fuzzy (0.80) | Versioned DataPoint | Soft invalidation | Any via LiteLLM |
| **fast-graphrag** | Overlapping | `instructor` library | Yes (until LLM signals done) | Hash-based chunk dedup | None | None | Any OpenAI/Gemini/Ollama |

### Where HelixPay already matches or beats the field

- **Temporal + contradictions-as-first-class.** Only **Graphiti** does this
  seriously among all frameworks reviewed. The rest silently merge or drop
  conflicts. HelixPay's `valid_to`/`superseded_by` + first-class `Contradiction`
  rows is essentially the Graphiti bi-temporal pattern — state-of-the-art.
- **Roster-first resolution returning `None` on ambiguity** is exactly what the
  coreference literature recommends for the shared-name problem — don't silently
  pick.
- **Predicate canonicalization before contradiction grouping** is correct and
  non-obvious; without it, contradiction detection no-ops. Most frameworks skip
  it.
- **Named/versioned prompts + validate-and-repair-or-drop** matches field
  consensus (Instructor's "repair once with the error, then drop").
- **Roster-first creation guard** (person/team never auto-created) prevents the
  exact "two Marias" duplication that GraphRAG's name+type string-merge gets
  wrong (GraphRAG issues #847, #962, #1718).

---

## Part 3 — Gaps worth acting on

### 1. No "gleaning" (multi-pass extraction) → recall left on the table  **[HIGH]**

The single most widely-adopted recall technique HelixPay is missing. GraphRAG,
LightRAG, fast-graphrag, and Graphiti (via a "reflection" pass) all do it. After
the first extraction, a continuation turn asserts *"MANY entities/relationships
were missed — add them"*, then a binary loop prompt asks whether more remain.
Default is **1 extra pass**; empirically ~15–25% more entities/claims per chunk.
GraphRAG's own finding: LLMs extract ~2× more from 600-token than 2,400-token
chunks — gleaning compensates for recall loss.

**Recommendation:** add an optional single gleaning pass to `ChunkExtractor`,
with a token-budget guard (LightRAG skips it past ~20k input tokens). Low effort,
directly improves the recall the Eval agent measures.

### 2. `evidence` captured but not enforced as a grounding gate  **[HIGH]**

The schema has an `evidence` field — good — but nothing verifies the claim's
subject/predicate/object actually appear in that span. The faithfulness research
converges on: require a verbatim `evidence_span`, then a deterministic/fuzzy
string check that the extracted values are restorable from it; drop/flag those
that aren't.

- Microsoft **Claimify**: 99% entailment via selectivity + disambiguation +
  decomposition; flags-and-excludes ambiguous claims rather than guessing.
- **PARSE/SCOPE**: three-gate validation (missing-attribute → source-grounding →
  rule-compliance) cut errors 92% on first retry.
- MDPI **anchor-constrained** "extract-then-restore": if every triplet element
  can be traced back to a source span by string match, hallucinations become
  detectable.

**Recommendation:** make `evidence` a required verbatim span and add a cheap
post-extraction grounding gate. Highest-leverage precision improvement; exactly
what the adversarial verifier will probe.

### 3. LLM self-reported `confidence` is poorly calibrated — don't gate on it  **[DON'T]**

Strong, consistent finding: verbalized confidence scores (model emitting `0.7`)
are systematically miscalibrated (Dunning-Kruger-like) — "On Verbalized
Confidence Scores for LLMs" (arXiv 2412.14737), LM-Polygraph (arXiv 2503.15850).
Fine to **store** it as a weak signal (HelixPay does), but don't use it as a
routing/drop threshold. If real confidence is ever needed, the gold standard is
**semantic entropy** (sample-and-cluster with an entailment model) or token
log-probs; isotonic regression / Platt scaling to calibrate against a golden set.
For this project, the practical move is simply: don't build logic that trusts the
number.

### 4. Entity resolution lacks embedding blocking + LLM tiebreak  **[MEDIUM]**

`resolve_entity` does normalized/alias string match against the roster. The SOTA
funnel (Graphiti, iText2KG, semantic-ER literature) is: **normalize → embedding
ANN against roster → LLM tiebreak only on surviving multi-candidate cases.**
Chunk embeddings are already computed, so a roster embedding index is cheap.
iText2KG's specific trick worth stealing: embed **name and type separately**
(weighted ~0.6/0.4) so "Python the language" ≠ "Python the snake", with a
calibrated threshold (~0.7).

**Recommendation:** keep the current exact-match tier as the fast path; add an
embedding tier *before* returning `None`, falling to LLM tiebreak with
`source_uri` context. Helps transliteration / variant names the string-fold
misses. The OpenSanctions work shows rule-based and LLM matchers are
**complementary** (rules over-predict, LLMs under-predict on transliteration).

### 5. Contradiction detection is value-equality, not semantic (NLI)  **[LOW]**

`values_conflict` is text/numeric equality after normalization. Catches "14.2M"
vs "15.1M" but not semantic contradictions in `object_value` prose. Field
standard for pairwise claim contradiction is a cross-encoder NLI model
(`cross-encoder/nli-deberta-v3-large`, ~90% MNLI). For HelixPay's mostly-numeric
financial metrics, the existing normalization is arguably *sufficient and more
deterministic* — but for non-numeric claims (titles, statuses, org facts) NLI
catches conflicts equality misses.

**Recommendation:** optional, lower priority — only if eval shows missed
non-numeric contradictions. Do **not** add auto-resolution: the reconciliation
(REG) task scores ~40% even on frontier models — surfacing (HelixPay's design)
is correct.

### 6. Two minor robustness items  **[LOW / TRIVIAL]**

- **Schema field ordering:** put reasoning/evidence *before* `confidence` /
  `object_value` in the output schema so the model commits after thinking, not
  before (benchmark finding, arXiv 2501.10868). Cheap prompt-level win.
- **Repair count:** "one repair then drop" is well-supported — research says
  >2–3 retries rarely help (failures are conceptual, not formatting). No change
  needed; just don't be tempted to raise it.

---

## Part 4 — Prioritized recommendations

| Priority | Change | Effort | Why |
|---|---|---|---|
| **High** | Add single **gleaning** pass (with token guard) to `ChunkExtractor` | Low | Biggest recall gain; field-standard; Eval agent measures recall |
| **High** | Enforce **evidence-span grounding gate** (verbatim + restorability check) | Low–Med | Biggest precision gain; defends against adversarial verifier |
| **Medium** | Add **embedding ANN + LLM tiebreak** tier to entity resolution (name+type separate embeddings) | Med | Catches variant/transliterated names string-fold misses |
| **Low** | Reorder schema so reasoning/evidence precedes confidence | Trivial | Free quality bump |
| **Low** | Optional **NLI** contradiction check for non-numeric claims | Med | Only if eval shows gaps |
| **Don't** | Gate/route on the LLM's self-reported `confidence` | — | Proven miscalibrated; store-only is fine |
| **Don't** | Auto-resolve contradictions | — | ~40% success even on frontier models; surface-only is correct |

---

## Part 5 — State-of-the-art techniques (reference notes)

### Gleaning (multi-pass extraction)
Origin: GraphRAG (Edge et al., 2024); copied into LightRAG, fast-graphrag.
Mechanics: after the primary turn, inject a continuation prompt asserting
entities were missed, then a binary loop prompt. Multi-turn conversation (model
sees its own prior output, avoids repetition). Production default everywhere is
N=1. Guard with a token budget.

### Entity resolution funnel (by sophistication)
1. String/name match (GraphRAG) — cheap, high precision, zero synonym recall.
2. Embedding cosine, dual-component name+type (iText2KG) — threshold ~0.7;
   prevents same-name/different-concept merges. Calibrate threshold on
   domain pairs.
3. Hybrid search + LLM resolution (Graphiti) — embedding + BM25 → LLM sees
   top-K candidates + context → resolves to existing UUID or new. Highest
   accuracy; 1 LLM call per new entity. Explicit "only if same real-world
   object" instruction prevents over-merge.
4. Iterative LLM clustering + LLM-as-judge (KGGen) — best cross-document synonym
   consolidation; O(n) iterations, expensive at scale.

For a **known roster** (HelixPay's case): normalize → embedding ANN against the
roster → LLM tiebreak only on multi-candidate ties → `None` when context
insufficient. Wikidata label lookup before the LLM call helps multilingual names.

### Bi-temporal edge handling (Graphiti)
Four fields per edge: `valid_at`, `invalid_at` (event timeline) + `created_at`,
`expired_at` (transaction timeline). LLM extracts `valid_at`/`invalid_at` from
text against a reference ingestion time; handles out-of-order arrival by sorting
on `valid_at`. Invalidation not deletion. `dedupe_edges` distinguishes
**duplicate** (same fact) from **contradicted** (superseded) — a fact can be
both. This is the pattern HelixPay's conventions already describe.

### Structured-output reliability (2025 consensus)
1. **Best:** constrained decoding — XGrammar / Guidance via vLLM, or provider
   JSON-schema mode for APIs. Zero structural failures, no retry cost. XGrammar
   is now the default backend for vLLM/SGLang/TensorRT-LLM.
2. **Second:** Instructor or BAML with `max_retries=2–3` for API/hosted.
3. **Drop vs repair:** repair once with the error fed back, then drop. >2–3
   retries rarely succeed (failure is conceptual, not formatting). Put
   `reasoning` before `answer` fields in the schema.
4. **Schema enrichment (PARSE):** 55% of effective improvements came from
   structural reorganization (field ordering/nesting), 34% from richer field
   descriptions — both beat adding retries.

### Confidence / uncertainty
Verbalized confidence: poorly calibrated, don't gate on it. Semantic Entropy
(Nature 2024) / SAR: gold standard for fact tasks (sample → cluster by entailment
→ entropy). Token log-probs: free but unavailable on some frontier APIs and fail
on knowledge-gap cases. Calibrate with isotonic/Platt against your own golden
set; recalibrate periodically.

### Faithfulness / grounding
Require an `evidence_span`; verify extracted values are restorable from it
(SCOPE/anchor-constrained). Claimify hits 99% entailment via selectivity +
disambiguation + decomposition, flagging-and-excluding ambiguous claims. Always
put the source document in the context window — models rationalize from
parametric memory when context is incomplete (FACTS Grounding).

### Evaluation
Build a golden set (200–500 claims, ≥3 doc types + planned contradiction cases).
Headline metric: **F_fact** = harmonic mean of Focus (precision) and Coverage
(recall) from FEVERFact — not token-match F1. Use semantic metrics (G-BERTScore)
not exact match. An LLM-as-judge (GraphJudge pattern, ~87% F1 with GPT-4o) works
for bulk eval, but validate the judge against the human golden set first; judge
accuracy drops to 60–68% on specialized domains. Track per-predicate-type recall
separately.

---

## Sources

### Frameworks
- Microsoft GraphRAG — https://github.com/microsoft/graphrag ;
  paper arXiv 2404.16130 ; entity-extraction prompt (gleaning CONTINUE/LOOP) in
  `graphrag/prompts/index/entity_extraction.py` ; ER weakness issues #847, #962,
  #1718
- LangChain `LLMGraphTransformer` —
  https://github.com/langchain-ai/langchain-experimental/blob/main/libs/experimental/langchain_experimental/graph_transformers/llm.py
- LlamaIndex PropertyGraphIndex —
  https://developers.llamaindex.ai/python/framework/module_guides/indexing/lpg_index_guide/
- Graphiti / Zep — https://github.com/getzep/graphiti ; paper arXiv 2501.13956 ;
  `extract_nodes.py`, `extract_edges.py`, `dedupe_nodes.py`, `dedupe_edges.py`,
  `edges.py`
- iText2KG — https://github.com/AuvaLab/itext2kg ; paper arXiv 2409.03284
- KGGen — https://github.com/knowledge-graph-hub/kggen ; paper arXiv 2502.09956
- LightRAG — https://github.com/HKUDS/LightRAG ; paper arXiv 2410.05779
- Cognee — https://github.com/topoteretes/cognee
- fast-graphrag — https://github.com/circlemind-ai/fast-graphrag
- TrustGraph — https://github.com/trustgraph-ai/trustgraph ;
  https://docs.trustgraph.ai/guides/ontology-rag/

### Structured output
- Generating Structured Outputs from LLMs: Benchmark — arXiv 2501.10868
- XGrammar — arXiv 2411.15100 ; XGrammar-2 — arXiv 2601.04426
- Instructor — https://python.useinstructor.com/learning/validation/retry_mechanisms/
- BAML — https://github.com/BoundaryML/baml
- PARSE (schema optimization + SCOPE validation) — arXiv 2510.08623
- Outlines — https://github.com/dottxt-ai/outlines

### Entity resolution
- The Rise of Semantic Entity Resolution —
  https://towardsdatascience.com/the-rise-of-semantic-entity-resolution/
- Splink — https://github.com/moj-analytical-services/splink ;
  BlockingPy — arXiv 2504.04266
- LLM-Driven Coreference-Resolved KGs — arXiv 2510.26486
- OpenSanctions Pairs — arXiv 2603.11051 ; SemEval-2025 Task 2 — arXiv 2506.13070
- Awesome Entity Resolution — https://github.com/OlivierBinette/Awesome-Entity-Resolution

### Contradiction / conflict
- Uncertainty Management in KG Construction: A Survey — arXiv 2405.16929
- cross-encoder/nli-deberta-v3-large —
  https://huggingface.co/cross-encoder/nli-deberta-v3-large
- Explanation Generation for Contradiction Reconciliation (REG) — arXiv 2603.22735
- LegalWiz: Multi-Agent Contradiction Detection — arXiv 2510.03418

### Confidence / calibration
- On Verbalized Confidence Scores for LLMs — arXiv 2412.14737
- Uncertainty Quantification and Confidence Calibration in LLMs (LM-Polygraph) —
  arXiv 2503.15850
- Cleanlab TLM Structured Outputs Benchmark —
  https://cleanlab.ai/blog/tlm-structured-outputs-benchmark/

### Faithfulness / grounding
- Grounded KG Extraction (anchor-constrained) — MDPI Computers 2025,
  https://www.mdpi.com/2073-431X/15/3/178
- FaithLens — arXiv 2512.20182
- Claimify — https://www.microsoft.com/en-us/research/blog/claimify-extracting-high-quality-claims-from-language-model-outputs/
  ; paper arXiv 2502.10855
- FACTS Grounding Leaderboard — arXiv 2501.03200

### Evaluation
- Can LLMs be Good Graph Judges for KG Construction? — arXiv 2411.17388
- FEVERFact (Focus/Coverage/F_fact) — arXiv 2502.04955
- KG-based RAG evaluation survey — arXiv 2510.02549
