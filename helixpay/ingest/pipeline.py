"""The ingestion pipeline: discover → load → embed → add_chunks → extract → resolve →
canonicalize → persist claims/links → detect contradictions. Idempotent end-to-end.

Seams are injectable (``discover``, ``embedder``, ``extractor``, ``already_ingested``) so
the pipeline is fully unit-testable without Agent 1's loaders, a database, or API keys. In
production those default to the real Voyage/Anthropic clients and Agent 1's
``loaders.discover_all``.

Ontology invariants enforced here (CLAUDE.md §7):
* predicates canonicalize via ``Repository.canonical_predicate`` **before** ``add_claim``;
* conflicting claims **coexist** — contradiction detection writes rows, never collapses;
* a changed file (new ``content_hash``) **supersedes** the same source's older claims via
  ``supersede_claim`` (sets ``valid_to``), never deletes; cross-source disagreement is left
  to contradiction detection;
* claims are value-claims (``object_value`` set); entity relations go through ``add_link``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional, Protocol

from helixpay.contracts import Chunk, Claim, Document, Repository, SourceConnector
from helixpay.ingest.assemble import build_claim, build_link, should_supersede
from helixpay.ingest.contradict import detect
from helixpay.ingest.embed import VoyageEmbedder
from helixpay.ingest.extract.extractor import ChunkContext, ChunkExtractor
from helixpay.ingest.extract.ledger import LossLedger
from helixpay.ingest.extract.schemas import ClaimOut
from helixpay.ingest.repair import is_known_metric, repair_metric_subject
from helixpay.ingest.resolve import context_from_source_uri, resolve_mention

log = logging.getLogger("helixpay.ingest.pipeline")

Discover = Callable[[str], Iterable[tuple[SourceConnector, str]]]

# The corpus's primary entity (the company every ownerless metric belongs to). It is
# resolved + seed-validated at run start (``_resolve_primary_entity``) before it is used to
# repair any claim, so a roster rename disables the metric-subject repair with a loud warning
# rather than silently re-minting a duplicate. Single-company corpus assumption (CLAUDE.md §7).
_PRIMARY_ENTITY_NAME = "HelixPay"

# A claim-repair callable: ``ClaimOut -> ClaimOut``. Built once per run.
ClaimRepair = Callable[[ClaimOut], ClaimOut]


def _resolve_primary_entity(repo: Repository) -> Optional[str]:
    """Resolve + seed-validate the corpus primary entity once per run.

    Returns its canonical name when ``_PRIMARY_ENTITY_NAME`` resolves to a **seeded** roster
    entity; otherwise logs a warning and returns ``None`` (metric-subject repair is then
    disabled — never silently re-minting a duplicate on a roster rename). HIGH-3.
    """
    try:
        ent = repo.resolve_entity(_PRIMARY_ENTITY_NAME, "other", None)
    except Exception as exc:  # noqa: BLE001 — a resolution failure must not abort ingest
        # Log the exception TYPE only — a DB error message can embed a connection string (§7).
        log.warning("primary-entity resolve failed; metric-subject repair disabled", extra={"error_type": type(exc).__name__})
        return None
    if ent is None or ent.id is None or not getattr(ent, "seeded", False):
        log.warning(
            "primary entity not a seeded roster entity; metric-subject repair disabled",
            extra={"primary_entity": _PRIMARY_ENTITY_NAME},
        )
        return None
    return ent.canonical_name


def _build_claim_repair(repo: Repository) -> ClaimRepair:
    """Bind the Layer-0 repair to the seed-validated primary entity, or identity when disabled."""
    primary = _resolve_primary_entity(repo)
    if primary is None:
        return lambda co: co
    return lambda co: repair_metric_subject(co, primary_entity=primary, known_metric=is_known_metric)


@dataclass
class IngestReport:
    documents: int = 0
    chunks: int = 0
    claims: int = 0
    links: int = 0
    contradictions: int = 0
    skipped_documents: int = 0
    dropped_mentions: int = 0
    touched_groups: set[tuple[int, str]] = field(default_factory=set)
    ledger: Optional[LossLedger] = None


class _Embedder(Protocol):  # structural seam for typing/injection
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class _Extractor(Protocol):
    def extract(self, chunk: Chunk, ctx: ChunkContext): ...


def _default_discover(root: str) -> Iterable[tuple[SourceConnector, str]]:
    import importlib  # noqa: PLC0415

    try:
        loaders = importlib.import_module("helixpay.ingest.loaders")  # Agent 1's registry
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised at integration, not unit
        raise RuntimeError(
            "helixpay.ingest.loaders.discover_all is unavailable — the loaders slice "
            "(Agent 1 / SP_002) must be merged, or pass an explicit discover= callable."
        ) from exc
    return loaders.discover_all(root)


def run(
    root: str = "data",
    repo: Optional[Repository] = None,
    *,
    discover: Optional[Discover] = None,
    embedder: Optional[_Embedder] = None,
    extractor: Optional[_Extractor] = None,
    already_ingested: Optional[Callable[[str], bool]] = None,
    roster_hint: Optional[str] = None,
) -> IngestReport:
    """Ingest everything under ``root`` into the ontology. Returns an :class:`IngestReport`.

    ``roster_hint`` is an optional compact listing of the seeded roster (``"Name (type)"``
    per line) injected into the extraction prompt so the model spells mentions canonically.
    It is caller-supplied because the frozen ``Repository`` exposes no entity-listing method;
    when omitted, resolution still enforces the roster downstream (roster-first), so this is
    a precision aid, not a correctness dependency.
    """
    if repo is None:
        from helixpay.db.repository import PostgresRepository  # noqa: PLC0415 — lazy (no DB at import)

        repo = PostgresRepository.from_url()
    discover_fn: Discover = discover or _default_discover
    emb: _Embedder = embedder or VoyageEmbedder()
    if extractor is None:
        from helixpay.ingest.extract.llm import AnthropicClient  # noqa: PLC0415

        # production default: one gleaning pass for recall (off in unit tests, which inject
        # their own extractor)
        ext: _Extractor = ChunkExtractor(AnthropicClient(), glean_passes=1)
    else:
        ext = extractor

    report = IngestReport()
    seen_hashes: set[str] = set()
    repair_claim = _build_claim_repair(repo)

    for connector, path in discover_fn(root):
        doc, chunks = connector.load(path)
        if doc.content_hash in seen_hashes:
            continue  # within-run de-dup of the same content
        seen_hashes.add(doc.content_hash)

        if already_ingested is not None and already_ingested(doc.content_hash):
            report.skipped_documents += 1
            log.info("skip unchanged document", extra={"source_uri": doc.source_uri})
            continue

        doc_id = repo.upsert_document(doc)
        report.documents += 1
        _ingest_document(repo, doc, doc_id, chunks, emb, ext, report, roster_hint or "", repair_claim)

    # contradiction sweep over every (subject, predicate) we touched this run
    for subject_id, predicate in report.touched_groups:
        report.contradictions += detect(repo, subject_id, predicate)

    # attach the extraction loss ledger (guarded: stub extractors in unit tests may not
    # have a .ledger attribute, so getattr keeps test_pipeline.py green without edits)
    ledger = getattr(ext, "ledger", None)
    report.ledger = ledger
    if ledger is not None:
        log.info("extraction loss ledger", extra={"ledger": ledger.summary()})

    log.info(
        "ingest complete",
        extra={
            "documents": report.documents,
            "chunks": report.chunks,
            "claims": report.claims,
            "links": report.links,
            "contradictions": report.contradictions,
            "skipped": report.skipped_documents,
        },
    )
    return report


def _ingest_document(
    repo: Repository,
    doc: Document,
    doc_id: int,
    chunks: list[Chunk],
    embedder: _Embedder,
    extractor: _Extractor,
    report: IngestReport,
    roster_hint: str,
    repair_claim: ClaimRepair,
) -> None:
    if not chunks:
        return
    chunks = [c.model_copy(update={"document_id": doc_id}) for c in chunks]
    embeddings = embedder.embed([c.text for c in chunks])
    chunk_ids = repo.add_chunks(chunks, embeddings)
    report.chunks += len(chunks)

    ctx = context_from_source_uri(doc.source_uri, doc.author)
    doc_as_of = doc.as_of.isoformat() if doc.as_of else None

    for chunk, chunk_id in zip(chunks, chunk_ids):
        result = extractor.extract(
            chunk,
            ChunkContext(
                source_type=doc.source_type,
                source_uri=doc.source_uri,
                as_of=doc_as_of,
                roster_hint=roster_hint,
            ),
        )
        for claim_out in result.claims:
            # Layer 0 (SP_019): re-attribute a known-company-metric-as-subject to the document's
            # primary entity BEFORE resolution, so the value resolves as the company's metric.
            claim_out = repair_claim(claim_out)
            subject_id = resolve_mention(
                repo, claim_out.subject, entity_type=claim_out.subject_type, context=ctx
            )
            if subject_id is None:
                report.dropped_mentions += 1
                continue
            predicate = repo.canonical_predicate(claim_out.predicate)
            claim = build_claim(
                claim_out,
                subject_id=subject_id,
                predicate=predicate,
                chunk_id=chunk_id,
                document_id=doc_id,
                doc_as_of=doc.as_of,
            )
            new_id = repo.add_claim(claim)
            report.claims += 1
            report.touched_groups.add((subject_id, predicate))
            _maybe_supersede(repo, subject_id, predicate, claim, new_id, doc.source_uri)

        for rel in result.relations:
            from_id = resolve_mention(repo, rel.from_entity, context=ctx)
            to_id = resolve_mention(repo, rel.to_entity, context=ctx)
            if from_id is None or to_id is None:
                report.dropped_mentions += 1
                continue
            link = build_link(rel, from_id=from_id, to_id=to_id, chunk_id=chunk_id, doc_as_of=doc.as_of)
            if link is None:
                # a self-loop (e.g. two surface forms collapsing to one entity) would
                # corrupt the org graph and risk recursive-CTE cycles — drop it.
                log.warning("skip self-loop relation", extra={"entity_id": from_id, "link_type": rel.link_type})
                continue
            repo.add_link(link)
            report.links += 1


def _maybe_supersede(
    repo: Repository,
    subject_id: int,
    predicate: str,
    new_claim: Claim,
    new_id: int,
    source_uri: str,
) -> None:
    """Same-source temporal supersession: when this newer claim restates an older one from
    the *same file* with a different value, set the old claim's ``valid_to``/``superseded_by``
    (never delete). Cross-source disagreement is intentionally left to contradiction
    detection, so a real contradiction is never collapsed.

    The decision rule is pure (:func:`assemble.should_supersede`); this function keeps only
    the Repository I/O — fetching the (subject, predicate) group, resolving each candidate's
    source uri, and applying the supersession write."""
    if new_claim.as_of is None:
        return  # supersede_claim requires a concrete valid_to date; nothing to scan
    for existing in repo.get_claims(subject_id, predicate):
        if existing.id is None or existing.id == new_id or existing.superseded_by is not None:
            continue  # skip the just-added claim and already-closed rows
        cites = repo.get_sources([existing.id])
        prior_uri = cites[0].source_uri if cites else None
        if should_supersede(existing, new_claim, prior_uri=prior_uri, source_uri=source_uri):
            repo.supersede_claim(existing.id, new_id, valid_to=new_claim.as_of)
            log.info(
                "superseded same-source claim",
                extra={"old": existing.id, "new": new_id, "source_uri": source_uri},
            )


__all__ = ["run", "IngestReport"]
