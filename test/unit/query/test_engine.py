"""HelixQueryEngine wiring: Protocol conformance + end-to-end with fakes."""

from __future__ import annotations

from datetime import date

import pytest

from helixpay.contracts import (
    AnswerBundle,
    Chunk,
    Citation,
    Claim,
    Contradiction,
    Document,
    Entity,
    Link,
    MetricVocab,
    OrgNode,
    QueryEngine,
)
from helixpay.api.engine import ExposureEngine
from helixpay.query import HelixQueryEngine
from helixpay.query.clients import Embedder, Synthesizer

from fakes import FakeEmbedder, FakeSynthesizer


def _revenue_world(repo):
    rid = repo.add_entity(Entity(canonical_name="Revenue", entity_type="metric"))
    repo.vocab = {"revenue": "revenue"}
    repo.add_claim_row(
        Claim(
            id=10,
            subject_entity_id=rid,
            predicate="revenue",
            object_value="SGD 14.2M",
            as_of=date(2026, 3, 31),
        ),
        Citation(source_uri="data/dashboards/april.html", as_of=date(2026, 3, 31)),
    )
    repo.add_claim_row(
        Claim(
            id=11,
            subject_entity_id=rid,
            predicate="revenue",
            object_value="SGD 13.9M",
            as_of=date(2026, 3, 31),
        ),
        Citation(source_uri="data/board-deck.pdf", as_of=date(2026, 3, 31)),
    )
    repo.contradictions = [
        Contradiction(
            id=1,
            subject_entity_id=rid,
            predicate="revenue",
            claim_a_id=10,
            claim_b_id=11,
            kind="value_conflict",
        ),
    ]
    return rid


def _engine(repo, synth=None):
    return HelixQueryEngine(repo, FakeEmbedder(), synth or FakeSynthesizer(), k=8)


def test_fakes_satisfy_seam_protocols():
    assert isinstance(FakeEmbedder(), Embedder)
    assert isinstance(FakeSynthesizer(), Synthesizer)


def test_engine_satisfies_queryengine_protocol(repo):
    engine = _engine(repo)
    assert isinstance(engine, QueryEngine)


def test_engine_methods_return_contract_types(repo):
    _revenue_world(repo)
    repo.org_tree = OrgNode(
        entity_id=1, name="Wei Chen", children=[], dotted_reports=[]
    )
    engine = _engine(repo)
    assert isinstance(engine.ask("hello"), AnswerBundle)
    assert isinstance(engine.get_entity("Revenue"), dict)  # EntityDetail is a TypedDict
    assert isinstance(engine.get_org_chart(), dict)  # OrgNode is a TypedDict
    assert isinstance(engine.find_contradictions(), list)


def test_ask_surfaces_contradiction_with_both_sides_and_citations(repo):
    _revenue_world(repo)
    synth = FakeSynthesizer(
        {
            "sentences": [
                {"text": "The dashboard reports SGD 14.2M.", "cites": ["C1"]},
                {"text": "The board deck reports SGD 13.9M.", "cites": ["C2"]},
                {"text": "These two sources disagree.", "cites": ["C1", "C2"]},
            ],
            "confidence": 0.7,
        }
    )
    bundle = _engine(repo, synth).ask("What was HelixPay's Q1 2026 revenue?")
    # contradiction surfaced with both sides attributed
    assert len(bundle.contradictions) == 1
    assert bundle.contradictions[0].claim_a_id == 10
    assert bundle.contradictions[0].claim_b_id == 11
    # both conflicting claims cited (zero uncited claims, both values attributed)
    assert "14.2M" in bundle.answer and "13.9M" in bundle.answer
    uris = {c.source_uri for c in bundle.citations}
    assert uris == {"data/dashboards/april.html", "data/board-deck.pdf"}
    assert bundle.as_of_coverage["latest"] == "2026-03-31"
    assert bundle.confidence == 0.7


def test_ask_keeps_contradiction_even_when_answer_uncited(repo):
    # Contradictions are first-class — surfaced even if synthesis cited nothing.
    _revenue_world(repo)
    synth = FakeSynthesizer(
        {"sentences": [{"text": "Vague uncited claim.", "cites": []}]}
    )
    bundle = _engine(repo, synth).ask("What was Q1 revenue?")
    assert bundle.answer == "I could not find sufficient cited evidence to answer that."
    assert bundle.citations == []
    assert len(bundle.contradictions) == 1  # never hidden


