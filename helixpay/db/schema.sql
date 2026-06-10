-- HelixPay ontology schema (spec §3, refined by the SP_001 Stage 3 review).
-- Apply with helixpay/db/migrate.py against pgvector/pgvector:pg16.
--
-- Design: a temporal, provenance-carrying ontology. Property values are *claims*
-- (conflicting values coexist, never collapsed); contradictions are first-class
-- rows; superseded facts are kept (valid_to / superseded_by), never deleted.
-- All statements are idempotent (IF NOT EXISTS) so migrate is safe to re-run.

CREATE EXTENSION IF NOT EXISTS vector;

-- --------------------------------------------------------------------------- --
-- Raw provenance, content-addressed for ingestion idempotency.
-- --------------------------------------------------------------------------- --
CREATE TABLE IF NOT EXISTS documents (
    id            BIGSERIAL PRIMARY KEY,
    source_uri    TEXT NOT NULL,
    source_type   TEXT NOT NULL,            -- md|pdf|html|image|slack|email|code
    title         TEXT,
    author        TEXT,
    lang          TEXT,
    as_of         DATE,
    ingested_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    content_hash  TEXT NOT NULL UNIQUE,     -- re-ingest of unchanged content is a no-op
    raw_text      TEXT
);

-- --------------------------------------------------------------------------- --
-- Retrievable spans. embedding is produced upstream (Voyage, 1024d); tsv is a
-- GENERATED column so callers never compute lexical vectors (review H3).
-- --------------------------------------------------------------------------- --
CREATE TABLE IF NOT EXISTS chunks (
    id           BIGSERIAL PRIMARY KEY,
    document_id  BIGINT REFERENCES documents(id) ON DELETE CASCADE,
    ordinal      INT NOT NULL DEFAULT 0,
    text         TEXT NOT NULL,
    embedding    VECTOR(1024),
    tsv          TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
    UNIQUE (document_id, ordinal)        -- re-ingesting a document is a no-op on its chunks
);
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_tsv_gin
    ON chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS chunks_document_id_idx
    ON chunks (document_id);

-- --------------------------------------------------------------------------- --
-- Entities + aliases. Seeded entities (roster) carry seeded=true and are matched
-- first by resolve_entity.
-- --------------------------------------------------------------------------- --
CREATE TABLE IF NOT EXISTS entities (
    id             BIGSERIAL PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    entity_type    TEXT NOT NULL,           -- person|team|customer|product|metric|other
    attributes     JSONB NOT NULL DEFAULT '{}',
    seeded         BOOLEAN NOT NULL DEFAULT false,
    UNIQUE (canonical_name, entity_type)
);
CREATE INDEX IF NOT EXISTS entities_type_idx ON entities (entity_type);

CREATE TABLE IF NOT EXISTS entity_aliases (
    id              BIGSERIAL PRIMARY KEY,
    entity_id       BIGINT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    alias           TEXT NOT NULL,
    source_chunk_id BIGINT REFERENCES chunks(id),
    UNIQUE (entity_id, alias)
);
CREATE INDEX IF NOT EXISTS entity_aliases_alias_idx ON entity_aliases (lower(alias));

-- --------------------------------------------------------------------------- --
-- Controlled metric vocabulary: predicates normalize onto canonical_key so that
-- "ARR" and "annual recurring revenue" are the same predicate (else contradiction
-- detection silently no-ops).
-- --------------------------------------------------------------------------- --
CREATE TABLE IF NOT EXISTS metric_vocab (
    canonical_key TEXT PRIMARY KEY,
    display_name  TEXT,
    aliases       TEXT[] NOT NULL DEFAULT '{}'
);

-- --------------------------------------------------------------------------- --
-- Claims: the claim/assertion model. Conflicting values coexist. The partial
-- UNIQUE natural key makes add_claim idempotent across re-ingest (review H1);
-- supersession sets valid_to / superseded_by, never deletes (review H2).
-- --------------------------------------------------------------------------- --
CREATE TABLE IF NOT EXISTS claims (
    id                BIGSERIAL PRIMARY KEY,
    subject_entity_id BIGINT REFERENCES entities(id),
    predicate         TEXT NOT NULL,        -- canonicalized via metric_vocab where applicable
    object_value      TEXT,
    object_entity_id  BIGINT REFERENCES entities(id),
    as_of             DATE,
    confidence        REAL,
    valid_from        DATE,
    valid_to          DATE,
    superseded_by     BIGINT REFERENCES claims(id),
    source_chunk_id   BIGINT REFERENCES chunks(id),
    document_id       BIGINT REFERENCES documents(id)
);
CREATE INDEX IF NOT EXISTS claims_subject_predicate_idx
    ON claims (subject_entity_id, predicate);
