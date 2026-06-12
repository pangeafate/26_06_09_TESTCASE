"""Fake↔real Repository conformance (SP_030 Item 2).

The query unit suite is wired to the hand-written ``FakeRepository`` (``fakes.py``).
That fake can silently DRIFT from the real ``PostgresRepository`` read contract —
and the only thing that exercises the real reads (the ``db`` integration suite)
auto-skips without a database. This test builds the **same logical data** in both
repositories and runs **one shared assertion body** against each, so any divergence
in the reads the query layer depends on surfaces as a failure.

The ``fake`` parametrization always runs (local smoke). The ``real`` parametrization
is ``db``-marked → it skips locally and runs in CI against pgvector (where SP_030
provisions the service). Method set is restricted to DETERMINISTIC structural reads
the fake actually implements — ``search_semantic``/``search_lexical`` are excluded
because the fake returns canned slices independent of the query vector and does not
rank (comparing them to real pgvector search would assert false divergence).
"""

from __future__ import annotations

import pytest

from fakes import FakeRepository  # bare top-level module (test/unit/query on sys.path)
from helixpay.contracts import Claim, Entity, Link, MetricVocab

# Logical data shape built identically in both repositories. Entity keys are stable
# labels; the populate helpers map them to whatever ids the backend assigns.
_METRIC_KEY = "annual_recurring_revenue"
_METRIC_ALIASES = ["ARR", "annual recurring revenue"]


def _populate_fake(repo: FakeRepository) -> dict[str, int]:
    ids = {
        "helixpay": repo.add_entity(Entity(canonical_name="HelixPay", entity_type="other")),
        "maria_s": repo.add_entity(Entity(canonical_name="Maria Santos", entity_type="person")),
        "maria_l": repo.add_entity(Entity(canonical_name="Maria Lopez", entity_type="person")),
        "eng": repo.add_entity(Entity(canonical_name="Engineering", entity_type="team")),
    }
    repo.add_alias_for(ids["maria_s"], "MS")
    repo.add_metric(MetricVocab(canonical_key=_METRIC_KEY, display_name="ARR", aliases=_METRIC_ALIASES))
    repo.add_link_row(Link(from_entity_id=ids["maria_s"], to_entity_id=ids["maria_l"], link_type="reports_to"))
    repo.add_link_row(Link(from_entity_id=ids["maria_s"], to_entity_id=ids["eng"], link_type="dotted_line_to"))
    repo.add_claim_row(Claim(subject_entity_id=ids["helixpay"], predicate="ARR", object_value="SGD 14.2M", confidence=0.9))
    repo.add_claim_row(Claim(subject_entity_id=ids["helixpay"], predicate="annual recurring revenue", object_value="SGD 14.0M", confidence=0.8))
    return ids


def _populate_real(repo) -> dict[str, int]:
    ids = {
        "helixpay": repo.upsert_entity(Entity(canonical_name="HelixPay", entity_type="other")),
        "maria_s": repo.upsert_entity(Entity(canonical_name="Maria Santos", entity_type="person")),
        "maria_l": repo.upsert_entity(Entity(canonical_name="Maria Lopez", entity_type="person")),
        "eng": repo.upsert_entity(Entity(canonical_name="Engineering", entity_type="team")),
    }
    repo.add_alias(ids["maria_s"], "MS")
    repo.upsert_metric(_METRIC_KEY, "ARR", _METRIC_ALIASES)
    repo.add_link(Link(from_entity_id=ids["maria_s"], to_entity_id=ids["maria_l"], link_type="reports_to"))
    repo.add_link(Link(from_entity_id=ids["maria_s"], to_entity_id=ids["eng"], link_type="dotted_line_to"))
    repo.add_claim(Claim(subject_entity_id=ids["helixpay"], predicate="ARR", object_value="SGD 14.2M", confidence=0.9))
    repo.add_claim(Claim(subject_entity_id=ids["helixpay"], predicate="annual recurring revenue", object_value="SGD 14.0M", confidence=0.8))
    return ids


@pytest.fixture(
    params=[
        pytest.param("fake"),
        pytest.param("real", marks=pytest.mark.db),
    ]
)
def conformance(request):
    """Yield (repo, ids) for each backend. ``real`` is db-marked → CI-only."""
    if request.param == "fake":
        repo = FakeRepository()
        return repo, _populate_fake(repo)
    pg_repo = request.getfixturevalue("pg_repo")
    return pg_repo, _populate_real(pg_repo)


# --- resolve_entity ----------------------------------------------------------- #


def test_resolve_entity_by_canonical_name(conformance):
    repo, _ids = conformance
    ent = repo.resolve_entity("Maria Santos")
    assert ent is not None and ent.canonical_name == "Maria Santos"


def test_resolve_entity_by_alias(conformance):
    repo, ids = conformance
    ent = repo.resolve_entity("MS")
    assert ent is not None and ent.id == ids["maria_s"]


def test_resolve_entity_miss_is_none(conformance):
    repo, _ids = conformance
    assert repo.resolve_entity("Nobody Here") is None


def test_resolve_entity_type_mismatch_is_none(conformance):
    repo, _ids = conformance
    # A person name queried as a team must not resolve.
    assert repo.resolve_entity("Maria Santos", entity_type="team") is None


# --- canonical_predicate ------------------------------------------------------ #


def test_canonical_predicate_folds_aliases(conformance):
    repo, _ids = conformance
    a = repo.canonical_predicate("ARR")
    b = repo.canonical_predicate("annual recurring revenue")
    assert a == b == _METRIC_KEY


# --- get_claims_by_predicate -------------------------------------------------- #


def test_get_claims_by_predicate_canonicalizes(conformance):
    repo, ids = conformance
    claims = repo.get_claims_by_predicate("ARR")
    assert len(claims) == 2  # both raw spellings fold onto the same canonical key
    assert all(c.subject_entity_id == ids["helixpay"] for c in claims)
    assert {c.object_value for c in claims} == {"SGD 14.2M", "SGD 14.0M"}


# --- get_links ---------------------------------------------------------------- #


def test_get_links_filters_by_type(conformance):
    repo, _ids = conformance
    links = repo.get_links(link_type="reports_to")
    assert len(links) == 1
    assert all(link.link_type == "reports_to" for link in links)


def test_get_links_filters_by_from_entity(conformance):
    repo, ids = conformance
    links = repo.get_links(from_entity_id=ids["maria_s"])
    assert len(links) == 2  # reports_to + dotted_line_to both originate here
    assert all(link.from_entity_id == ids["maria_s"] for link in links)


def test_get_links_filters_by_to_entity(conformance):
    repo, ids = conformance
    links = repo.get_links(to_entity_id=ids["maria_l"])  # incoming edges (SP_023)
    assert len(links) == 1
    assert links[0].link_type == "reports_to"


# --- list_entities ------------------------------------------------------------ #


def test_list_entities_filters_and_sorts(conformance):
    repo, _ids = conformance
    people = repo.list_entities(entity_type="person")
    names = [e.canonical_name for e in people]
    assert names == ["Maria Lopez", "Maria Santos"]  # type-filtered, name-ascending


# --- get_contradictions (present-and-empty contract) -------------------------- #


def test_get_contradictions_is_present_and_empty(conformance):
    repo, _ids = conformance
    # No contradictions planted → the read returns an empty list, never None.
    assert repo.get_contradictions() == []
