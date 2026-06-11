"""DB-gated end-to-end for the LLM adjudication sweep (SP_028b). $0 — a scripted stub client,
no real model. Auto-skipped unless DATABASE_URL is set (see test/conftest.py).

Plants, in a freshly-migrated store:
  * a same-period revenue conflict on HelixPay (two sources, two values)   → must surface (claim pair)
  * a multi-valued ``pain_point`` set on HelixPay                          → must NOT surface
  * a solid vs dotted org line for a person (link block)                   → must surface (link pair)
and asserts the written contradiction set matches, through the real PostgresRepository.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from helixpay.contracts import Chunk, Claim, Document, Entity, Link
from helixpay.ingest.adjudicate import DictCache, adjudicate_store

pytestmark = pytest.mark.db


def _doc(repo, uri: str) -> int:
    return repo.upsert_document(
        Document(source_uri=uri, source_type="html", content_hash=f"h-{uri}", raw_text="x")
    )


def _stub_responder(user: str) -> str:
    if "reports_to" in user or "dotted_line_to" in user:
        return json.dumps(
            {"contradictions": [{"block": "link", "a": 1, "b": 2,
                                 "kind": "source_disagreement", "rationale": "sources disagree on line"}]}
        )
    if "revenue" in user:
        return json.dumps(
            {"contradictions": [{"block": "claim", "a": 1, "b": 2,
                                 "kind": "source_disagreement", "rationale": "same quarter, two values"}]}
        )
    return json.dumps({"contradictions": []})


class _Stub:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, *, system: str, user: str, max_tokens: int) -> str:
        self.calls += 1
        return _stub_responder(user)


def _seed(repo) -> dict[str, int]:
    d1, d2 = _doc(repo, "dash.html"), _doc(repo, "board.md")
    hp = repo.upsert_entity(Entity(canonical_name="HelixPay", entity_type="other"))
    maria = repo.upsert_entity(Entity(canonical_name="Maria Santos", entity_type="person"))
    mgr_a = repo.upsert_entity(Entity(canonical_name="Manager A", entity_type="person"))
    mgr_b = repo.upsert_entity(Entity(canonical_name="Manager B", entity_type="person"))

    # same-period revenue conflict (two docs, same as_of → overlap → source_disagreement)
    repo.add_claim(Claim(subject_entity_id=hp, predicate="revenue", object_value="SGD 14.2M",
                         as_of=date(2026, 3, 31), document_id=d1))
    repo.add_claim(Claim(subject_entity_id=hp, predicate="revenue", object_value="SGD 13.9M",
                         as_of=date(2026, 3, 31), document_id=d2))
    # multi-valued pain_point — legitimate multiplicity, never a conflict
    repo.add_claim(Claim(subject_entity_id=hp, predicate="pain_point", object_value="slow onboarding",
                         as_of=date(2026, 3, 31), document_id=d1))
    repo.add_claim(Claim(subject_entity_id=hp, predicate="pain_point", object_value="opaque reporting",
                         as_of=date(2026, 3, 31), document_id=d2))
    # solid vs dotted org line for Maria (link block; dotted is NOT swept by detect_link_conflicts)
    repo.add_link(Link(from_entity_id=maria, to_entity_id=mgr_a, link_type="reports_to", document_id=d1))
    repo.add_link(Link(from_entity_id=maria, to_entity_id=mgr_b, link_type="dotted_line_to", document_id=d2))
    repo.conn.commit()
    return {"hp": hp, "maria": maria}


def test_adjudication_surfaces_planted_conflicts_and_skips_multivalued(pg_repo):
    ids = _seed(pg_repo)
    stub = _Stub()
    stats = adjudicate_store(pg_repo, stub, DictCache())
    pg_repo.conn.commit()

    rows = pg_repo.get_contradictions()

    # the multi-valued predicate is never a contradiction
    assert all((r.predicate or "") != "pain_point" for r in rows)

    # the same-period revenue conflict surfaced as a CLAIM pair
    rev = [r for r in rows if r.subject_entity_id == ids["hp"] and r.claim_a_id is not None]
    assert len(rev) == 1
    assert (rev[0].note or "").startswith("[llm]")
    assert rev[0].link_a_id is None

    # the solid-vs-dotted line surfaced as a LINK pair (cross-predicate recall the floor can't catch)
    links = [r for r in rows if r.subject_entity_id == ids["maria"] and r.link_a_id is not None]
    assert len(links) == 1
    assert links[0].claim_a_id is None
    assert stats["llm_rows"] >= 2


def test_second_sweep_is_zero_cost_on_unchanged_store(pg_repo):
    _seed(pg_repo)
    cache = DictCache()
    stub = _Stub()
    adjudicate_store(pg_repo, stub, cache)
    pg_repo.conn.commit()
    first = stub.calls
    assert first >= 1
    adjudicate_store(pg_repo, stub, cache)  # content-cache hit on every cluster
    pg_repo.conn.commit()
    assert stub.calls == first
