"""The frozen Protocols are runtime-checkable and PostgresRepository satisfies the
Repository name-surface. (Signature conformance is enforced separately by mypy in
the freeze verification — runtime_checkable only checks attribute presence.)"""

from __future__ import annotations

from helixpay.contracts import QueryEngine, Repository, SourceConnector
from helixpay.db.repository import PostgresRepository

_REPOSITORY_METHODS = {
    "upsert_document", "add_chunks", "upsert_entity", "add_alias", "resolve_entity",
    "add_claim", "supersede_claim", "add_link", "add_contradiction", "canonical_predicate",
    "search_semantic", "search_lexical", "get_claims", "get_links", "get_org_subtree",
    "get_contradictions", "get_sources",
}


def test_protocols_are_runtime_checkable():
    for proto in (Repository, QueryEngine, SourceConnector):
        assert getattr(proto, "_is_runtime_protocol", False), f"{proto.__name__} must be @runtime_checkable"


def test_postgres_repository_satisfies_repository_protocol():
    # __init__ only stores the connection; a None placeholder is fine for the
    # structural (attribute-presence) check.
    repo = PostgresRepository(None)  # type: ignore[arg-type]
    assert isinstance(repo, Repository)


def test_postgres_repository_covers_every_protocol_method():
    missing = [m for m in _REPOSITORY_METHODS if not callable(getattr(PostgresRepository, m, None))]
    assert not missing, f"PostgresRepository is missing Protocol methods: {missing}"