def test_ask_populates_trace(repo):
    _revenue_world(repo)
    synth = FakeSynthesizer(
        {"sentences": [{"text": "SGD 14.2M.", "cites": ["C1"]}], "confidence": 0.6}
    )
    engine = _engine(repo, synth)
    engine.ask("What was HelixPay's Q1 2026 revenue?")
    assert engine.last_trace["route"] == "both"
    assert 10 in engine.last_trace["cited_claim_ids"]
    assert engine.last_trace["contradiction_ids"] == [1]


def test_ask_surfaces_contradiction_even_when_subject_entity_unresolved(repo):
    # The "Revenue" entity is NOT registered (resolve_entity returns None), but a
    # value_conflict on predicate "revenue" exists. The topic path must surface it
    # and both sides must still be citeable (reviews code-C1 + code-C2 together).
    sid = 5  # subject id with no entity name → resolve_entity("revenue") is None
    repo.vocab = {"revenue": "revenue"}
    repo.add_claim_row(
        Claim(
            id=10,
            subject_entity_id=sid,
            predicate="revenue",
            object_value="SGD 14.2M",
            as_of=date(2026, 3, 31),
        ),
        Citation(source_uri="data/dash.html", as_of=date(2026, 3, 31)),
    )
    repo.add_claim_row(
        Claim(
            id=11,
            subject_entity_id=sid,
            predicate="revenue",
            object_value="SGD 13.9M",
            as_of=date(2026, 3, 31),
        ),
        Citation(source_uri="data/board.pdf", as_of=date(2026, 3, 31)),
    )
    repo.contradictions = [
        Contradiction(
            id=1,
            subject_entity_id=sid,
            predicate="revenue",
            claim_a_id=10,
            claim_b_id=11,
        ),
    ]
    synth = FakeSynthesizer(
        {
            "sentences": [
                {"text": "Dashboard 14.2M.", "cites": ["C1"]},
                {"text": "Board 13.9M.", "cites": ["C2"]},
            ]
        }
    )
    bundle = _engine(repo, synth).ask("What was Q1 revenue?")
    assert len(bundle.contradictions) == 1
    assert {c.source_uri for c in bundle.citations} == {
        "data/dash.html",
        "data/board.pdf",
    }


def test_find_contradictions_by_topic(repo):
    _revenue_world(repo)
    got = _engine(repo).find_contradictions("revenue")
    assert [c.id for c in got] == [1]


def test_get_org_chart_root(repo):
    repo.add_entity(
        Entity(
            canonical_name="Wei Chen", entity_type="person", attributes={"role": "CEO"}
        )
    )
    repo.org_tree = OrgNode(
        entity_id=1, name="Wei Chen", children=[], dotted_reports=[]
    )
    tree = _engine(repo).get_org_chart()
    assert tree["name"] == "Wei Chen" and tree["role"] == "CEO"


# -- SP_012: provenance surface ------------------------------------------ #
def _runway_world(repo):
    rid = repo.add_entity(Entity(canonical_name="runway", entity_type="metric"))
    repo.vocab = {"runway": "runway"}
    for i, (val, as_of) in enumerate(
        [
            ("18 months", date(2026, 1, 1)),
            ("eighteen months", date(2026, 3, 31)),
            ("18 months", date(2026, 2, 1)),
            ("24 months", date(2026, 3, 15)),
        ],
        start=10,
    ):
        repo.add_claim_row(
            Claim(
                id=i,
                subject_entity_id=rid,
                predicate="runway",
                object_value=val,
                as_of=as_of,
            ),
            Citation(source_uri=f"data/src-{i}.md", as_of=as_of),
        )
    return rid


def test_ask_renders_consensus_into_the_prompt(repo):
    _runway_world(repo)
    synth = FakeSynthesizer(
        {
            "sentences": [{"text": "Runway is 18 months.", "cites": ["C1"]}],
            "confidence": 0.6,
        }
    )
    _engine(repo, synth).ask("What is the runway?")
    assert synth.last_prompt is not None
    assert "Consensus" in synth.last_prompt
    assert "3 source" in synth.last_prompt  # three "18 months" variants corroborate
    assert "24 months" in synth.last_prompt  # dissent still present, never collapsed
    assert "[C" in synth.last_prompt  # consensus cites real claim markers


