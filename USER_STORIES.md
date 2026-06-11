---
status: living
last-reconciled: 2026-06-12
authoritative-for: [user-stories, acceptance-criteria]
---

# User Stories

Derived from `HELIXPAY_BUILD_SPEC.md` §1 (acceptance criteria). The consumer is an
**AI agent** (exec-briefing bots, sales-prep agents, support copilots) plus the
grader. Each story notes the gate's contribution and the owning agent for the rest.

## US-1 — Grounded answers with provenance
> As an agent, I can ask a deep question and get an answer where every claim cites
> its `source_uri` and `as_of`, so I can trust and attribute it.

- Acceptance: `ask()` returns an `AnswerBundle` with zero uncited claims.
- Gate: `Citation`/`AnswerBundle` contracts; `Repository.get_sources`. Full: Agent 3.

## US-2 — Conflicts surfaced, never silently resolved
> As an agent, when sources disagree (e.g. Q1 revenue: dashboard vs board deck), the
> answer surfaces the contradiction and attributes each side.

- Acceptance: contradictions returned as first-class objects, both sides cited.
- Gate: `contradictions` table + `add_contradiction` + query fixture conflict. Full: Agents 2/3.

## US-3 — Hierarchy resolution
> As an agent, I can ask who reports to whom as of the latest org chart and get the
> correct chain, including dotted-line relationships.

- Acceptance: org hierarchy resolved via recursive query with `as_of` filtering.
- Gate: seeded roster + `reports_to`/`dotted_line_to` links + `get_org_subtree`. Full: Agent 3.

## US-4 — Staleness handling
> As an agent, I prefer fresh facts over stale ones and am told when a fact is stale.

- Acceptance: freshest-wins resolution; `as_of_coverage` populated.
- Gate: temporal columns; seeded rows stamped `as_of=2026-04-15`. Full: Agent 3.

## US-5 — Alias / entity resolution
> As an agent, messy mentions (HPB, Helix Brasil; the two Marias) resolve to the right
> canonical entity.

- Acceptance: roster-first resolution; ambiguous bare names don't silently mis-resolve.
- Gate: seeded roster + aliases + `resolve_entity(name, type, context)`. Full: Agent 2.

## US-6 — One-command run, live in production
> As the grader, `make up && make ingest && make demo` works from a fresh clone with
> only env vars, and the system is reachable at a live URL.

- Acceptance: idempotent ingestion; MCP over streamable-HTTP at the domain.
- Gate: idempotent schema + seed; config from env. Full: Agents 4/5.

## US-7 — Retrieval primitives for connected agents (SP_022)
> As an agent (ChatGPT/Claude) connected to the live MCP, I can `search` the corpus,
> `fetch` a hit's full text, list the `get_sources` document inventory, and enumerate
> entities by type — so corpus-scoped and entity-scoped questions ("what discussions did
> Wei Chen have recently", "what countries are covered") are answerable directly, not only
> through `ask` synthesis.

- Acceptance: all four retrieval tools return `available:true` against the real engine;
  `search` is RRF-ranked with `source_as_of` + provenance; `fetch` returns full text and
  never raises on a bad id; `list_entities('other')` enumerates regions/org-units.
- Gate: `ExposureEngine` optional surfaces over `HelixQueryEngine` + additive `Repository`
  reads (`get_chunk`/`list_documents`/`list_entities`). Full: SP_022.

## US-8 — Graph & temporal reads for connected agents (SP_023)
> As an agent connected to the live MCP, I can read the *history* of a fact (`get_timeline`),
> traverse an entity's relationships beyond the org chart (`get_relationships`), discover the
> queryable metric vocabulary (`list_metrics`), and compare one predicate across entities
> (`get_claims_by_predicate`) — so temporal, graph, vocabulary-discovery and cross-entity
> questions are answerable without `ask` synthesis.

- Acceptance: all four tools return `available:true` against the real engine; `get_timeline`
  shows the supersession chain + coexisting conflicting values in order, each cited, and
  degrades to `resolved:false` on an ambiguous entity; `get_relationships` returns both
  directions with resolved endpoint names; `get_claims_by_predicate` canonicalizes
  raw/alias/period-qualified spellings onto one key across subjects (excluding distinct
  suffixes and glued tokens).
- Gate: `ExposureEngine` optional surfaces + additive `Repository` reads (`get_links`
  `to_entity_id`, `list_metrics`, `get_claims_by_predicate`) + the `MetricVocab` model; frozen
  `QueryEngine` untouched; `$0` (pure DB reads). Full: SP_023.

## US-9 — Trustworthy contradictions: precision + semantic adjudication (SP_028a/SP_028b)
> As the operator, the contradiction layer surfaces the GENUINE cross-document conflicts and
> stops flooding spurious ones, so a human (or a connected agent reading
> `AnswerBundle.contradictions`) can trust that a surfaced conflict is real and that both sides
> are shown — never silently resolved to one value.

- Acceptance: the SP_028a deterministic sweep collapses the format/multi-valued/breakdown spurious
  classes at $0 (live `helixpay_full` 266 → 115) with zero real conflicts lost; the SP_028b LLM
  pass then refines precision (drops same-fact-different-words pairs) and adds the cross-predicate /
  solid-vs-dotted recall the same-predicate comparator can't see — both sides cited, no winner
  field; a re-sweep of an unchanged store is $0 (content-hash cache).
- Gate: single-writer clear-then-rewrite sweep; `predicate_cardinality` + shared `DedupWriter`
  (SP_028a); two labeled claim/link blocks + Opus(temp-0) adjudication + content cache +
  deterministic fallback floor (SP_028b); frozen `Contradiction`/`Repository` untouched. Full:
  SP_028a, SP_028b.
