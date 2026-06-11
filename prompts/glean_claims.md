# Gleaning prompt — recover claims/relations missed on the first pass

A first extraction pass already ran on the span below. MANY real claims and relations are
commonly missed on a first pass. Your job: find **only the ones that were missed** — do
**not** repeat anything already extracted, and do **not** invent anything not present in the
span.

## Source
- source_type: `{{source_type}}`
- source_uri: `{{source_uri}}`
- document as_of (fallback date for undated facts): `{{as_of}}`

## Known entities (resolve mentions toward these where they clearly match; may be empty)
{{roster_hint}}

## Already extracted (do NOT repeat these)
{{already_extracted}}

## Rules
- Same output contract and field meanings as the first pass: `claims[]` (subject,
  subject_type, predicate, **evidence** = verbatim quote, object_value, as_of, confidence,
  hypothetical) + `relations[]` (from_entity, to_entity, link_type, as_of, confidence).
- Emit ONLY claims/relations **missing** from the "Already extracted" list above.
- Same discipline: capture the as-of date with each value; copy values verbatim into
  `evidence`; flag hypotheticals/counterfactuals with `hypothetical: true`; keep people who
  share a name distinct; never collapse conflicts.
- If nothing was missed, return `{"claims": [], "relations": []}`.

## Output — STRICT JSON ONLY

Return a single JSON object (a lone ```json fence is tolerated), same shape as the first
pass:

```
{
  "claims": [
    {"subject": "...", "subject_type": "other", "predicate": "...",
     "evidence": "<verbatim quote>", "object_value": "...", "as_of": "YYYY-MM-DD",
     "confidence": 0.0, "hypothetical": false}
  ],
  "relations": [
    {"from_entity": "...", "to_entity": "...", "link_type": "reports_to",
     "as_of": "YYYY-MM-DD", "confidence": 0.0}
  ]
}
```

## The span

```
{{chunk_text}}
```
