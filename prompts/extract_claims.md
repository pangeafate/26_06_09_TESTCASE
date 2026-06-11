# Extraction prompt — claims + relations from one chunk

You extract a **temporal, provenance-carrying ontology** from one span of a HelixPay
document. HelixPay is a B2B payments company; the corpus is a messy multi-format snapshot
(markdown, PDF tables, HTML dashboards, Slack, email, interviews, an org chart). Emit
**only what this span actually asserts** — never guess, never use outside knowledge.

## Source
- source_type: `{{source_type}}`
- source_uri: `{{source_uri}}`
- document as_of (fallback date for undated facts in this span): `{{as_of}}`

## Known entities (resolve mentions toward these where they clearly match; may be empty)
{{roster_hint}}

## What to extract

**Claims** — a property value asserted about a subject. One claim per asserted fact.
- `subject`: the **entity** the fact is about — a person, team, customer, product, the
  company, or a named region/subsidiary. **Never a bare metric name.** A KPI or financial
  figure with no explicitly named owner belongs to the document's **primary entity**: this
  corpus is about **HelixPay**, so an ownerless company metric (a dashboard card, a board
  figure) has `subject` = `HelixPay`. If the figure is explicitly scoped to a region or
  subsidiary (e.g. "Brasil Q1 revenue", "HelixPay Brasil"), use that scoped entity as the
  subject (`HelixPay Brasil`) — never collapse a regional figure onto HelixPay.
- `subject_type`: one of `person | team | customer | product | other` for the subject entity
  (use `other` for the company / a region). **Do not use `metric` as a subject_type for a
  company KPI** — the metric is the *predicate*, not the subject.
- `predicate`: the property — the **canonical metric name, with any time period stripped off**
  ("revenue", not "Q1 2026 revenue"; "nps"; "arr"; "headcount"; "runway"; "monthly burn";
  "net new merchants"; …). The reporting period goes in `as_of`, not in the predicate. It is
  canonicalized downstream, so do not invent codes.
- `object_value`: the value **exactly as written**, including units and currency
  (illustrative shapes only — `"SGD 9.9M"`, `"315"`, `"end of May"`). Keep the as-of date
  attached to the number it belongs to.
- `as_of`: the date this value is true *as of*, **always `YYYY-MM-DD`**. When the text
  gives a quarter (e.g. "Q1 2026"), emit the quarter-**end** date directly:
  Q1→`YYYY-03-31`, Q2→`YYYY-06-30`, Q3→`YYYY-09-30`, Q4→`YYYY-12-31`
  (e.g. "Q1 2026" → `2026-03-31`). A bare year "2026" → `2026-12-31`.
  Use the value's own reporting period first; fall back to the document as_of only if the
  value names no period of its own. **A dashboard's "As of <date>" header is NOT the metric's
  as_of** — a card labelled "Q1 2026 Revenue" is `as_of` `2026-03-31` (the quarter end), even
  if the dashboard was exported on 2026-04-21. Omit only if truly undated.
- `confidence`: 0.0–1.0, how clearly the span states this.
- `evidence`: a **verbatim** quote copied from this span that contains the value (do not
  paraphrase the number — copy it exactly; this span is checked against the source).
- `hypothetical`: **`true`** if the value is counterfactual, hypothetical, a target/plan,
  or a "would have been" — e.g. "the renewal *would have been* SGD 165K", "if we'd closed".
  These are NOT asserted facts and must be flagged so they are not stored as competing
  values. Set `false` for actual, realized values.

**Relations** — typed links between two entities.
- `from_entity`, `to_entity`: the two entity names.
- `link_type`: one of `reports_to` (solid-line management) | `dotted_line_to` (functional
  dotted-line) | `owns` (e.g. an account exec owns a customer relationship) | `member_of`
  (person→team) | `mentions`. Keep solid and dotted reporting **distinct**.
- `as_of`, `confidence`: as above.

