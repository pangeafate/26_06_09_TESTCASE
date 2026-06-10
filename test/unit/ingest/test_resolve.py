"""Roster-first resolution. The headline guarantee: the two Marias stay distinct, an
ambiguous bare name with no resolving context is NEVER silently picked or duplicated, and
only open-class (customer) mentions create new entities.

``FakeRepo`` faithfully mirrors the real ``PostgresRepository.resolve_entity`` /
``_filter_by_context`` semantics (exact canonical/alias match; multi-candidate ties broken
only by a resolving context) so these tests exercise the real algorithm with no DB.
"""

from __future__ import annotations

from helixpay.contracts import Entity
from helixpay.ingest.resolve import context_from_source_uri, fold_name, resolve_mention


class FakeRepo:
    def __init__(self) -> None:
        self.entities: list[Entity] = []
        self.aliases: dict[int, set[str]] = {}
        self._next = 1

    def seed(self, name, etype, attrs=None, aliases=()):
        e = Entity(id=self._next, canonical_name=name, entity_type=etype, attributes=attrs or {}, seeded=True)
        self.entities.append(e)
        self.aliases[e.id] = {a.lower() for a in aliases}
        self._next += 1
        return e.id

    # -- mirrors PostgresRepository --------------------------------------- #
    def upsert_entity(self, e: Entity) -> int:
        for ex in self.entities:
            if ex.canonical_name == e.canonical_name and ex.entity_type == e.entity_type:
                return ex.id  # type: ignore[return-value]
        new = Entity(id=self._next, canonical_name=e.canonical_name, entity_type=e.entity_type,
                     attributes=e.attributes, seeded=e.seeded)
        self.entities.append(new)
        self.aliases[new.id] = set()
        self._next += 1
        return new.id  # type: ignore[return-value]

    def resolve_entity(self, name, entity_type=None, context=None):
        nl = name.strip().lower()
        cands = [e for e in self.entities
                 if e.canonical_name.lower() == nl and (entity_type is None or e.entity_type == entity_type)]
        if not cands:
            cands = [e for e in self.entities
                     if nl in self.aliases[e.id] and (entity_type is None or e.entity_type == entity_type)]
        if not cands:
            return None
        if len(cands) == 1:
            return cands[0]
        if context:
            kept = self._filter(cands, context)
            if len(kept) == 1:
                return kept[0]
        return None

    @staticmethod
    def _filter(cands, context):
        kept = []
        for ent in cands:
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


def _two_marias() -> FakeRepo:
    repo = FakeRepo()
    repo.seed("Maria Silva", "person", {"department": "Sales", "location": "São Paulo"}, aliases=["Maria"])
    repo.seed("Maria Santos", "person", {"department": "Customer Success", "location": "São Paulo"}, aliases=["Maria"])
    return repo


def test_full_name_resolves_exactly():
    repo = _two_marias()
    assert resolve_mention(repo, "Maria Santos", entity_type="person") == 2


def test_ambiguous_bare_name_without_context_is_none_and_not_created():
    repo = _two_marias()
    before = len(repo.entities)
    assert resolve_mention(repo, "Maria", entity_type="person") is None
    assert len(repo.entities) == before  # no silent third "Maria"


def test_customer_success_path_disambiguates_to_santos():
    repo = _two_marias()
    ctx = context_from_source_uri("data/interviews/customer_success/Maria_Santos.md")
    assert resolve_mention(repo, "Maria", entity_type="person", context=ctx) == 2


def test_sales_path_disambiguates_to_silva():
    repo = _two_marias()
    ctx = context_from_source_uri("data/interviews/sales/maria-silva.md")
    assert resolve_mention(repo, "Maria", entity_type="person", context=ctx) == 1


def test_location_only_context_does_not_disambiguate():
    repo = _two_marias()
    # both Marias are in São Paulo — location must NOT pick one (would be a silent guess)
    assert resolve_mention(repo, "Maria", entity_type="person", context={"location": "São Paulo"}) is None


def test_accent_folding_matches_a_folded_roster_entry():
    repo = FakeRepo()
    repo.seed("Joao Pereira", "person", {"department": "Sales"})
    assert resolve_mention(repo, "João Pereira", entity_type="person") == 1


def test_new_customer_is_created_unseeded():
    repo = _two_marias()
    before = len(repo.entities)
    cid = resolve_mention(repo, "Cosmos Hotels", entity_type="customer")
    assert cid is not None and len(repo.entities) == before + 1
    assert repo.entities[-1].seeded is False


def test_unresolved_person_is_not_created():
    repo = _two_marias()
    before = len(repo.entities)
    assert resolve_mention(repo, "Some Stranger", entity_type="person") is None
    assert len(repo.entities) == before


def test_fold_name_strips_accents_and_honorifics():
    assert fold_name("Dr. João  Pereira") == "Joao Pereira"


def test_context_from_source_uri_maps_known_departments():
    assert context_from_source_uri("data/interviews/customer_success/Maria_Santos.md")["department"] == "Customer Success"
    assert context_from_source_uri("data/interviews/engineering/Sara_Wijaya.md")["department"] == "Engineering"
    assert context_from_source_uri("data/overview.md") == {}  # no department token
