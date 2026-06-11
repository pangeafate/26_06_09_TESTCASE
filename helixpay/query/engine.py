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
        if plan.route in (Route.structured, Route.both):
            subjects = self._resolve_subjects(terms)
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
            return {"id": id, "title": "", "text": "", "url": "", "metadata": {"found": False}}
        chunk = self.repo.get_chunk(cid)
        if chunk is None:
            return {"id": id, "title": "", "text": "", "url": "", "metadata": {"found": False}}
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

    def _resolve_subjects(self, terms: list[str]) -> list["Entity"]:
        """Resolve candidate subject entities (roster-first, via the Repository).
        Ambiguous bare names resolve to None and are skipped — never a silent pick.
        (Perf note / Protocol friction: one ``resolve_entity`` call per term; a
        batched ``resolve_entities`` would collapse this hot loop.)"""
        found: dict[int, "Entity"] = {}
        for term in terms:
            ent = self.repo.resolve_entity(term)
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
