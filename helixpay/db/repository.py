"""PostgresRepository — the one implementation of the Repository Protocol.

All raw SQL lives here. Writes are idempotent so ingestion and seeding can re-run:
documents on ``content_hash``, entities on ``(canonical_name, entity_type)``, claims
on their natural key, links/aliases/contradictions on their unique constraints.

The instance holds (but does not own) a psycopg connection and commits after each
write, so callers get insert-or-return-existing semantics without managing
transactions. ``from_url`` is a convenience constructor for tooling and tests.
"""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Any, Optional

import psycopg
from psycopg.types.json import Json

from helixpay.contracts import (
    Chunk,
    Citation,
    Claim,
    Contradiction,
    Document,
    Entity,
    Link,
    OrgNode,
)
from helixpay.db.connection import DictConnection, connect


# A leading reporting-period qualifier on a predicate ("Q1 2026 revenue", "FY2026 ebitda").
# The period is redundant with the claim's ``as_of``; stripping it lets the period-qualified
# predicate the extractor emits canonicalize onto the bare metric key. (The pure-path mirror
# in ``helixpay.seed.metric_vocab`` is SP_010's to add; kept here in the db layer so
# ``canonical_predicate`` — the path the pipeline and eval actually use — works on its own.)
_PERIOD_TOKEN_RE = re.compile(r"^(?:q[1-4]|h[12]|fy|20\d{2})\b[\s\-/]*", re.IGNORECASE)


def _strip_period_qualifier(s: str) -> str:
    out = s.strip()
    while True:
        m = _PERIOD_TOKEN_RE.match(out)
        if not m or m.end() == 0:
            break
        out = out[m.end() :].strip()
    return out


def _vector_literal(vec: list[float]) -> str:
    """pgvector text literal: [0.1,0.2,...]. Rejects non-finite values early so a bad
    embedding fails as a clean ValueError, not an opaque server-side error."""
    parts: list[str] = []
    for x in vec:
        f = float(x)
        if not math.isfinite(f):
            raise ValueError("embedding contains a non-finite value (nan/inf)")
        parts.append(repr(f))
    return "[" + ",".join(parts) + "]"


def _entity_from_row(row: dict[str, Any]) -> Entity:
    return Entity(
        id=row["id"],
        canonical_name=row["canonical_name"],
        entity_type=row["entity_type"],
        attributes=row.get("attributes") or {},
        seeded=row.get("seeded", False),
    )


def _claim_from_row(row: dict[str, Any]) -> Claim:
    return Claim.model_validate({k: row.get(k) for k in Claim.model_fields})


def _link_from_row(row: dict[str, Any]) -> Link:
    return Link.model_validate({k: row.get(k) for k in Link.model_fields})


def _contradiction_from_row(row: dict[str, Any]) -> Contradiction:
    return Contradiction.model_validate({k: row.get(k) for k in Contradiction.model_fields})


def _chunk_from_row(row: dict[str, Any]) -> Chunk:
    return Chunk(id=row["id"], document_id=row.get("document_id"), ordinal=row.get("ordinal", 0), text=row["text"])


def _document_from_row(row: dict[str, Any]) -> Document:
    return Document.model_validate({k: row.get(k) for k in Document.model_fields})


_SNIPPET_MAX = 200


def _truncate_snippet(snippet: Optional[str]) -> Optional[str]:
    """Clip a citation snippet to a fixed length with an ellipsis (shared by every
    *_sources read so the truncation rule lives in one place)."""
    if snippet and len(snippet) > _SNIPPET_MAX:
        return snippet[:_SNIPPET_MAX] + "…"
    return snippet