## Rules
- **Do not collapse or resolve conflicts.** If the span gives two different values, emit
  both as separate claims — contradictions are detected downstream, not by you.
- **Capture the as-of date** with every metric value. That is where staleness and
  contradictions hide.
- **Distinguish people who share a name.** If the text refers to a specific person, use
  their full name as written; do not merge two different people who share a first name or
  surname (e.g. two colleagues both written as "A. Mensah") into one.
- Skip pure chrome (navigation, boilerplate). Prefer fewer, well-grounded claims over many
  speculative ones.

## Attribution examples (the metric-as-subject trap)

A KPI is a property **of an entity**; the metric is the predicate, never the subject.

- A dashboard card "Q2 2027 Revenue (SGD) 9.9M" (fictional figure):
  - ✗ wrong: `{"subject": "Q2 2027 Revenue", "subject_type": "metric", "predicate": "Q2 2027 Revenue", "object_value": "9.9M"}`
  - ✓ right: `{"subject": "HelixPay", "subject_type": "other", "predicate": "revenue", "object_value": "SGD 9.9M", "as_of": "2027-06-30"}`
- A region row "Brasil Q2 Revenue — SGD equiv 3.3M" (scoped, so it stays on the region):
  - ✓ right: `{"subject": "HelixPay Brasil", "subject_type": "other", "predicate": "revenue", "object_value": "SGD 3.3M", "as_of": "2027-06-30"}`

## Initiative milestones & contributor rankings

Two more attributions that are easy to mis-shape:

**A project / initiative milestone** (a GA / launch date, a migration cutover or
legacy-system decommission) is a claim about the **named initiative**, not the company:
- `subject` = the initiative as named (a fictional "Project Atlas", "Ledger migration"). If the
  span uses a surface form ("the Atlas platform", "the X → Y cutover"), still use the canonical
  initiative entity — resolution to the seeded name happens downstream, not here.
- `predicate` = the **canonical milestone name**: `ga_target` for a go-live / general-
  availability / launch date; `completion_target` for a migration completion / cutover /
  legacy-system decommission. (A migration **start** date is NOT a completion — keep it a
  separate, plainly-named predicate.)
- `object_value` = the milestone date as a **clean human phrase including the year**
  ("end of Q4 2027", "end of May 2027") — not a bare token ("end-Q4") and not a parenthetical
  ISO date ("(2027-12-31)").
- `as_of` = the date the milestone is **asserted** (the document/board date), since a target
  is a forward-looking assertion, not a realized period.

Examples (fictional subjects/values — they teach the SHAPE, never a real fact):
- Board deck "Project Atlas platform — Original plan: end-Q1 GA. Reality: end-Q4." (dated):
  - ✗ wrong: `{"subject": "Atlas platform", "subject_type": "product", "predicate": "ga target date (revised)", "object_value": "end-Q4 (2027-12-31)"}`
  - ✓ right: `{"subject": "Project Atlas", "subject_type": "other", "predicate": "ga_target", "object_value": "end of Q4 2027", "as_of": "<board date>"}`
- Slack "legacy ledger decommission — end of may for everyone" (dated):
  - ✗ wrong: `{"subject": "HelixPay", "subject_type": "other", "predicate": "ledger decommission date", "object_value": "end of May"}`
  - ✓ right: `{"subject": "Ledger migration", "subject_type": "other", "predicate": "completion_target", "object_value": "end of May 2027", "as_of": "<message date>"}`

**A contributor / ownership ranking** (a doc that names who *leads* a repo, component, or
account by an explicit measure) yields a claim whose `subject` is the thing being led and
whose value is the **named leader**:
- predicate `top_contributor`; `subject` = the repo/component (e.g. a fictional "acme/core");
  `object_value` = the person named as the leader. **Direction matters: the repo is the
  subject and the person is the value — never the reverse.**
