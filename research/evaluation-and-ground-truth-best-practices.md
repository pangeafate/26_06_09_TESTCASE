# Evaluation & Ground Truth in HelixPay: Design Review + GitHub Best-Practice Report

> **Date:** 2026-06-10
> **Author:** Claude (research + codebase analysis)
> **Scope:** How HelixPay's Agent-6 evaluation + golden-truth subsystem is *designed*
> (it is specified but not yet built), how the leading open-source eval frameworks and
> the 2023–2026 literature do the same job, and a prioritized set of recommendations.
> Companion to `research/extraction-design-and-best-practices.md`.

---

## TL;DR

HelixPay's eval design is methodologically strong on the things most teams get
wrong: **author-independence** (ground truth hand-derived from raw `data/`, never
from build output), **binary capability checks** ("evals as unit tests"),
**format-stratified coverage**, and — rarest of all — testing that contradictions
are **surfaced, not resolved**. That last choice puts it ahead of the entire
public benchmark field (WikiContradict shows frontier models surface conflicts
<10% of the time without explicit prompting).

The design is currently **specified, not built** — `eval/` and `test/golden/` are
empty; the contract lives in `HELIXPAY_BUILD_SPEC.md` §8, `fanout/AGENT_6_eval.md`,
and `.claude/agents/verifier.md`.

The changes that will move eval *trustworthiness* most, in priority order:

1. **The golden set is statistically too small.** "A dozen-plus" facts cannot
   support a "recall bar" — one miss is an 8-point swing. Grow to ≥30–50 now
   (≥100 for a real CI gate), and **report Wilson confidence intervals**, not a
   bare ratio.
2. **Make "zero uncited claims" a measured metric, not a presence check.** Adopt
   ALCE-style citation precision/recall with an **NLI entailment gate**: the cited
   source must actually *support* the claim, not merely be attached.
3. **Validate the LLM judge before trusting it.** The answer-check verdicts
   (`cross_document_synthesis`, `attributes_each_side`) need a judge; measure its
   **TPR/TNR vs. human labels** (not raw agreement), use a **different model family
   than the synthesis model** (Opus synthesizes → don't let Opus alone grade), and
   keep every deterministic check deterministic.
4. **Specify the match function for "fact exists as a claim."** Exact-match on
   `source_uri` + `as_of`, resolved-`entity_id` match on subjects, normalized match
   on values — and report **per-predicate (macro) recall**, which is where
   `dotted_line_to` / `valid_to` misses hide.
5. **Upgrade contradiction scoring to WikiContradict's 3-class** (Correct = both
   sides named / Partial = one side or a pick / Incorrect = silent merge) with
   precision/recall over the planted set.

Two things to explicitly **not** do (consistent with the extraction report):
don't gate on the LLM's self-reported `confidence` (miscalibrated), and don't
score contradiction questions on final-answer accuracy (rewards silent resolution).

---

## Part 1 — How HelixPay plans to evaluate

**Owner:** Agent 6 (`fanout/AGENT_6_eval.md`), **Standard** tier — the
**author-independent oracle and adversary**. It authors ground truth from raw
`data/` with no sight of the build code, runs the autotest at integration, and
doubles as the verifier. Per the spec it is "the #1 quality lever."

**Status:** Not yet built. `eval/` and `test/golden/` do not exist on `main`. The
design is fully specified across three files:

- `HELIXPAY_BUILD_SPEC.md` §8 (the remit), §1 (acceptance criteria), §12 (the
  gated integration phase).
