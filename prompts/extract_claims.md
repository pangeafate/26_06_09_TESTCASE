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
- `subject`: the entity the fact is about (a person, team, customer, product, the company,
  or a metric name like "ARR"). Use the clearest surface name in the text.
- `subject_type`: one of `person | team | customer | product | metric | other` (omit if unsure).
- `predicate`: the property. For business metrics use the metric's name as written
  ("ARR", "annual recurring revenue", "Q1 revenue", "NPS", "churn", "headcount",
  "monthly burn", "runway", "net new merchants", …) — it is canonicalized downstream, so
  do not invent codes.
- `object_value`: the value **exactly as written**, including units and currency
  (`"SGD 14.2M"`, `"47"`, `"412"`, `"end of June"`). Keep the as-of date attached to the
  number it belongs to.
- `as_of`: the date this value is true *as of*, `YYYY-MM-DD`. Use the value's own date
  when the text gives one (dashboards stamp an "As of" date; tables say "Q1 2026");
  otherwise fall back to the document as_of above. Omit only if truly undated.
- `confidence`: 0.0–1.0, how clearly the span states this.
- `evidence`: the short quote from this span that supports the claim (for provenance).
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
  their full name as written; do not merge "Maria", "Daniel Tan", etc. across people.
- Skip pure chrome (navigation, boilerplate). Prefer fewer, well-grounded claims over many
  speculative ones.

## Output — STRICT JSON ONLY

Return a single JSON object and nothing else (a lone ```json fence is tolerated but not
required). It must match this shape exactly:

```
{
  "claims": [
    {"subject": "...", "subject_type": "metric", "predicate": "...", "object_value": "...",
     "as_of": "YYYY-MM-DD", "confidence": 0.0, "evidence": "...", "hypothetical": false}
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