- Only emit it when the span **explicitly states the lead** (a fictional "J. Okafor led Q2 with
  73 commits"); do not infer a winner the document does not name.
  - ✓ right: `{"subject": "acme/core", "subject_type": "other", "predicate": "top_contributor", "object_value": "J. Okafor", "as_of": "2027-06-30"}`
  - ✗ wrong (inverted): `{"subject": "J. Okafor", "subject_type": "person", "predicate": "top_contributor", "object_value": "acme/core"}`

## Charts & figures (image transcriptions)

When the span is a transcribed chart/graph (a `source_type: image` caption that lists data
**series** and their values by period), extract the datapoints, not just the title:

- A chart of a metric **by region or segment over time** yields **one claim per region per
  period** for each **actual** series. Treat each series line independently.
- `subject` = the **scoped region/segment entity**, canonicalized: a "SEA"/"Southeast Asia"
  series ⇒ `HelixPay SEA`; a "Brasil"/"Brazil" series ⇒ `HelixPay Brasil`. **Never collapse a
  regional series onto `HelixPay`** (a region's value is not the company's), and never merge two
  regions together. `subject_type` = `other`.
- `predicate` = the metric the chart plots, period stripped (e.g. a "Revenue by region" chart ⇒
  `revenue`). `object_value` = the value **as transcribed, with its unit** (keep the chart's unit
  of measure). `as_of` = that period's **end** date (the quarter-end rule above; use the ISO date
  the caption gives next to the period label).
- A **plan / target / forecast** series — or any series the caption marks as dashed — is **not an
  asserted actual**: set `hypothetical: true` so it is never stored as a competing value against
  the actual. Only the solid/actual series are realized facts.
- Extract only datapoints actually present in the transcription; never infer an unplotted value.

(Describe the shape only — the numbers come from the transcribed caption, not from here.)

## Sales pipeline / CRM deal snapshots

A sales-pipeline or CRM dashboard lists **open deals/opportunities** with their **current
recorded state** as of the snapshot. That recorded state **is an asserted fact** about the
deal — **not** hypothetical — even though the deal's outcome is still in the future. Do not
skip a pipeline table as "speculative": extract one claim per deal attribute the row gives.

- `subject` = the **account / opportunity** as named (e.g. a fictional "Acme Robotics" /
  "Globex Retail" — use the real name from the row); `subject_type` = `customer`.
- `predicate` = the attribute, canonical and period-stripped: `pipeline_stage`,
  `deal_amount`, `deal_owner`, `expected_close_date`, `deal_health`.
- `object_value` = the cell value exactly as written (illustrative shapes: a stage word, an
  amount like "450K", an ISO date, a health phrase).
- `as_of` = the dashboard's snapshot/export date. **This is the one case where the export
  date IS the as_of** — it dates the deal's *recorded state*, not a metric's reporting period
  (contrast the KPI-card rule above). Use the "as of <date>" header.
- `hypothetical` = `false` for a recorded deal attribute. Only an explicitly **weighted /
  forecast aggregate** (e.g. a "total weighted pipeline" or "coverage ×" figure) is
  forward-looking → `true`.

  ✓ right (shape only — fictional values): `{"subject": "Acme Robotics", "subject_type": "customer", "predicate": "expected_close_date", "object_value": "2026-08-15", "as_of": "<snapshot date>", "hypothetical": false}`

## Output — STRICT JSON ONLY

Return a single JSON object and nothing else (a lone ```json fence is tolerated but not
required). It must match this shape exactly:

```
{
  "claims": [
    {"subject": "...", "subject_type": "other", "predicate": "...",
     "evidence": "<verbatim quote from the span containing the value>",
     "object_value": "...", "as_of": "YYYY-MM-DD", "confidence": 0.0, "hypothetical": false}
  ],
  "relations": [
    {"from_entity": "...", "to_entity": "...", "link_type": "reports_to",
     "as_of": "YYYY-MM-DD", "confidence": 0.0}
  ]
}
```

If the span asserts nothing extractable, return `{"claims": [], "relations": []}`.

## The span

```
{{chunk_text}}
```
