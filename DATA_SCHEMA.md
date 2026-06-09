---
status: living
last-reconciled: 2026-06-09
authoritative-for: [schema]
---

# Data Schema

The ontology schema lives in `helixpay/db/schema.sql` (applied by
`helixpay/db/migrate.py` onto `pgvector/pgvector:pg16`). It is a **temporal,
provenance-carrying** model: property values are *claims* (conflicting values
coexist, never collapsed), contradictions are first-class rows, and superseded
facts are kept (`valid_to` / `superseded_by`), never deleted.

## Database

- **Type**: PostgreSQL 16 + `pgvector` extension (semantic) + native FTS (lexical).
- **Connection**: `DATABASE_URL` env var only (via `helixpay/config.py`); psycopg 3.
- **Access**: exclusively through `helixpay/db/repository.py` (`PostgresRepository`).
  No raw SQL outside `helixpay/db/`.

## Tables

| Table | Purpose | Key columns / constraints |
|-------|---------|---------------------------|
| `documents` | Raw provenance, content-addressed | `content_hash` UNIQUE → ingestion idempotency; `source_type`, `as_of` |
| `chunks` | Retrievable spans | `embedding VECTOR(1024)` (HNSW); `tsv` GENERATED tsvector (GIN); `UNIQUE(document_id, ordinal)` |
| `entities` | person/team/customer/product/metric/other | `UNIQUE(canonical_name, entity_type)`; `seeded` flags roster rows |
| `entity_aliases` | Surface forms → entity | `UNIQUE(entity_id, alias)`; `lower(alias)` index |
| `metric_vocab` | Controlled predicate vocabulary | `canonical_key` PK; `aliases TEXT[]` |
| `claims` | The claim/assertion model | partial-UNIQUE natural key `(COALESCE(subject,-1), predicate, COALESCE(object_value,''), COALESCE(source_chunk_id,-1))`; temporal cols + `superseded_by` |
| `links` | Typed relations incl. org hierarchy | `link_type` ∈ `reports_to \| dotted_line_to \| owns \| member_of \| mentions`; unique index on `(from,to,type,COALESCE(as_of,…))` |
| `contradictions` | First-class conflict objects | `UNIQUE(claim_a_id, claim_b_id)` (pair normalized min,max); `kind` ∈ value_conflict\|temporal\|source_disagreement |

## Relationships

- `chunks.document_id → documents.id` (cascade)
- `entity_aliases.entity_id → entities.id` (cascade); `…source_chunk_id → chunks.id`
- `claims.subject_entity_id / object_entity_id → entities.id`;
  `…source_chunk_id → chunks.id`; `…document_id → documents.id`;
  `…superseded_by → claims.id` (self-reference)
- `links.from_entity_id / to_entity_id → entities.id`
- `contradictions.claim_a_id / claim_b_id → claims.id`

## Invariants

- **Idempotent writes** on every natural key — re-ingest / re-seed is a no-op.
- **Never collapse conflicts** — two disagreeing claims both persist; a
  `contradictions` row pairs them.
- **Temporal** — seeded roster rows stamped `as_of = 2026-04-15` (org-chart export);
  supersession via `Repository.supersede_claim`, never delete.

## Migrations

1. Edit `helixpay/db/schema.sql` (all statements idempotent, `IF NOT EXISTS`).
2. `python -m helixpay.db.migrate` (applies statement-by-statement; needs `DATABASE_URL`).
3. Update the frozen model in `helixpay/contracts/models.py` if a shape changed.
4. Update this file + add/extend tests. No destructive migrations.

> Gotcha: a uniqueness key containing an expression (e.g. `COALESCE(...)`) must be a
> `CREATE UNIQUE INDEX`, not a table-level `UNIQUE(...)` constraint.