def test_ask_types_contradiction_into_the_prompt(repo):
    _revenue_world(repo)  # value_conflict on revenue
    synth = FakeSynthesizer({"sentences": [{"text": "x", "cites": ["C1"]}]})
    _engine(repo, synth).ask("What was Q1 revenue?")
    assert "value conflict" in synth.last_prompt.lower()
    # both sides attributed to their markers (never an unattributed conflict line)
    assert "[C1]" in synth.last_prompt and "[C2]" in synth.last_prompt
    assert "vs" in synth.last_prompt


def test_gather_claim_facts_never_drops_a_contradiction_side_past_the_cap(repo):
    # A subject with many claims (> the cap) plus a contradiction whose sides sort to the
    # extremes must still surface BOTH sides — losing one half-resolves the conflict.
    rid = repo.add_entity(Entity(canonical_name="Metric", entity_type="metric"))
    for i in range(1, 71):  # 70 claims, ids 1..70 (cap is 50)
        repo.add_claim_row(
            Claim(id=i, subject_entity_id=rid, predicate=f"p{i}", object_value=str(i))
        )
    con = Contradiction(
        id=1, subject_entity_id=rid, predicate="p1", claim_a_id=1, claim_b_id=70
    )
    repo.contradictions = [con]
    facts = _engine(repo)._gather_claim_facts([rid], [con])
    ids = {c.id for c in facts}
    assert 1 in ids and 70 in ids  # both extremes retained despite the cap


def test_ask_cites_a_retrieved_chunk(repo):
    # Feature 1 end-to-end: a [S#]-grounded answer carries a real chunk Citation.
    chunk = Chunk(
        id=5, document_id=1, ordinal=0, text="HelixPay closed Series B in March."
    )
    repo.semantic = [(chunk, 0.9)]
    repo.add_chunk_source(5, Citation(source_uri="data/news.md", snippet=chunk.text))
    synth = FakeSynthesizer(
        {
            "sentences": [
                {"text": "HelixPay closed Series B in March.", "cites": ["S1"]}
            ],
            "confidence": 0.5,
        }
    )
    eng = _engine(repo, synth)
    bundle = eng.ask("When did HelixPay close Series B?")
    assert any(c.chunk_id == 5 for c in bundle.citations)
    assert eng.last_trace["cited_chunk_ids"] == [5]


def test_ask_cites_a_relationship_link(repo):
    # Feature 2 end-to-end: a relationship answer carries a link Citation.
    boss = repo.add_entity(Entity(canonical_name="Bob", entity_type="person"))
    repo.add_entity(Entity(canonical_name="Alice", entity_type="person"))
    link = Link(id=3, from_entity_id=boss, to_entity_id=2, link_type="reports_to")
    repo.add_link_row(link, Citation(source_uri="data/org-chart.md"))
    synth = FakeSynthesizer(
        {
            "sentences": [{"text": "Bob reports to Alice.", "cites": ["L1"]}],
            "confidence": 0.5,
        }
    )
    eng = _engine(repo, synth)
    bundle = eng.ask("Who does Bob report to?")
    assert any(c.link_id == 3 for c in bundle.citations)
    assert eng.last_trace["cited_link_ids"] == [3]


def test_gather_links_surfaces_link_contradiction_side_on_other_entity(repo):
    # Review H2: a link-pair contradiction's two links can hang off DIFFERENT entities.
    # The conflicting link (id 6, from entity 7) is not reachable via the subject's
    # from_entity_id, so it must be resolved by link id — else the synthesizer is told
    # a conflict exists but is never given the second side to attribute.
    bob = repo.add_entity(Entity(canonical_name="Bob", entity_type="person"))
    repo.add_link_row(Link(id=5, from_entity_id=bob, to_entity_id=2, link_type="reports_to"))
    repo.add_link_row(Link(id=6, from_entity_id=7, to_entity_id=3, link_type="reports_to"))
    con = Contradiction(id=1, subject_entity_id=bob, link_a_id=5, link_b_id=6,
                        kind="source_disagreement")
    links = _engine(repo)._gather_links([bob], [con])
    assert {ln.id for ln in links} == {5, 6}   # both sides surfaced despite link 6 off entity 7


# -- SP_022: MCP retrieval surfaces (search / fetch / get_sources / list_entities) -- #
def test_engine_satisfies_exposure_engine_protocol(repo):
    engine: ExposureEngine = _engine(repo)  # typed assignment: mypy conformance too
    assert isinstance(engine, ExposureEngine)