- `fanout/AGENT_6_eval.md` (the agent's scope-of-work).
- `.claude/agents/verifier.md` (the adversarial-verifier sub-agent — a stub the
  gate left for Agent 6 to refine).

### The two artifacts

| Artifact | Shape | Source of truth |
|---|---|---|
| `test/golden/facts.yaml` | "A dozen-plus" facts, `(subject, predicate, value, as_of, source_uri)`, ≥1 per format, **incl. the planted Q1 revenue/ARR contradiction** (dashboard vs. board deck, both as-of dates) | hand-inspection of raw `data/` |
| `eval/questions.yaml` | ~5 deep questions, each with binary `checks:` exercising a failure mode | derived from the data |

The five deep questions and their checks (§8):

```yaml
- q: "Who does the Head of Engineering report to, as of the latest org chart?"
  checks: [resolves_hierarchy, uses_freshest_as_of, cites_source]
- q: "What was HelixPay's ARR in Q1 2026?"
  checks: [surfaces_contradiction_if_sources_disagree, cites_source, states_as_of]
- q: "Summarize the CEO's priorities."          # CEO has no interview — cross-doc
  checks: [cross_document_synthesis, cites_multiple_sources]
- q: "Do the dashboards and the board deck disagree on any key metrics?"
  checks: [returns_contradictions, attributes_each_side]
- q: "List the customers mentioned and who owns each relationship."
  checks: [entity_resolution, alias_handling, cites_source]
```

### The two-level autotest (`eval/run.py`, wired into `make test` / `make demo`)

1. **Extraction check** — after ingest, assert every golden fact exists as a
   claim/link with the right `source_uri` + `as_of`; report **precision/recall**
   over the golden set.
2. **Answer check** — run each deep question through `ask()`; assert its `checks`
   (cites source, states `as_of`, resolves hierarchy, surfaces the planted
   contradiction); report **per-question pass/fail + latency**.

### Observability feeding the check (§8)

Extraction logs every LLM call (named prompt, inputs, structured output,
validate/repair outcome); the answer layer logs the plan route, what was
retrieved, which claims were cited. Agent 6 reads these to explain *why* a golden
fact was missed (bad chunk, failed resolution, dropped on repair) — root cause,
not just a red cell.

### The `/goal` pass condition (§8, §12)

`make test` green · golden-set recall **above a bar Agent 6 states in
`SOLUTION.md`** · `make demo` answers all deep questions with `as_of`-stamped
citations · **≥1 answer surfaces a real planted contradiction** · adversarial
stage filed and resolved.

---

## Part 2 — How the field does it (GitHub + literature, 2023–2026)

### A. Golden-dataset construction

**Author-independence is the accepted principle, and HelixPay nails it.** The term
of art is a *human-labeled gold set*; the test is Anthropic's: "two domain experts
would independently reach the same pass/fail verdict"
([Demystifying Evals for AI Agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)).
The named anti-pattern HelixPay avoids: deriving ground truth from the
system-under-test's own output (circular; reliably inflates metrics). Microsoft's
golden-dataset study found a **34% expert-rejection rate** on AI-generated QA
pairs — which is exactly why HelixPay's "by eye, from raw files" rule is correct
([Path to a Golden Dataset](https://medium.com/data-science-at-microsoft/the-path-to-a-golden-dataset-or-how-to-evaluate-your-rag-045e23d1f13f)).

**Sizing is where HelixPay is weak.** Anthropic's *Adding Error Bars to Evals*
([arXiv:2411.00640](https://arxiv.org/html/2411.00640v1)) is explicit: **n < 100
is statistically unreliable** — the CLT fails, confidence intervals mislead.
Detecting a 3-point quality difference at 80% power needs ~969 items. Practical
tiers from the literature (Anthropic, Hamel Husain, Maxim, Statsig):

| Size | What it buys |
|---|---|
| 20–50 | catches gross failures (early dev only) |
| 100 | statistical-reliability floor; error-analysis saturation |
| 200–250 | detect 3–5% differences with confidence (~246/slice rule of thumb) |
| 1,000+ | production-grade regression gate (~3pp detectable) |

Worse for RAG specifically: **clustered standard errors**. Multiple golden facts
drawn from the same document are correlated, which can make the true SE >3× the
naive one — so HelixPay's "≥1 fact per format" structure is *inherently* clustered
and needs interval reporting, not point estimates.

**Coverage = capability stratification.** Hamel Husain's feature → scenario →
source taxonomy ([Your AI Product Needs Evals](https://hamel.dev/blog/posts/evals/))
and the "look at your data" error-analysis loop (open-code traces → axial-code into
failure categories → stop at saturation, ~20 traces with no new category) are the
standard. HelixPay's "each check exercises a failure mode" is the same idea, just
under-populated. Anthropic's **capability-vs-regression split** matters too:
capability evals start at 50–70% and that's fine; regression evals should sit near
100% and a failure is an incident. **100% pass = the set is too easy**, not a win.

**Synthetic expansion, human promotion.** RAGAS `TestsetGenerator` (v0.2 = KG +
Specific/Abstract/Comparative synthesizers) and DeepEval's `Synthesizer` (7
evolution types: reasoning, multicontext, concretizing, constrained, comparative,
hypothetical, in-breadth) cut authoring time ~90% — but **every synthetic item
must be human-promoted to gold** (the 34% rejection rate again). Hybrid
silver→gold is the accepted pattern; shipping unreviewed synthetic items as ground
truth is not.

**Leakage is a first-class risk.** Three vectors: training-corpus contamination;
**prompt/few-shot contamination** (a golden fact used as a few-shot example
measures memorization, not capability); and **optimization leakage** (tuning
prompts repeatedly against the same held-out set folds it into training). Keep a
dev set separate from the locked eval set; lock the judge model version.

### B. KG / fact-extraction precision & recall

**Exact vs. partial match is not cosmetic.** The ACL GenBench paper
[*90% F1 in Relational Triple Extraction: Is it Real?*](https://arxiv.org/pdf/2302.09887)
shows systems at 90% F1 under *partial match* (last-token entity match) collapse
under *exact match* and OOD data. For a financial/temporal ontology where the
exact `as_of` date and exact source matter, **EM is the honest primary metric.**

**Match-function options for "does this golden fact exist in the graph":**
- *Exact / normalized* — what HelixPay needs for `source_uri` (exact) and `as_of`
  (exact or ±N-day), with value normalization (units, number formatting).
- *Semantic threshold* — Distill-SynthKG covers a gold triple if
  `max cos(gold, extracted) ≥ 0.88`; iText2KG dedupes entities at 0.70. Useful for
  the *value*/*subject* surface form, dangerous for dates.
- *2-hop + LLM judge* — KGGen's MINE: embed gold fact, retrieve top-k KG nodes,
  expand 2-hop, ask a judge "is this fact inferable from this subgraph?"
  ([arXiv:2502.09956](https://arxiv.org/abs/2502.09956)). Catches non-local
  compound facts ("Q1 ARR reported by source X on date Y") that single-node lookup
  misses.

**Report macro-F1 per predicate, not just micro.** Micro-F1 is dominated by
high-frequency predicates (`name`, `org`); macro-F1 weights the rare-but-critical
ones (`reports_to`, `dotted_line_to`, `valid_to`, `annual_recurring_revenue`)
equally. A 95% micro score can hide a `dotted_line_to` recall of 0.

**Joint scoring:** a triple counts as a true positive only if subject, predicate,
*and* object are all simultaneously correct — stricter than scoring entities and
relations separately, and the right standard for fact-completeness.

### C. Citation / attribution ("zero uncited claims")

This is HelixPay's headline constraint, and the spec currently checks it as a
**boolean presence flag** (`cites_source`). The field measures it as a **graded,
NLI-backed metric** — ALCE ([github.com/princeton-nlp/ALCE](https://github.com/princeton-nlp/ALCE),
EMNLP 2023):

- **Citation recall** (per sentence) = 1 iff the sentence has ≥1 citation *and* the
  concatenated cited docs **entail** the sentence (NLI). "Does every claim have
  support?"
- **Citation precision** (per citation) penalizes citations that are neither
  individually entailing nor jointly necessary. "Are the citations actually doing
  work?"

The crucial gap a presence check misses: a citation can be *attached* to a claim
the source does not support. ALCE's NLI gate (TRUE / T5-11B; any NLI model works)
catches that. RAGAS/DeepEval implement the same idea as **faithfulness =
supported-claims / total-claims** (decompose answer → entailment-check each claim
against retrieved context). TREC-2024's RAG track validated GPT-4o as a citation
judge at human-competitive agreement (κ≈0.29 vs. human-human κ≈-0.03). FActScore
and ProVe round it out (ProVe is the closest existing tool to verifying that a
*source URI actually supports* a triple — relevant to HelixPay's `source_uri`
check; pitfall: dead URLs, so **cache source docs at ingest**).

### D. LLM-as-judge reliability

The answer-checks (`cross_document_synthesis`, `attributes_each_side`,
`alias_handling`) cannot be pure string matches — they need a judge. The
literature is unanimous that an **unvalidated judge is the dominant eval failure
mode**:

- **Validate against human labels with TPR/TNR, not raw agreement.** Class-
  imbalanced sets (most answers are fine) make accuracy lie. Use **Balanced
  Accuracy = (TPR+TNR)/2** and Cohen's κ; target >90% agreement / κ>0.7. The
  documented disaster: **agreeableness bias** — judges with TPR>96% but TNR<25%
  (passes almost everything) ([arXiv:2510.11822](https://arxiv.org/html/2510.11822)).
- **Don't let the synthesis model grade its own answers.** Self-preference is
  10–25% in MT-Bench ([arXiv:2306.05685](https://arxiv.org/abs/2306.05685)). Since
  HelixPay synthesizes with Opus, the judge should be a different family (or at
  least a different model) for the subjective checks.
- **Binary + chain-of-thought is the only universally positive mitigation**
  (+1.5–13pp; [arXiv:2604.23178](https://arxiv.org/html/2604.23178v1)). Low-
  precision scales (binary / 3-point) beat 1–10 scales. Position-swap helps some
  models, hurts others — test, don't assume.
- **Keep deterministic checks deterministic.** `cites_source` (≥1 citation
  present), `states_as_of` (date present + matches), `returns_contradictions`
  (`AnswerBundle.contradictions` non-empty) need no LLM at all — assert them in
  code. Reserve the judge for genuinely semantic checks.

### E. Contradiction & temporal evaluation

HelixPay's "surface, don't resolve" stance is **the correct and rare one.**
WikiContradict (NeurIPS 2024, [arXiv:2406.13805](https://arxiv.org/html/2406.13805v1))
shows frontier models surface conflicts **2.1–10.4% of the time without explicit
prompting** (43.8% with). Its 3-class metric is the upgrade HelixPay should adopt:

- **Correct** — names both conflicting values, favors neither.
- **Partial** — names one, or names both but picks a side.
- **Incorrect** — merges into a false synthesis (the worst case).

The current `/goal` bar ("≥1 answer surfaces a real planted contradiction") is a
floor; strengthen to **contradiction precision/recall over the planted set**, and
assert `AnswerBundle.contradictions` references **both** claim IDs with neither
value silently dropped.

**Don't conflate freshness with contradiction.** A system that always returns the
newest value scores well on freshness benchmarks (FreshQA) but *fails*
WikiContradict — it silently resolves. HelixPay needs both, separately tested:
prefer-fresh-and-say-so when there's no conflict (As-of Correctness; recency
prior, [arXiv:2509.19376](https://arxiv.org/abs/2509.19376)); surface-both when two
valid-period claims genuinely conflict. ConflictBank's finding reinforces the
design: explicit temporal anchoring in the prompt drops the "ignore the conflict"
rate from 67.5% to 8.3% ([arXiv:2408.12076](https://arxiv.org/html/2408.12076v1)).

### F. Entity-resolution / alias evaluation

For the two-Marias / two-Tans traps, assert the **resolved `entity_id` (UUID)**,
not the string — measure resolution precision (correct entity / all resolved) and
recall. Use CORE-KG's **node-duplication-rate** as a cheap smoke test
(RapidFuzz `partial_ratio ≥ 75%` flags candidate duplicate nodes;
[arXiv:2510.26512](https://arxiv.org/abs/2510.26512)). Predicate canonicalization
is, per iText2KG, the **hardest and least-evaluated** step (relation similarity
runs lower than entity similarity) — add explicit golden synonym pairs (`ARR` vs.
"annual recurring revenue") asserting they land on the **same canonical key**,
because if they don't, contradiction detection silently no-ops.

---

## Part 3 — Recommendations (prioritized)

Tiered for the take-home's time budget. **P0 = do before calling `/goal` met;**
P1 = high-leverage, low-cost; P2 = production scale-up (state as a scope cut in
`SOLUTION.md`).

### P0 — trustworthiness blockers

1. **Grow the golden set to ≥30–50 facts and report Wilson confidence intervals
   on precision/recall** (not a bare ratio). State the n and the interval in
   `SOLUTION.md`; acknowledge clustered SE explicitly. *Why:* a dozen facts cannot
   support a "recall bar" — the bar is noise. (Anthropic error-bars paper.)
   *Cost:* ~1–2h of hand-labeling; the single biggest credibility win.

2. **Turn `cites_source` into an NLI-backed citation check.** For each claim in an
   `ask()` answer, verify the cited chunk **entails** it (ALCE recall) and that
   citations aren't padding (ALCE precision). Report citation precision/recall
   alongside per-question pass/fail. *Why:* "zero uncited claims" is the headline
   constraint and a presence flag doesn't test it. *Cost:* one NLI call per
   claim, or reuse the judge.

3. **Validate the answer-check judge before trusting it.** Hand-label ~20–30
   answer outputs pass/fail, measure judge **TPR/TNR + κ**, iterate the judge
   prompt to >90% agreement, and **use a non-Opus judge** for the subjective
   checks. Keep `states_as_of` / `returns_contradictions` / citation-presence as
   **deterministic code assertions**. *Why:* agreeableness + self-preference bias
   otherwise silently passes a half-built system — exactly the failure §8 exists
   to prevent.

4. **Specify the match function** in `eval/run.py`: `source_uri` exact,
   `as_of` exact (or ±N days, stated), subject by **resolved `entity_id`**, value
   normalized. Report **macro recall per predicate**, not only micro. *Why:* an
   unspecified matcher makes precision/recall unauditable; macro surfaces the
   `dotted_line_to` / `valid_to` misses a micro score hides.

### P1 — high-leverage, low-cost

5. **Adopt WikiContradict 3-class contradiction scoring** (Correct/Partial/
   Incorrect) with precision/recall over the planted set; assert both claim IDs
   present in `AnswerBundle.contradictions`. Keep the "≥1 surfaced" as the floor.

6. **Separate a freshness check from the contradiction check.** Add a question
   where the right behavior is *prefer-fresh-and-say-so* (no conflict), distinct
   from the *surface-both* contradiction case. Report As-of Correctness.

7. **Assert resolved `entity_id` for the name-collision facts** and add a
   node-duplication-rate smoke test; add **predicate-synonym golden pairs**
   (`ARR` ≡ "annual recurring revenue" → same canonical key).

8. **Leakage discipline:** keep golden facts out of extraction/synthesis few-shot
   prompts; lock the judge model version; don't tune prompts against the locked
   eval set (use a dev split). Cache source docs at ingest so provenance checks
   don't depend on live reads. (Already aligned with DEV_RULES §12 — version the
   gold set in git.)

### P2 — production scale-up (scope-cut in `SOLUTION.md`)

9. **Grow to 100+ facts** via RAGAS/DeepEval synthetic generation **with human
   promotion** (expect ~34% rejection), then split **capability vs. regression**
   evals. Expect capability ~50–70%; treat regression failures as incidents.

10. **Error-analysis-driven growth:** every missed golden fact and every demo
    failure becomes a new golden item; stop adding categories at saturation.

11. **Uncertainty reporting at scale:** ARES-style PPI confidence intervals
    (needs ~150 human labels) or a panel-of-judges with minority-veto to lift TNR.

### Explicitly do NOT

- Don't gate or route on the LLM's self-reported `confidence` (miscalibrated —
  consistent with the extraction report).
- Don't score contradiction questions on final-answer accuracy — it rewards silent
  resolution, the exact failure the ontology exists to prevent.
- Don't validate a judge on raw agreement over a class-imbalanced set (a lenient
  judge looks great and catches nothing).

---

## Sources

### Golden-set construction & sizing
- Anthropic — Demystifying Evals for AI Agents — https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- Anthropic — Adding Error Bars to Evals — arXiv 2411.00640 ; https://www.anthropic.com/research/statistical-approach-to-model-evals
- Hamel Husain — Your AI Product Needs Evals — https://hamel.dev/blog/posts/evals/
- Hamel Husain — LLM-as-Judge — https://hamel.dev/blog/posts/llm-judge/ ; Evals FAQ — https://hamel.dev/blog/posts/evals-faq/
- Eugene Yan — Evaluating LLM-Evaluators — https://eugeneyan.com/writing/llm-evaluators/ ; Task-specific evals — https://eugeneyan.com/writing/evals/
- Microsoft — Path to a Golden Dataset — https://medium.com/data-science-at-microsoft/the-path-to-a-golden-dataset-or-how-to-evaluate-your-rag-045e23d1f13f
- Maxim — Building a Golden Dataset — https://www.getmaxim.ai/articles/building-a-golden-dataset-for-ai-evaluation-a-step-by-step-guide/
- Statsig — Golden Datasets as Evaluation Standards — https://www.statsig.com/perspectives/golden-datasets-evaluation-standards
- Cameron Wolfe — Applying Statistics to LLM Evaluations — https://cameronrwolfe.substack.com/p/stats-llm-evals
- Daniel Corin — Evals: Unit Testing for LMs — https://www.danielcorin.com/posts/2024/evals-unit-testing-for-lms/

### Eval frameworks
- RAGAS — https://github.com/explodinggradients/ragas ; paper arXiv 2309.15217 ; testset gen v0.2 — https://docs.ragas.io/en/stable/getstarted/rag_testset_generation/
- DeepEval — https://github.com/confident-ai/deepeval ; faithfulness template.py ; Synthesizer — https://deepeval.com/guides/guides-using-synthesizer
- TruLens (RAG triad) — https://github.com/truera/trulens ; OTel — https://www.trulens.org/otel/
- promptfoo — https://github.com/promptfoo/promptfoo ; LLM-as-judge guide — https://www.promptfoo.dev/docs/guides/llm-as-a-judge/
- continuous-eval — https://github.com/relari-ai/continuous-eval
- ARES (fine-tuned judges + PPI) — https://github.com/stanford-futuredata/ARES ; arXiv 2311.09476
- Phoenix / Arize — https://github.com/Arize-ai/phoenix

### KG / triple-extraction eval
- 90% F1 in Relational Triple Extraction: Is it Real? — arXiv 2302.09887
- KGGen / MINE — https://github.com/stair-lab/kg-gen ; arXiv 2502.09956
- Distill-SynthKG — arXiv 2410.16597
- iText2KG — https://github.com/AuvaLab/itext2kg ; arXiv 2409.03284
- GraphJudge — https://github.com/hhy-huang/GraphJudge ; arXiv 2411.17388
- CORE-KG (node-duplication-rate) — arXiv 2510.26512
- ProVe (provenance verification) — https://journals.sagepub.com/doi/full/10.3233/SW-233467
- TGB 2.0 (temporal KG) — https://github.com/shenyangHuang/TGB ; arXiv 2406.09639
- When Facts Expire — CIKM 2025, https://dl.acm.org/doi/10.1145/3746252.3761648

### Citation / attribution
- ALCE — https://github.com/princeton-nlp/ALCE ; arXiv 2305.14627
- AttributedQA / AutoAIS — https://github.com/google-research-datasets/Attributed-QA ; arXiv 2212.08037
- FActScore — https://github.com/shmsw25/FActScore ; arXiv 2305.14251
- RARR — arXiv 2210.08726
- TREC 2024 RAG support eval — arXiv 2504.15205

### LLM-as-judge reliability
- MT-Bench / Chatbot Arena — arXiv 2306.05685
- Judging the Judges (position bias) — arXiv 2406.07791 ; (bias mitigation) — arXiv 2604.23178
- G-Eval — arXiv 2303.16634
- Balanced Accuracy for judges — arXiv 2512.08121 ; Agreeableness bias — arXiv 2510.11822
- LLMs-as-Judges survey — arXiv 2412.05579

### Temporal / contradiction
- WikiContradict — arXiv 2406.13805 (NeurIPS 2024)
- ConflictBank — arXiv 2408.12076 (NeurIPS 2024)
- Knowledge Conflicts Survey — arXiv 2403.08319 ; https://github.com/pillowsofwind/Knowledge-Conflicts-Survey
- FreshQA / FreshLLMs — ACL 2024 Findings, https://aclanthology.org/2024.findings-acl.813/
- Recency prior for RAG freshness — arXiv 2509.19376
- TempReason — arXiv 2306.08952
- Contradiction Detection in RAG — arXiv 2504.00180