class PostgresRepository:
    """Concrete Repository (satisfies helixpay.contracts.Repository)."""

    def __init__(self, conn: DictConnection) -> None:
        self.conn = conn

    @classmethod
    def from_url(cls, url: Optional[str] = None) -> "PostgresRepository":
        return cls(connect(url))

    # ------------------------------------------------------------------ #
    # documents & chunks
    # ------------------------------------------------------------------ #
    def upsert_document(self, doc: Document) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO documents (source_uri, source_type, title, author, lang, as_of, content_hash, raw_text)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (content_hash) DO NOTHING
                RETURNING id
                """,
                (doc.source_uri, doc.source_type, doc.title, doc.author, doc.lang, doc.as_of, doc.content_hash, doc.raw_text),
            )
            row = cur.fetchone()
            if row is None:  # already present — idempotent no-op
                cur.execute("SELECT id FROM documents WHERE content_hash = %s", (doc.content_hash,))
                row = cur.fetchone()
            assert row is not None  # the hash exists either way
            self.conn.commit()
            return int(row["id"])

    def add_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]) -> list[int]:
        if len(chunks) != len(embeddings):
            raise ValueError("add_chunks: chunks and embeddings length mismatch")
        ids: list[int] = []
        with self.conn.cursor() as cur:
            for chunk, emb in zip(chunks, embeddings):
                emb_lit = _vector_literal(emb) if emb is not None else None
                cur.execute(
                    """
                    INSERT INTO chunks (document_id, ordinal, text, embedding)
                    VALUES (%s,%s,%s,%s::vector)
                    ON CONFLICT (document_id, ordinal) DO NOTHING
                    RETURNING id
                    """,
                    (chunk.document_id, chunk.ordinal, chunk.text, emb_lit),
                )
                row = cur.fetchone()
                if row is None:  # chunk already present — idempotent re-ingest
                    cur.execute(
                        "SELECT id FROM chunks WHERE document_id IS NOT DISTINCT FROM %s AND ordinal = %s",
                        (chunk.document_id, chunk.ordinal),
                    )
                    row = cur.fetchone()
                assert row is not None
                ids.append(int(row["id"]))
            self.conn.commit()
        return ids

    # ------------------------------------------------------------------ #
    # entities & aliases
    # ------------------------------------------------------------------ #
    def upsert_entity(self, e: Entity) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO entities (canonical_name, entity_type, attributes, seeded)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT (canonical_name, entity_type)
                DO UPDATE SET attributes = entities.attributes || EXCLUDED.attributes,
                              seeded = entities.seeded OR EXCLUDED.seeded
                RETURNING id
                """,
                (e.canonical_name, e.entity_type, Json(e.attributes), e.seeded),
            )
            row = cur.fetchone()
            assert row is not None
            self.conn.commit()
            return int(row["id"])

    def add_alias(self, entity_id: int, alias: str, source_chunk_id: Optional[int] = None) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO entity_aliases (entity_id, alias, source_chunk_id)
                VALUES (%s,%s,%s)
                ON CONFLICT (entity_id, alias) DO NOTHING
                """,
                (entity_id, alias, source_chunk_id),
            )
            self.conn.commit()

    def resolve_entity(
        self,
        name: str,
        entity_type: Optional[str] = None,
        context: Optional[dict] = None,
    ) -> Optional[Entity]:
        name_l = name.strip().lower()
        candidates = self._entities_by_canonical(name_l, entity_type)
        if not candidates:
            candidates = self._entities_by_alias(name_l, entity_type)
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        # Roster-first disambiguation (CLAUDE.md §7: "matches the seeded roster first"): a
        # seeded entity outranks a minted same-name dupe — e.g. the seeded company
        # ``other|HelixPay`` vs a ``metric|HelixPay`` the extractor minted by guessing a
        # different entity_type. Restrict to seeded candidates when any exist. This does NOT
        # weaken the two-Marias / two-Tans trap: those are *two seeded* people, so the
        # restriction keeps both and context still separates them below (and an all-minted
        # ambiguity, e.g. two dupes of an unseeded name, stays ambiguous → None).
        seeded = [c for c in candidates if c.seeded]
        if seeded:
            candidates = seeded
            if len(candidates) == 1:
                return candidates[0]
        # Ambiguous among same-rank candidates — only a resolving context may break the tie.
        if context:
            filtered = self._filter_by_context(candidates, context)
            if len(filtered) == 1:
                return filtered[0]
        return None

    def _entities_by_canonical(self, name_l: str, entity_type: Optional[str]) -> list[Entity]:
        sql = "SELECT * FROM entities WHERE lower(canonical_name) = %s"
        params: list[Any] = [name_l]
        if entity_type:
            sql += " AND entity_type = %s"
            params.append(entity_type)
        sql += " ORDER BY seeded DESC, id ASC"
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return [_entity_from_row(r) for r in cur.fetchall()]

    def _entities_by_alias(self, name_l: str, entity_type: Optional[str]) -> list[Entity]:
        sql = (
            "SELECT e.* FROM entities e JOIN entity_aliases a ON a.entity_id = e.id "
            "WHERE lower(a.alias) = %s"
        )
        params: list[Any] = [name_l]
        if entity_type:
            sql += " AND e.entity_type = %s"
            params.append(entity_type)
        sql += " ORDER BY e.seeded DESC, e.id ASC"
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return [_entity_from_row(r) for r in cur.fetchall()]

    @staticmethod
    def _filter_by_context(candidates: list[Entity], context: dict) -> list[Entity]:
        """Keep candidates whose attributes are consistent with every context hint
        they carry a value for. A hint the entity has no value for is ignored."""
        kept: list[Entity] = []
        for ent in candidates:
            ok = True
            for key, val in context.items():
                attr = ent.attributes.get(key)
                if attr is None or val is None:
                    continue
                if str(val).lower() not in str(attr).lower() and str(attr).lower() not in str(val).lower():
                    ok = False
                    break
            if ok:
                kept.append(ent)
        return kept

    # ------------------------------------------------------------------ #
    # claims, links, contradictions
    # ------------------------------------------------------------------ #
    def add_claim(self, c: Claim) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                # Provenance-v2 columns (evidence/char_start/char_end) are appended to the
                # INSERT but are NOT in the ON CONFLICT target: the natural key is unchanged,
                # so a re-extraction of the same fact dedupes and keeps the first span.
                """
                INSERT INTO claims
                    (subject_entity_id, predicate, object_value, object_entity_id, as_of,
                     confidence, valid_from, valid_to, superseded_by, source_chunk_id, document_id,
                     evidence, char_start, char_end)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (COALESCE(subject_entity_id, -1), predicate, COALESCE(object_value, ''), COALESCE(source_chunk_id, -1))
                DO NOTHING
                RETURNING id
                """,
                (c.subject_entity_id, c.predicate, c.object_value, c.object_entity_id, c.as_of,
                 c.confidence, c.valid_from, c.valid_to, c.superseded_by, c.source_chunk_id, c.document_id,
                 c.evidence, c.char_start, c.char_end),
            )
            row = cur.fetchone()
            if row is None:  # natural-key duplicate — return the existing id
                cur.execute(
                    """
                    SELECT id FROM claims
                    WHERE subject_entity_id IS NOT DISTINCT FROM %s AND predicate = %s
                      AND COALESCE(object_value,'') = COALESCE(%s,'')
                      AND COALESCE(source_chunk_id,-1) = COALESCE(%s,-1)
                    LIMIT 1
                    """,
                    (c.subject_entity_id, c.predicate, c.object_value, c.source_chunk_id),
                )
                row = cur.fetchone()
            assert row is not None
            self.conn.commit()
            return int(row["id"])

    def supersede_claim(self, old_id: int, new_id: int, valid_to: date) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE claims SET superseded_by = %s, valid_to = %s WHERE id = %s",
                (new_id, valid_to, old_id),
            )
            self.conn.commit()

    def add_link(self, link: Link) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                # document_id is appended to the INSERT but stays out of the natural key
                # (the ON CONFLICT target is byte-identical to links_natural_key), so
                # re-ingesting the same edge dedupes and keeps the first document_id.
                """
                INSERT INTO links (from_entity_id, to_entity_id, link_type, as_of, valid_to, confidence, source_chunk_id, document_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (from_entity_id, to_entity_id, link_type, COALESCE(as_of, '0001-01-01')) DO NOTHING
                """,
                (link.from_entity_id, link.to_entity_id, link.link_type, link.as_of, link.valid_to, link.confidence, link.source_chunk_id, link.document_id),
            )
            self.conn.commit()

    def add_contradiction(self, c: Contradiction) -> None:
        # Normalize each pair so (a,b) and (b,a) dedupe to one row (review HIGH-4). The
        # claim pair dedupes via the table UNIQUE(claim_a_id, claim_b_id); the link pair
        # (SP_009) via the partial unique index contradictions_link_pair — both rely on
        # the inserted ids being order-normalized here.
        a, b = c.claim_a_id, c.claim_b_id
        if a is not None and b is not None and a > b:
            a, b = b, a
        la, lb = c.link_a_id, c.link_b_id
        if la is not None and lb is not None and la > lb:
            la, lb = lb, la
        with self.conn.cursor() as cur:
            cur.execute(
                # Bare ON CONFLICT DO NOTHING (no target) so a conflict on EITHER unique
                # constraint is an idempotent no-op: the claim-pair UNIQUE(claim_a_id,
                # claim_b_id) and the link-pair partial index contradictions_link_pair.
                # Naming only the claim columns would let a duplicate link pair raise.
                """
                INSERT INTO contradictions (subject_entity_id, predicate, claim_a_id, claim_b_id, kind, note, link_a_id, link_b_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING
                """,
                (c.subject_entity_id, c.predicate, a, b, c.kind, c.note, la, lb),
            )
            self.conn.commit()

    def upsert_metric(self, canonical_key: str, display_name: str, aliases: list[str]) -> None:
        """Seed/refresh one metric_vocab row (gate-only; not on the Protocol)."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO metric_vocab (canonical_key, display_name, aliases)
                VALUES (%s,%s,%s)
                ON CONFLICT (canonical_key) DO UPDATE SET display_name = EXCLUDED.display_name,
                                                          aliases = EXCLUDED.aliases
                """,
                (canonical_key, display_name, aliases),
            )
            self.conn.commit()

    def canonical_predicate(self, raw: str) -> str:
        raw_l = raw.strip().lower()
        key = self._lookup_predicate(raw_l)
        if key is not None:
            return key
        # SP_015 fix #2: the extractor emits period-qualified predicates ("Q1 2026 revenue")
        # whose period duplicates the claim's as_of and so never matches a bare alias. Strip
        # the leading quarter/half/FY/year qualifier and retry, so "Q1 2026 revenue" lands on
        # "revenue" (and the planted same-quarter revenue contradiction can actually pair).
        # A distinct suffix ("Q1 2026 revenue vs plan" → "revenue vs plan") still stays its
        # own predicate — only an exact post-strip alias hit canonicalizes.
        stripped = _strip_period_qualifier(raw_l)
        if stripped and stripped != raw_l:
            key = self._lookup_predicate(stripped)
            if key is not None:
                return key
        return raw  # unknown → unchanged, never raises

    def _lookup_predicate(self, raw_l: str) -> Optional[str]:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT canonical_key FROM metric_vocab
                WHERE lower(canonical_key) = %s
                   OR EXISTS (SELECT 1 FROM unnest(aliases) a WHERE lower(a) = %s)
                LIMIT 1
                """,
                (raw_l, raw_l),
            )
            row = cur.fetchone()
        return row["canonical_key"] if row else None

    # ------------------------------------------------------------------ #
    # retrieval
    # ------------------------------------------------------------------ #
    def search_semantic(self, qvec: list[float], k: int) -> list[tuple[Chunk, float]]:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, document_id, ordinal, text, 1 - (embedding <=> %s::vector) AS score
                FROM chunks
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (_vector_literal(qvec), _vector_literal(qvec), k),
            )
            return [(_chunk_from_row(r), float(r["score"])) for r in cur.fetchall()]

    def search_lexical(self, q: str, k: int) -> list[tuple[Chunk, float]]:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, document_id, ordinal, text,
                       ts_rank(tsv, plainto_tsquery('english', %s)) AS score
                FROM chunks
                WHERE tsv @@ plainto_tsquery('english', %s)
                ORDER BY score DESC
                LIMIT %s
                """,
                (q, q, k),
            )
            return [(_chunk_from_row(r), float(r["score"])) for r in cur.fetchall()]

    # ------------------------------------------------------------------ #
    # graph / structured reads
    # ------------------------------------------------------------------ #
    def get_claims(self, subject_id: int, predicate: Optional[str] = None) -> list[Claim]:
        sql = "SELECT * FROM claims WHERE subject_entity_id = %s"
        params: list[Any] = [subject_id]
        if predicate:
            sql += " AND predicate = %s"
            params.append(predicate)
        sql += " ORDER BY as_of DESC NULLS LAST, id ASC"
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return [_claim_from_row(r) for r in cur.fetchall()]

    def get_links(
        self,
        link_type: Optional[str] = None,
        from_entity_id: Optional[int] = None,
    ) -> list[Link]:
        clauses: list[str] = []
        params: list[Any] = []
        if link_type:
            clauses.append("link_type = %s")
            params.append(link_type)
        if from_entity_id is not None:
            clauses.append("from_entity_id = %s")
            params.append(from_entity_id)
        sql = "SELECT * FROM links"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id ASC"
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return [_link_from_row(r) for r in cur.fetchall()]

    def get_org_subtree(self, root_id: Optional[int] = None, as_of: Optional[date] = None) -> OrgNode:
        if root_id is None:
            root_id = self._org_root_id(as_of)
        if root_id is None:
            return OrgNode(entity_id=0, name="", children=[], dotted_reports=[])
        rows = self._reports_to_edges(as_of)
        children_by_parent: dict[int, list[int]] = {}
        for frm, to in rows:
            children_by_parent.setdefault(to, []).append(frm)
        dotted = self._dotted_reports_map(as_of)
        names = self._entity_names()
        visited: set[int] = set()  # global — a node is emitted once even with multiple parents/cycles

        def build(node_id: int) -> OrgNode:
            visited.add(node_id)
            node: OrgNode = {
                "entity_id": node_id,
                "name": names.get(node_id, ""),
                "children": [],
                "dotted_reports": dotted.get(node_id, []),
            }
            for child in children_by_parent.get(node_id, []):
                if child in visited:
                    continue
                node["children"].append(build(child))
            return node

        return build(root_id)

    def _org_root_id(self, as_of: Optional[date] = None) -> Optional[int]:
        """Top of the org: a manager (has incoming reports_to) with no outgoing one,
        evaluated over the reporting lines valid at ``as_of``."""
        date_filter = ""
        params: list[Any] = []
        if as_of is not None:
            date_filter = " AND (as_of IS NULL OR as_of <= %s) AND (valid_to IS NULL OR valid_to > %s)"
            params = [as_of, as_of, as_of, as_of]
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT to_entity_id AS id FROM links
                WHERE link_type = 'reports_to'{date_filter}
                  AND to_entity_id NOT IN (
                      SELECT from_entity_id FROM links WHERE link_type = 'reports_to'{date_filter}
                  )
                ORDER BY id ASC
                LIMIT 1
                """,
                params,
            )
            row = cur.fetchone()
            return int(row["id"]) if row else None

    def _reports_to_edges(self, as_of: Optional[date]) -> list[tuple[int, int]]:
        sql = "SELECT from_entity_id, to_entity_id FROM links WHERE link_type = 'reports_to'"
        params: list[Any] = []
        if as_of is not None:
            sql += " AND (as_of IS NULL OR as_of <= %s) AND (valid_to IS NULL OR valid_to > %s)"
            params += [as_of, as_of]
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return [(int(r["from_entity_id"]), int(r["to_entity_id"])) for r in cur.fetchall()]

    def _dotted_reports_map(self, as_of: Optional[date]) -> dict[int, list[int]]:
        sql = "SELECT from_entity_id, to_entity_id FROM links WHERE link_type = 'dotted_line_to'"
        params: list[Any] = []
        if as_of is not None:
            sql += " AND (as_of IS NULL OR as_of <= %s) AND (valid_to IS NULL OR valid_to > %s)"
            params += [as_of, as_of]
        out: dict[int, list[int]] = {}
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            for r in cur.fetchall():
                out.setdefault(int(r["to_entity_id"]), []).append(int(r["from_entity_id"]))
        return out

    def _entity_names(self) -> dict[int, str]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT id, canonical_name FROM entities")
            return {int(r["id"]): r["canonical_name"] for r in cur.fetchall()}

    def get_contradictions(self, subject_id: Optional[int] = None) -> list[Contradiction]:
        sql = "SELECT * FROM contradictions"
        params: list[Any] = []
        if subject_id is not None:
            sql += " WHERE subject_entity_id = %s"
            params.append(subject_id)
        sql += " ORDER BY id ASC"
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return [_contradiction_from_row(r) for r in cur.fetchall()]

    def get_sources(self, claim_ids: list[int]) -> list[Citation]:
        if not claim_ids:
            return []
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT cl.id AS claim_id,
                       d.source_uri AS source_uri,
                       COALESCE(cl.as_of, d.as_of) AS as_of,
                       ch.text AS snippet,
                       cl.source_chunk_id AS chunk_id
                FROM claims cl
                LEFT JOIN chunks ch ON ch.id = cl.source_chunk_id
                LEFT JOIN documents d ON d.id = COALESCE(cl.document_id, ch.document_id)
                WHERE cl.id = ANY(%s) AND (d.id IS NOT NULL OR ch.id IS NOT NULL)
                ORDER BY cl.id ASC
                """,
                (claim_ids,),
            )
            out: list[Citation] = []
            for r in cur.fetchall():
                out.append(
                    Citation(
                        source_uri=r.get("source_uri") or "",
                        as_of=r.get("as_of"),
                        snippet=_truncate_snippet(r.get("snippet")),
                        claim_id=r.get("claim_id"),
                        chunk_id=r.get("chunk_id"),
                    )
                )
            return out

    # ------------------------------------------------------------------ #
    # provenance v2 (SP_009)
    # ------------------------------------------------------------------ #
    def get_link_sources(self, link_ids: list[int]) -> list[Citation]:
        """Provenance for link rows, each anchored by ``link_id``. ``snippet`` is the
        source-chunk text prefix (links carry no evidence span); ``as_of`` prefers the
        link's own date, else the document's. Links with no resolvable source are omitted."""
        if not link_ids:
            return []
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT l.id AS link_id,
                       d.source_uri AS source_uri,
                       COALESCE(l.as_of, d.as_of) AS as_of,
                       ch.text AS snippet,
                       l.source_chunk_id AS chunk_id
                FROM links l
                LEFT JOIN chunks ch ON ch.id = l.source_chunk_id
                LEFT JOIN documents d ON d.id = COALESCE(l.document_id, ch.document_id)
                WHERE l.id = ANY(%s) AND d.id IS NOT NULL
                ORDER BY l.id ASC
                """,
                (link_ids,),
            )
            return [
                Citation(
                    source_uri=r.get("source_uri") or "",
                    as_of=r.get("as_of"),
                    snippet=_truncate_snippet(r.get("snippet")),
                    chunk_id=r.get("chunk_id"),
                    link_id=r.get("link_id"),
                )
                for r in cur.fetchall()
            ]

    def get_chunk_sources(self, chunk_ids: list[int]) -> list[Citation]:
        """One ``Citation`` per chunk (anchored by ``chunk_id``), the chunk-text prefix as
        ``snippet``. No claim join — ``claim_id`` is always ``None``. Chunks whose document
        is missing are omitted."""
        if not chunk_ids:
            return []
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT ch.id AS chunk_id,
                       d.source_uri AS source_uri,
                       d.as_of AS as_of,
                       ch.text AS snippet
                FROM chunks ch
                LEFT JOIN documents d ON d.id = ch.document_id
                WHERE ch.id = ANY(%s) AND d.id IS NOT NULL
                ORDER BY ch.id ASC
                """,
                (chunk_ids,),
            )
            return [
                Citation(
                    source_uri=r.get("source_uri") or "",
                    as_of=r.get("as_of"),
                    snippet=_truncate_snippet(r.get("snippet")),
                    chunk_id=r.get("chunk_id"),
                )
                for r in cur.fetchall()
            ]

    # ------------------------------------------------------------------ #
    # retrieval reads for the MCP tool surface (SP_022)
    # ------------------------------------------------------------------ #
    def get_chunk(self, chunk_id: int) -> Optional[Chunk]:
        """A single chunk by id with its FULL text (backs MCP ``fetch``). ``None`` on
        miss. Unlike ``get_chunk_sources`` the text is NOT truncated."""
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT id, document_id, ordinal, text FROM chunks WHERE id = %s",
                (chunk_id,),
            )
            row = cur.fetchone()
        return _chunk_from_row(row) if row is not None else None

    def list_documents(self) -> list[Document]:
        """Full document inventory (backs MCP ``get_sources``), ordered ``as_of`` DESC
        NULLS LAST then ``id`` ASC. Returns complete ``Document`` models including
        ``raw_text`` — payload trimming is the engine/wire layer's job (SP_022)."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, source_uri, source_type, title, author, lang, as_of,
                       ingested_at, content_hash, raw_text
                FROM documents
                ORDER BY as_of DESC NULLS LAST, id ASC
                """
            )
            return [_document_from_row(r) for r in cur.fetchall()]

    def list_entities(self, entity_type: Optional[str] = None) -> list[Entity]:
        """Enumerate entities (backs MCP ``list_entities``), optionally by type. An
        unknown/empty type returns ``[]`` (never raises — mirrors ``canonical_predicate``'s
        never-raise convention). Ordered by ``entity_type`` then ``canonical_name``."""
        sql = "SELECT id, canonical_name, entity_type, attributes, seeded FROM entities"
        params: list[Any] = []
        if entity_type is not None:
            sql += " WHERE entity_type = %s"
            params.append(entity_type)
        sql += " ORDER BY entity_type ASC, canonical_name ASC"
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return [_entity_from_row(r) for r in cur.fetchall()]

    def known_content_hashes(self) -> set[str]:
        """Every ``documents.content_hash`` already stored (compute-idempotency)."""
        with self.conn.cursor() as cur:
            cur.execute("SELECT content_hash FROM documents")
            return {r["content_hash"] for r in cur.fetchall()}

    def audit_chunk_embeddings(self, source_uris: list[str]) -> dict[str, bool]:
        """SP_015 $0 proving probe: per ``source_uri``, ``True`` iff the document has at
        least one chunk and **every** chunk carries a non-null, non-zero-norm embedding.

        Read-only; the raw SQL stays in the db layer (callers get a plain ``{uri: bool}``).
        Non-zero norm is tested via the inner-product operator ``embedding <#> embedding``
        (pgvector returns the *negative* inner product, i.e. ``-||v||**2`` ≤ 0, which is
        strictly ``< 0`` exactly when the vector is non-zero) — version-safe, no ``l2_norm``
        dependency. Catches the zero-vector / misconfigured-embed failure with no API call."""
        out: dict[str, bool] = {}
        with self.conn.cursor() as cur:
            for uri in source_uris:
                cur.execute(
                    """
                    SELECT count(*) AS n,
                           count(*) FILTER (
                               WHERE ch.embedding IS NOT NULL
                                 AND (ch.embedding <#> ch.embedding) < 0
                           ) AS good
                    FROM documents d
                    JOIN chunks ch ON ch.document_id = d.id
                    WHERE d.source_uri = %s
                    """,
                    (uri,),
                )
                row = cur.fetchone()
                n = int(row["n"]) if row else 0
                good = int(row["good"]) if row else 0
                out[uri] = n > 0 and good == n
        return out


__all__ = ["PostgresRepository"]
