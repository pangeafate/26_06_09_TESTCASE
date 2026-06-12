"""``HelixQueryEngine`` — the concrete ``QueryEngine`` (spec §4/§5, Agent 3).

Wires the query modules into the four-method reasoning surface Agent 4 exposes:

* ``ask`` — plan → gather (retrieval + structured + contradictions) → synthesize
  grounded-and-cited → enforce zero-uncited-claims → bundle.
* ``get_entity`` / ``get_org_chart`` / ``find_contradictions`` — structured reads.

Design stances:
* Contradictions are **always surfaced** on the bundle (present-and-empty, never
  hidden) regardless of whether synthesis cited them, and both sides are carried
  so the answer attributes each (CLAUDE.md §7).
* Every fact handed to synthesis is a governed claim or a retrieved excerpt;
  ``enforce_citations`` drops anything the model asserts without a claim citation.
* Each ``ask`` logs a structured trace (``route``, retrieved chunk ids, cited
  claim ids) for Agent 6's observability read, and stashes it on ``last_trace``.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import TYPE_CHECKING, Optional

from helixpay.contracts import AnswerBundle, Contradiction, EntityDetail, OrgNode
from helixpay.query import consensus
from helixpay.query import contradictions as contra
from helixpay.query import graph, retrieval, synthesis
from helixpay.query.clients import Embedder, Synthesizer
from helixpay.query.planner import Route
from helixpay.query.planner import route as plan_route
from helixpay.query.temporal import as_of_coverage

if TYPE_CHECKING:
    from helixpay.contracts import Claim, Entity, Link, Repository

log = logging.getLogger("helixpay.query")

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'&-]+")
_MAX_SUBJECTS = 6
_MAX_TERMS = 40  # cap repo lookups on a long question (perf guard)
_MAX_LINKS = 12  # cap relationship facts pulled into grounding (perf/noise guard)
_MAX_CLAIM_FACTS = 50  # cap claims fed to grounding/consensus (perf/noise guard)
_SNIPPET_MAX = 200  # search-result snippet clip (fetch returns full text)


# fetch miss payload: a stable metadata key set (None-valued) so a consumer can read
# metadata["document_id"]/["source_as_of"] without first branching on `found` (review M2).
_MISS_META = {"source_as_of": None, "document_id": None, "ordinal": None, "found": False}


def _iso(d: Optional[date]) -> Optional[str]:
    """``date`` → ISO string, ``None`` → ``None``. The single date guard for the retrieval/
    graph surfaces — never a bare ``.isoformat()`` (claims/links/documents legitimately carry
    ``as_of=None``)."""
    return d.isoformat() if d is not None else None


def _snippet(text: str) -> str:
    """Clip a chunk to a short ``search`` snippet. Defined HERE in the query layer so the
    engine never imports ``db.repository._truncate_snippet`` — that would make the
    query/capabilities layer depend on the db/infrastructure layer (SP_022 review:
    layer-boundary). ``fetch`` returns the full, untruncated text instead."""
    return text[:_SNIPPET_MAX] + "…" if len(text) > _SNIPPET_MAX else text


class HelixQueryEngine:
    """Concrete QueryEngine over a Repository + injected Embedder/Synthesizer."""

    def __init__(
        self,
        repo: "Repository",
        embedder: Embedder,
        synthesizer: Synthesizer,
        *,
        k: int = 8,
    ) -> None:
        self.repo = repo
        self.embedder = embedder
        self.synth = synthesizer
        self.k = k
        self.last_trace: dict = {}

    # -- the QueryEngine surface ---------------------------------------- #
    def ask(self, question: str) -> AnswerBundle:
        plan = plan_route(question)

        chunks = []
        if plan.route in (Route.retrieval, Route.both):
            chunks = [
                c
                for c, _ in retrieval.hybrid_search(
                    self.repo, self.embedder, question, k=self.k
                )
            ]

        terms = self._candidate_terms(question)
        subjects: list["Entity"] = []
        # Fresh per-ask() memo (NOT an instance attribute — an engine-level cache would
        # leak a stale None/entity across requests after an ingest). Collapses redundant
        # resolve_entity lookups for case/whitespace-variant terms within this call.
        resolve_memo: dict[str, Optional["Entity"]] = {}
        if plan.route in (Route.structured, Route.both):
            subjects = self._resolve_subjects(terms, resolve_memo)
        subject_ids = [s.id for s in subjects if s.id is not None]

        # contradictions are first-class — gather (by subject AND by canonicalized
        # topic term) and ALWAYS surface them, even if synthesis cites none.
        relevant: list[Contradiction] = []
        if plan.wants_contradictions or subject_ids:
            relevant = contra.relevant(self.repo, subject_ids=subject_ids, topics=terms)

        claim_facts = self._gather_claim_facts(subject_ids, relevant)
        claims_by_id = {c.id: c for c in claim_facts if c.id is not None}

        # Relationship facts (Feature 2) + the link sides of any link-contradiction (so
        # both sides of a graph conflict are citeable, not just surfaced).
        links = self._gather_links(subject_ids, relevant)
        name_map = {s.id: s.canonical_name for s in subjects if s.id is not None}

        # Type each surfaced conflict (Feature 4) for the DRAGged-style prompt hint.
        typed = [(c, contra.label_for(c, claims_by_id)) for c in relevant]
        # Consensus/dissent rollup (Feature 3) over the candidate claims.
        groups = consensus.rollup(claim_facts, self.repo.canonical_predicate)

        facts_text, fact_index = synthesis.build_grounding(
            claim_facts, chunks, links, name_map=name_map
        )
        grounding_text = (
            facts_text
            + synthesis.render_consensus(groups, fact_index)
            + synthesis.render_contradictions(typed, fact_index)
        )
        prompt = synthesis.render_prompt(question, grounding_text)
        try:
            output = self.synth.synthesize(prompt, schema=synthesis.SYNTH_SCHEMA)
        except Exception:  # noqa: BLE001 - external model boundary: degrade, never leak the prompt
            log.warning("ask.synthesis_failed route=%s", plan.route.value)
            output = {"sentences": []}
        answer, citations, cited_ids, confidence = synthesis.enforce_citations(
            output, fact_index, self.repo
        )

        bundle = AnswerBundle(
            answer=answer,
            citations=citations,
            contradictions=relevant,
            as_of_coverage=as_of_coverage(citations),
            confidence=confidence,
        )
        self.last_trace = {
            "route": plan.route.value,
            "retrieved_chunk_ids": [c.id for c in chunks],
            "subject_ids": subject_ids,
            "cited_claim_ids": cited_ids,
            "cited_chunk_ids": [
                c.chunk_id for c in citations if c.chunk_id is not None
            ],
            "cited_link_ids": [c.link_id for c in citations if c.link_id is not None],
            "contradiction_ids": [c.id for c in relevant],
        }
        log.info("ask.trace %s", self.last_trace)
        return bundle

    def get_entity(self, name: str) -> EntityDetail:
        return graph.entity_detail(self.repo, name)

    def get_org_chart(self, as_of: Optional[date] = None) -> OrgNode:
        return graph.org_chart(self.repo, as_of=as_of)

    def find_contradictions(self, topic: Optional[str] = None) -> list[Contradiction]:
        return contra.find(self.repo, topic)

    # -- the ExposureEngine retrieval surface (SP_022) ------------------ #
    # Optional tools discovered by mcp.server._retrieval via getattr — NOT on the frozen
    # QueryEngine Protocol. They return plain JSON-friendly dicts (no model leakage).
    def search(self, query: str, k: int = 10) -> list[dict]:
        """Raw hybrid retrieval over chunks (no synthesis). Results stay in RRF rank order;
        provenance is re-aligned to each chunk BY ID (``get_chunk_sources`` returns rows in
        chunk-id order and omits chunks with a missing document join), never by zip. The
        date is the *document's* ``as_of`` (``source_as_of``) — not a per-fact reporting
        period (CLAUDE.md's as_of trap)."""
        hits = retrieval.hybrid_search(self.repo, self.embedder, query, k=k)
        cites = {
            c.chunk_id: c
            for c in self.repo.get_chunk_sources(
                [ch.id for ch, _ in hits if ch.id is not None]
            )
        }
        out: list[dict] = []
        for chunk, score in hits:
            if chunk.id is None:
                continue  # no addressable id → can't be fetched; never emit "None"
            c = cites.get(chunk.id)
            uri = c.source_uri if c else ""
            out.append(
                {
                    "id": str(chunk.id),
                    "title": uri,
                    "url": uri,
                    "snippet": _snippet(chunk.text),
                    "score": score,
                    "source_as_of": c.as_of.isoformat() if (c and c.as_of) else None,
                    "document_id": chunk.document_id,
                }
            )
        return out

    def fetch(self, id: str) -> dict:
        """Full text + provenance of a single chunk by id (the handle ``search`` minted).
        A malformed (non-int) or absent id degrades to a ``found: False`` payload — never a
        raise that 500s the tool (deliberate divergence from ``get_org_chart``: the id is an
        opaque search handle, not user-semantic input)."""
        try:
            cid = int(id)
        except (TypeError, ValueError):
            return {"id": id, "title": "", "text": "", "url": "", "metadata": _MISS_META.copy()}
        chunk = self.repo.get_chunk(cid)
        if chunk is None:
            return {"id": id, "title": "", "text": "", "url": "", "metadata": _MISS_META.copy()}
        cites = {c.chunk_id: c for c in self.repo.get_chunk_sources([cid])}
        c = cites.get(cid)
        uri = c.source_uri if c else ""
        return {
            "id": id,
            "title": uri,
            "text": chunk.text,  # FULL, untruncated (contrast search's snippet)
            "url": uri,
            "metadata": {
                "source_as_of": c.as_of.isoformat() if (c and c.as_of) else None,
                "document_id": chunk.document_id,
                "ordinal": chunk.ordinal,
                "found": True,
            },
        }

    def get_sources(self) -> list[dict]:
        """The document inventory backing the ontology, each with its ``as_of``. Calls
        ``self.repo.list_documents()`` — NEVER ``self.repo.get_sources(claim_ids)``, the
        unrelated claim-provenance homonym on the Repository (SP_022 review MEDIUM-1).
        ``raw_text`` is projected away here at the wire boundary."""
        return [
            {
                "source_uri": d.source_uri,
                "source_type": d.source_type,
                "title": d.title,
                "author": d.author,
                "as_of": d.as_of.isoformat() if d.as_of else None,
            }
            for d in self.repo.list_documents()
        ]

    def list_entities(self, entity_type: Optional[str] = None) -> list[dict]:
        """Enumerate entities, optionally by type — for corpus-wide 'what X are covered'
        questions. ``attributes`` is intentionally excluded (use ``get_entity`` for detail)."""
        return [
            {
                "id": e.id,
                "canonical_name": e.canonical_name,
                "entity_type": e.entity_type,
                "seeded": e.seeded,
            }
            for e in self.repo.list_entities(entity_type)
        ]

    # -- the ExposureEngine graph/temporal surface (SP_023) ------------- #
    # Four more optional tools discovered by mcp.server._retrieval via getattr — pure DB reads
    # ($0, no synthesis/embedding). They surface the ontology-shaped capabilities (temporal
    # history, graph traversal, vocabulary, cross-entity comparison) the four frozen methods
    # and the SP_022 retrieval primitives do not.
    def get_timeline(self, entity: str, predicate: str) -> dict:
        """Chronological claim history for ``entity``'s ``predicate`` — the supersession chain
        and any coexisting conflicting values, each cited and ``as_of``-stamped (the ontology
        versions facts, never overwrites). An ambiguous/unknown ``entity`` resolves to ``None``
        (never a silent pick) → ``resolved: False``, empty timeline. Built on
        ``get_claims_by_predicate(subject_id=…)`` so it shares the cross-entity tool's exact
        matching (no per-claim N+1; the two tools always agree on 'predicate X'). NB:
        ``source_as_of`` here is ``COALESCE(claim.as_of, doc.as_of)`` (the claim's reporting
        period, via ``get_sources``) — deliberately NOT the pure document date SP_022's
        ``search`` reports; a temporal view wants the fact's own period."""
        subj = self.repo.resolve_entity(entity)
        target = self.repo.canonical_predicate(predicate)
        if subj is None or subj.id is None:
            return {"entity": entity, "predicate": target, "resolved": False, "timeline": []}
        claims = self.repo.get_claims_by_predicate(predicate, subject_id=subj.id)
        cites = {c.claim_id: c for c in self.repo.get_sources([c.id for c in claims if c.id])}
        ordered = sorted(
            claims,
            key=lambda c: (c.as_of or date.min, c.valid_from or date.min, c.id or 0),
        )
        timeline: list[dict] = []
        for c in ordered:
            cit = cites.get(c.id)
            timeline.append(
                {
                    "claim_id": c.id,
                    "predicate": target,
                    "value": c.object_value,
                    "as_of": _iso(c.as_of),
                    "valid_from": _iso(c.valid_from),
                    "valid_to": _iso(c.valid_to),
                    "superseded_by": c.superseded_by,
                    "confidence": c.confidence,
                    "source_uri": cit.source_uri if cit else None,
                    "source_as_of": _iso(cit.as_of) if cit else None,
                    "snippet": cit.snippet if cit else None,
                }
            )
        return {
            "entity": subj.canonical_name,
            "entity_id": subj.id,
            "predicate": target,
            "resolved": True,
            "timeline": timeline,
        }

    def get_relationships(self, entity: str, link_type: Optional[str] = None) -> dict:
        """An entity's relationships in **both** directions (beyond `get_org_chart`'s
        reports_to): outgoing + incoming `owns`/`member_of`/`dotted_line_to`/`mentions`/
        `reports_to`. Unresolved entity → ``resolved: False``. Endpoint names are resolved via
        a `list_entities()` scan (corpus is small — avoids a get-entity-by-id seam)."""
        subj = self.repo.resolve_entity(entity)
        if subj is None or subj.id is None:
            return {"entity": entity, "resolved": False, "relationships": []}
        by_id: dict[int, tuple["Link", str]] = {}
        for ln in self.repo.get_links(link_type, from_entity_id=subj.id):
            if ln.id is not None:
                by_id[ln.id] = (ln, "outgoing")
        for ln in self.repo.get_links(link_type, to_entity_id=subj.id):
            if ln.id is not None and ln.id not in by_id:  # self-loop stays "outgoing"
                by_id[ln.id] = (ln, "incoming")
        names = {e.id: e.canonical_name for e in self.repo.list_entities()}
        cites = {c.link_id: c for c in self.repo.get_link_sources(list(by_id))}
        rels: list[dict] = []
        for lid, (ln, direction) in by_id.items():
            cit = cites.get(lid)
            rels.append(
                {
                    "link_id": lid,
                    "link_type": ln.link_type,
                    # SP_025: when link_type is the catch-all `mentions` because the original verb
                    # was out-of-vocab, raw_verb carries that verb (e.g. "contributor") — surface
                    # it so an agent can read the real relationship semantics. None for canonical.
                    "raw_verb": ln.raw_verb,
                    "direction": direction,
                    "from_entity_id": ln.from_entity_id,
                    "from_name": names.get(ln.from_entity_id),
                    "to_entity_id": ln.to_entity_id,
                    "to_name": names.get(ln.to_entity_id),
                    "as_of": _iso(ln.as_of),
                    "valid_to": _iso(ln.valid_to),
                    "source_uri": cit.source_uri if cit else None,
                    "source_as_of": _iso(cit.as_of) if cit else None,
                    "snippet": cit.snippet if cit else None,
                }
            )
        rels.sort(key=lambda r: (r["link_type"], r["link_id"]))
        return {
            "entity": subj.canonical_name,
            "entity_id": subj.id,
            "resolved": True,
            "relationships": rels,
        }

    def list_metrics(self) -> list[dict]:
        """The queryable metric vocabulary (canonical key + display name + aliases) — lets an
        agent discover which predicates it can ask about. NB: distinct from
        ``Repository.list_metrics`` (which returns ``MetricVocab[]``); this is the wire ``dict``."""
        return [
            {
                "canonical_key": m.canonical_key,
                "display_name": m.display_name,
                "aliases": m.aliases,
            }
            for m in self.repo.list_metrics()
        ]

    def get_claims_by_predicate(self, predicate: str) -> dict:
        """Every claim whose canonicalized predicate matches ``predicate``, across **all**
        subjects — for 'compare revenue across regions/quarters'. Conflicting/superseded values
        coexist (each carries `superseded_by`/`valid_to`); nothing is collapsed. The matched
        canonical key is echoed as ``predicate``. NB: distinct from
        ``Repository.get_claims_by_predicate`` (which returns raw ``Claim[]``); this is the
        wire-shaped ``dict``. Per-claim provenance ``snippet`` is intentionally omitted for
        compactness — use ``get_timeline`` for snippet-level provenance."""
        target = self.repo.canonical_predicate(predicate)
        claims = self.repo.get_claims_by_predicate(predicate)
        names = {e.id: e.canonical_name for e in self.repo.list_entities()}
        cites = {c.claim_id: c for c in self.repo.get_sources([c.id for c in claims if c.id])}
        out: list[dict] = []
        for c in claims:
            cit = cites.get(c.id)
            out.append(
                {
                    "claim_id": c.id,
                    "subject_entity_id": c.subject_entity_id,
                    "subject_name": names.get(c.subject_entity_id),
                    "value": c.object_value,
                    "as_of": _iso(c.as_of),
                    "valid_to": _iso(c.valid_to),
                    "superseded_by": c.superseded_by,
                    "confidence": c.confidence,
                    "source_uri": cit.source_uri if cit else None,
                    "source_as_of": _iso(cit.as_of) if cit else None,
                }
            )
        return {"predicate": target, "count": len(out), "claims": out}

    # -- internals ------------------------------------------------------ #
    @staticmethod
    def _candidate_terms(question: str) -> list[str]:
        """Question words + adjacent bigrams (deduped, capped) — the candidate
        names/metric terms for subject resolution and contradiction topics."""
        words = _WORD_RE.findall(question)
        terms = list(
            dict.fromkeys(words + [f"{a} {b}" for a, b in zip(words, words[1:])])
        )
        return terms[:_MAX_TERMS]

    def _resolve_subjects(
        self, terms: list[str], memo: dict[str, Optional["Entity"]]
    ) -> list["Entity"]:
        """Resolve candidate subject entities (roster-first, via the Repository).
        Ambiguous bare names resolve to None and are skipped — never a silent pick.

        ``memo`` is the caller's fresh per-``ask()`` dict, keyed on the normalized term
        (``strip().lower()`` — matching ``resolve_entity``'s own normalization). It
        collapses redundant lookups for case/whitespace-variant terms (e.g. "Revenue" vs
        "revenue") and caches the ``None`` miss so an ambiguous name is not re-queried.
        NOTE: this dedups *variant* lookups only — the dominant cost of many *distinct*
        names is not collapsed; a true batch ``resolve_entities`` would need a frozen
        ``Repository`` Protocol change (deferred, propose-don't-fork)."""
        found: dict[int, "Entity"] = {}
        for term in terms:
            key = term.strip().lower()
            if key in memo:
                ent = memo[key]
            else:
                ent = self.repo.resolve_entity(term)
                memo[key] = ent
            if ent is not None and ent.id is not None and ent.id not in found:
                found[ent.id] = ent
            if len(found) >= _MAX_SUBJECTS:
                break
        return list(found.values())

    def _gather_links(
        self, subject_ids: list[int], relevant: list[Contradiction]
    ) -> list["Link"]:
        """Relationship facts for grounding: links out of each resolved subject, PLUS the
        exact links named by every relevant link-contradiction so both sides become
        citeable ``[L#]`` markers. Deduped by id, ordered, capped — but a
        contradiction-side link is never dropped by the cap (else the synthesizer is told
        a conflict exists but cannot attribute it). Review H2: the conflicting links may
        hang off *different* entities than the subject, so they must be resolved by link
        id, not only by ``from_entity_id``."""
        needed: set[int] = set()
        for con in relevant:
            for lid in (con.link_a_id, con.link_b_id):
                if lid is not None:
                    needed.add(lid)
        by_id: dict[int, "Link"] = {}
        for sid in subject_ids:
            for link in self.repo.get_links(from_entity_id=sid):
                if link.id is not None:
                    by_id[link.id] = link
        # Pull any contradiction-side link not already gathered — its from-entity is
        # unknown (no get_link(id) on the Protocol), so scan all links once, only when a
        # needed side is actually missing.
        if needed - by_id.keys():
            for link in self.repo.get_links():
                if link.id in needed and link.id not in by_id:
                    by_id[link.id] = link
        sides = sorted(i for i in by_id if i in needed)
        others = [i for i in sorted(by_id) if i not in needed]
        budget = max(0, _MAX_LINKS - len(sides))
        kept = sorted(set(sides) | set(others[:budget]))
        return [by_id[i] for i in kept]

    def _gather_claim_facts(
        self, subject_ids: list[int], relevant: list[Contradiction]
    ) -> list["Claim"]:
        """All candidate claims for the resolved subjects, PLUS both sides of every
        relevant contradiction (so each side is citeable even when its subject was not
        resolved — review code-C1). Every claim is kept (not freshest-deduped): the
        SP_012 consensus rollup is now what consolidates same-predicate duplicates, and
        each member must keep its own ``[C#]`` marker so consensus + dissent stay
        individually citeable. Ordered by claim id for deterministic markers; capped."""
        by_id: dict[int, "Claim"] = {}
        contra_sides: set[int] = set()
        for sid in subject_ids:
            for c in self.repo.get_claims(sid):
                if c.id is not None:
                    by_id[c.id] = c
        for con in relevant:
            sides = [cid for cid in (con.claim_a_id, con.claim_b_id) if cid is not None]
            contra_sides.update(sides)
            if (
                any(cid not in by_id for cid in sides)
                and con.subject_entity_id is not None
            ):
                # pull the conflicting subject's claims so both sides are citeable
                for c in self.repo.get_claims(con.subject_entity_id):
                    if c.id is not None:
                        by_id[c.id] = c
        # Cap for perf/noise, but NEVER drop a contradiction side — losing one would make
        # the conflict unattributable in grounding (a silent half-resolution). Sides are
        # retained in full; the cap only bounds the remaining claims.
        sides_kept = sorted(i for i in by_id if i in contra_sides)
        others = [i for i in sorted(by_id) if i not in contra_sides]
        budget = max(0, _MAX_CLAIM_FACTS - len(sides_kept))
        kept = sorted(set(sides_kept) | set(others[:budget]))
        return [by_id[cid] for cid in kept]


def build_default_engine(repo: "Repository", *, k: int = 8) -> HelixQueryEngine:
    """Construct an engine with the real Voyage/Anthropic seams. The clients read
    keys/SDKs lazily on first use, so this is import- and key-safe."""
    from helixpay.query.clients import AnthropicSynthesizer, VoyageEmbedder

    return HelixQueryEngine(repo, VoyageEmbedder(), AnthropicSynthesizer(), k=k)


__all__ = ["HelixQueryEngine", "build_default_engine"]