def test_search_preserves_rrf_rank_and_realigns_provenance_by_chunk_id(repo):
    # Two hits whose RRF rank order is the OPPOSITE of chunk-id order, so a naive zip of
    # hybrid_search output against get_chunk_sources (which returns ORDER BY chunk id) would
    # mis-assign provenance. Chunk 30 outranks chunk 10; provenance must follow the id.
    top = Chunk(id=30, document_id=7, ordinal=0, text="alpha series B closed")
    low = Chunk(id=10, document_id=3, ordinal=0, text="bravo runway update")
    repo.semantic = [(top, 0.9), (low, 0.5)]
    repo.lexical = [(top, 0.8), (low, 0.4)]
    repo.add_chunk_source(30, Citation(source_uri="data/a.md", as_of=date(2026, 3, 31)))
    # chunk 10 has NO citation → fallback path
    results = _engine(repo).search("series B", k=8)
    assert [r["id"] for r in results] == ["30", "10"]  # RRF rank order, NOT id order
    assert results[0]["score"] >= results[1]["score"]
    assert results[0]["url"] == "data/a.md"
    assert results[0]["source_as_of"] == "2026-03-31"  # the DOCUMENT date, guarded iso
    assert results[0]["document_id"] == 7
    # no-citation hit falls back cleanly (review H1) — never a None.isoformat crash
    assert results[1]["url"] == "" and results[1]["title"] == ""
    assert results[1]["source_as_of"] is None


def test_search_caps_at_k_and_skips_idless_chunks(repo):
    # k truncation is upstream in hybrid_search (fused[:k]); confirm end-to-end. Also a
    # chunk with no id must never surface as the literal string "None" (review H1).
    a = Chunk(id=2, document_id=1, ordinal=0, text="alpha")
    b = Chunk(id=1, document_id=1, ordinal=1, text="bravo")
    idless = Chunk(id=None, document_id=1, ordinal=2, text="ghost")
    repo.semantic = [(a, 0.9), (b, 0.5), (idless, 0.4)]
    results = _engine(repo).search("x", k=2)
    assert len(results) <= 2
    assert all(r["id"] != "None" for r in results)  # no id=None chunk leaks through


def test_search_snippet_is_truncated_while_fetch_returns_full_text(repo):
    long_text = "x" * 600
    chunk = Chunk(id=42, document_id=1, ordinal=0, text=long_text)
    repo.semantic = [(chunk, 0.9)]
    repo.add_chunk_row(chunk)
    repo.add_chunk_source(42, Citation(source_uri="data/big.md", as_of=date(2026, 1, 1)))
    eng = _engine(repo)
    snippet = eng.search("x", k=1)[0]["snippet"]
    assert len(snippet) < len(long_text) and snippet.endswith("…")
    fetched = eng.fetch("42")
    assert fetched["text"] == long_text  # full, untruncated
    assert len(fetched["text"]) > len(snippet)


def test_fetch_returns_provenance_metadata(repo):
    chunk = Chunk(id=5, document_id=9, ordinal=2, text="HelixPay closed Series B.")
    repo.add_chunk_row(chunk)
    repo.add_chunk_source(5, Citation(source_uri="data/news.md", as_of=date(2026, 2, 1)))
    got = _engine(repo).fetch("5")
    assert got["id"] == "5" and got["text"] == "HelixPay closed Series B."
    assert got["url"] == "data/news.md"
    assert got["metadata"]["found"] is True
    assert got["metadata"]["source_as_of"] == "2026-02-01"
    assert got["metadata"]["document_id"] == 9 and got["metadata"]["ordinal"] == 2


def test_fetch_unknown_and_malformed_ids_degrade_without_raising(repo):
    eng = _engine(repo)
    for bad in ("999", "abc", "", "3.5"):  # valid-but-absent + non-int — none may raise
        got = eng.fetch(bad)
        assert got["metadata"]["found"] is False
        assert got["text"] == "" and got["url"] == ""
        # stable metadata key set even on a miss (review M2 — no KeyError for consumers)
        assert got["metadata"]["document_id"] is None
        assert got["metadata"]["source_as_of"] is None