-- Natural-key idempotency: the same fact from the same chunk inserts once.
-- COALESCE so NULL object_value / source_chunk_id still dedupe deterministically.
-- COALESCE every nullable key column: NULLs are distinct in a unique index, so a
-- bare nullable column would let duplicates through (review CRITICAL-1).
CREATE UNIQUE INDEX IF NOT EXISTS claims_natural_key
    ON claims (
        COALESCE(subject_entity_id, -1),
        predicate,
        COALESCE(object_value, ''),
        COALESCE(source_chunk_id, -1)
    );

-- --------------------------------------------------------------------------- --
-- Typed relations, including org hierarchy (recursive CTE). dotted_line_to keeps
-- functional dotted-line reporting distinct from solid reports_to (review C2).
-- --------------------------------------------------------------------------- --
CREATE TABLE IF NOT EXISTS links (
    id              BIGSERIAL PRIMARY KEY,
    from_entity_id  BIGINT NOT NULL REFERENCES entities(id),
    to_entity_id    BIGINT NOT NULL REFERENCES entities(id),
    link_type       TEXT NOT NULL,          -- reports_to|dotted_line_to|owns|member_of|mentions
    as_of           DATE,
    valid_to        DATE,
    confidence      REAL,
    source_chunk_id BIGINT REFERENCES chunks(id)
);
-- Expression in the uniqueness key requires a UNIQUE INDEX (constraints can't hold COALESCE).
CREATE UNIQUE INDEX IF NOT EXISTS links_natural_key
    ON links (from_entity_id, to_entity_id, link_type, COALESCE(as_of, '0001-01-01'));
CREATE INDEX IF NOT EXISTS links_type_idx ON links (link_type);
CREATE INDEX IF NOT EXISTS links_from_idx ON links (from_entity_id);

-- --------------------------------------------------------------------------- --
-- Contradictions: first-class objects pairing two disagreeing claims.
-- --------------------------------------------------------------------------- --
CREATE TABLE IF NOT EXISTS contradictions (
    id                BIGSERIAL PRIMARY KEY,
    subject_entity_id BIGINT REFERENCES entities(id),
    predicate         TEXT,
    claim_a_id        BIGINT REFERENCES claims(id),
    claim_b_id        BIGINT REFERENCES claims(id),
    kind              TEXT,                  -- value_conflict|temporal|source_disagreement
    note              TEXT,
    detected_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (claim_a_id, claim_b_id)
);
CREATE INDEX IF NOT EXISTS contradictions_subject_idx ON contradictions (subject_entity_id);

-- --------------------------------------------------------------------------- --
-- Provenance v2 (SP_009) — additive, backward-compatible amendment. Every
-- statement is idempotent (ADD COLUMN IF NOT EXISTS / CREATE ... IF NOT EXISTS) and
-- the migrate splitter is comment-safe ONLY when comments sit on their own line above
-- the statement (never inline on the DDL line) with no DEFAULT clauses and no
-- dollar-quoted bodies. Foreign keys are declared inline on ADD COLUMN (a separate
-- ADD CONSTRAINT has no IF NOT EXISTS and would throw on re-run).
-- --------------------------------------------------------------------------- --

-- Claims carry the verbatim grounding span + its offsets into the source chunk text.
-- Non-key payload only: the claims_natural_key index above is untouched.
ALTER TABLE claims ADD COLUMN IF NOT EXISTS evidence TEXT;
ALTER TABLE claims ADD COLUMN IF NOT EXISTS char_start INT;
ALTER TABLE claims ADD COLUMN IF NOT EXISTS char_end INT;

-- Links mirror claims so relationship provenance is a direct document join.
ALTER TABLE links ADD COLUMN IF NOT EXISTS document_id BIGINT REFERENCES documents(id);

-- Contradictions can pair two links (graph conflicts), not just two claims.
ALTER TABLE contradictions ADD COLUMN IF NOT EXISTS link_a_id BIGINT REFERENCES links(id);
ALTER TABLE contradictions ADD COLUMN IF NOT EXISTS link_b_id BIGINT REFERENCES links(id);
-- Link-pair idempotency: the table-level UNIQUE (claim_a_id, claim_b_id) gives NO
-- protection for link rows (both claim ids are NULL, and NULLs are distinct in a UNIQUE
-- constraint). A partial unique index on the order-normalized link pair makes re-running
-- graph contradiction detection a no-op. LEAST/GREATEST mirror add_contradiction's sort.
CREATE UNIQUE INDEX IF NOT EXISTS contradictions_link_pair
    ON contradictions (LEAST(link_a_id, link_b_id), GREATEST(link_a_id, link_b_id))
    WHERE link_a_id IS NOT NULL AND link_b_id IS NOT NULL;