def test_get_sources_lists_inventory_and_tolerates_null_as_of(repo):
    repo.add_document(Document(id=1, source_uri="data/q1.html", source_type="html",
                              title="Q1 Dashboard", as_of=date(2026, 3, 31),
                              content_hash="h1", raw_text="big body"))
    repo.add_document(Document(id=2, source_uri="data/notes.md", source_type="md",
                              title=None, as_of=None, content_hash="h2"))
    out = _engine(repo).get_sources()
    by_uri = {d["source_uri"]: d for d in out}
    assert by_uri["data/q1.html"]["as_of"] == "2026-03-31"
    assert by_uri["data/notes.md"]["as_of"] is None  # null-date doc, no crash (review H2)
    assert "raw_text" not in by_uri["data/q1.html"]  # projected away at the wire boundary


def test_list_entities_filters_by_type_and_excludes_attributes(repo):
    repo.add_entity(Entity(canonical_name="HelixPay Brasil", entity_type="other",
                           attributes={"region": "BR"}))
    repo.add_entity(Entity(canonical_name="HelixPay SEA", entity_type="other"))
    repo.add_entity(Entity(canonical_name="Wei Chen", entity_type="person"))
    eng = _engine(repo)
    others = eng.list_entities("other")
    assert [e["canonical_name"] for e in others] == ["HelixPay Brasil", "HelixPay SEA"]
    assert "attributes" not in others[0]  # detail lives in get_entity (review L2)
    assert len(eng.list_entities(None)) == 3       # list-all
    assert eng.list_entities("nonexistent") == []  # unknown type → [], no raise


# --------------------------------------------------------------------------- #
# SP_023 graph/temporal surfaces                                              #
# --------------------------------------------------------------------------- #
def _hp(repo):
    """A 'HelixPay' subject with a metric vocab where 'arr' canonicalizes to 'revenue'."""
    hid = repo.add_entity(Entity(canonical_name="HelixPay", entity_type="other", seeded=True))
    repo.add_metric(MetricVocab(canonical_key="revenue", display_name="Revenue",
                                aliases=["arr", "annual recurring revenue"]))
    return hid


def test_get_timeline_orders_history_and_surfaces_supersession(repo):
    hid = _hp(repo)
    # Three coexisting/versioned revenue claims, deliberately added out of chronological order;
    # one is stored under the ALIAS "arr" (must canonicalize onto "revenue").
    repo.add_claim_row(
        Claim(id=2, subject_entity_id=hid, predicate="revenue", object_value="$3.9M",
              as_of=date(2026, 2, 1), superseded_by=3),
        Citation(source_uri="data/dash.html", as_of=date(2026, 2, 2)),
    )
    repo.add_claim_row(
        Claim(id=3, subject_entity_id=hid, predicate="arr", object_value="$4.4M",
              as_of=date(2026, 3, 31)),
        Citation(source_uri="data/board.pdf", as_of=date(2026, 4, 15)),
    )
    repo.add_claim_row(
        Claim(id=1, subject_entity_id=hid, predicate="revenue", object_value="$3.5M",
              as_of=date(2026, 1, 1)),
        Citation(source_uri="data/jan.md", as_of=date(2026, 1, 5)),
    )
    tl = _engine(repo).get_timeline("HelixPay", "revenue")
    assert tl["resolved"] is True and tl["entity"] == "HelixPay" and tl["predicate"] == "revenue"
    # ascending by as_of; the alias-stored claim is included
    assert [e["value"] for e in tl["timeline"]] == ["$3.5M", "$3.9M", "$4.4M"]
    assert [e["as_of"] for e in tl["timeline"]] == ["2026-01-01", "2026-02-01", "2026-03-31"]
    # supersession chain visible; each entry cited
    mid = tl["timeline"][1]
    assert mid["superseded_by"] == 3
    assert mid["source_uri"] == "data/dash.html" and mid["source_as_of"] == "2026-02-02"


def test_get_timeline_unresolved_entity_degrades_without_raising(repo):
    _hp(repo)
    tl = _engine(repo).get_timeline("Nobody Here", "revenue")
    assert tl["resolved"] is False and tl["timeline"] == []
    assert tl["predicate"] == "revenue"  # canonicalized label still returned, no raise


def test_get_timeline_resolved_entity_with_no_matching_claims_is_empty(repo):
    _hp(repo)  # HelixPay resolves, but has no 'runway' claims
    repo.add_metric(MetricVocab(canonical_key="runway", display_name="Runway", aliases=[]))
    tl = _engine(repo).get_timeline("HelixPay", "runway")
    assert tl["resolved"] is True and tl["timeline"] == []  # resolved, just empty


def test_get_relationships_returns_both_directions_with_names(repo):
    maria = repo.add_entity(Entity(canonical_name="Maria Santos", entity_type="person"))
    tan = repo.add_entity(Entity(canonical_name="Tan Wei", entity_type="person"))
    bob = repo.add_entity(Entity(canonical_name="Bob Lee", entity_type="person"))
    # Maria -> reports_to -> Tan (outgoing); Bob -> reports_to -> Maria (incoming to Maria)
    repo.add_link_row(Link(id=1, from_entity_id=maria, to_entity_id=tan, link_type="reports_to",
                           as_of=date(2026, 1, 1)),
                      Citation(source_uri="data/org.md", as_of=date(2026, 1, 1)))
    repo.add_link_row(Link(id=2, from_entity_id=bob, to_entity_id=maria, link_type="reports_to"))
    rels = _engine(repo).get_relationships("Maria Santos")
    assert rels["resolved"] is True
    by_id = {r["link_id"]: r for r in rels["relationships"]}
    assert by_id[1]["direction"] == "outgoing"
    assert by_id[1]["from_name"] == "Maria Santos" and by_id[1]["to_name"] == "Tan Wei"
    assert by_id[1]["source_uri"] == "data/org.md"
    assert by_id[2]["direction"] == "incoming"
    assert by_id[2]["from_name"] == "Bob Lee" and by_id[2]["to_name"] == "Maria Santos"
    assert by_id[2]["source_uri"] is None  # absent-citation tolerated


def test_get_relationships_filters_by_link_type_and_self_loop_is_outgoing(repo):
    a = repo.add_entity(Entity(canonical_name="Acme", entity_type="customer"))
    repo.add_link_row(Link(id=1, from_entity_id=a, to_entity_id=a, link_type="owns"))
    repo.add_link_row(Link(id=2, from_entity_id=a, to_entity_id=a, link_type="mentions"))
    rels = _engine(repo).get_relationships("Acme", link_type="owns")
    assert [r["link_id"] for r in rels["relationships"]] == [1]  # link_type narrows
    assert rels["relationships"][0]["direction"] == "outgoing"  # self-loop emitted once


def test_get_relationships_unresolved_entity_degrades(repo):
    out = _engine(repo).get_relationships("Ghost")
    assert out["resolved"] is False and out["relationships"] == []


def test_list_metrics_returns_vocab_and_empty_when_none(repo):
    assert _engine(repo).list_metrics() == []
    repo.add_metric(MetricVocab(canonical_key="revenue", display_name="Revenue", aliases=["arr"]))
    repo.add_metric(MetricVocab(canonical_key="runway", display_name="Runway", aliases=[]))
    out = _engine(repo).list_metrics()
    assert [m["canonical_key"] for m in out] == ["revenue", "runway"]
    assert out[0]["aliases"] == ["arr"] and out[0]["display_name"] == "Revenue"


def test_get_claims_by_predicate_spans_subjects_and_canonicalizes_alias(repo):
    repo.add_metric(MetricVocab(canonical_key="revenue", aliases=["arr"]))
    sea = repo.add_entity(Entity(canonical_name="HelixPay SEA", entity_type="other"))
    bra = repo.add_entity(Entity(canonical_name="HelixPay Brasil", entity_type="other"))
    repo.add_claim_row(
        Claim(id=1, subject_entity_id=sea, predicate="revenue", object_value="$9.4M",
              as_of=date(2026, 3, 31)),
        Citation(source_uri="data/sea.md", as_of=date(2026, 4, 1)),
    )
    repo.add_claim_row(  # stored under the alias — must still match "revenue"
        Claim(id=2, subject_entity_id=bra, predicate="arr", object_value="$4.8M",
              as_of=date(2026, 3, 31)),
        Citation(source_uri="data/bra.md", as_of=date(2026, 4, 1)),
    )
    got = _engine(repo).get_claims_by_predicate("revenue")
    assert got["predicate"] == "revenue" and got["count"] == 2
    by_subj = {c["subject_name"]: c for c in got["claims"]}
    assert by_subj["HelixPay SEA"]["value"] == "$9.4M"
    assert by_subj["HelixPay Brasil"]["value"] == "$4.8M"  # alias-stored, found
    assert by_subj["HelixPay SEA"]["source_uri"] == "data/sea.md"


def test_get_claims_by_predicate_unknown_predicate_is_empty(repo):
    got = _engine(repo).get_claims_by_predicate("headcount")
    assert got["count"] == 0 and got["claims"] == []
