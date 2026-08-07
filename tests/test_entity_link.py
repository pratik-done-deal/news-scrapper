"""Resolving a company DB reference ("S5123") to the name its news is filed under."""

from unittest.mock import MagicMock

import pytest

from src.processor.entity_link import (
    InvalidEntityRef,
    parse_entity_ref,
    resolve_entity,
    resolve_ref,
)


@pytest.mark.parametrize(
    "ref, expected",
    [
        ("S5123", ("seller", 5123)),
        ("s5123", ("seller", 5123)),
        ("S-5123", ("seller", 5123)),
        ("  S5123 ", ("seller", 5123)),
        ("B42", ("buyer", 42)),
        ("L7", ("lead", 7)),
    ],
)
def test_reference_forms_resolve_to_type_and_id(ref, expected):
    assert parse_entity_ref(ref) == expected


@pytest.mark.parametrize("ref", ["5123", "", "   ", "S", "X5123", "S12A3", None])
def test_unparseable_references_are_rejected(ref):
    """A bare number is ambiguous — seller 5123 and buyer 5123 differ."""
    with pytest.raises(InvalidEntityRef):
        parse_entity_ref(ref)


def _dao_returning(row):
    dao = MagicMock()
    dao.fetch_all.return_value = [row] if row else []
    return dao


def test_brand_name_wins_over_registered_name():
    """Press coverage says "Ola", never "ANI Technologies Private Limited"."""
    dao = _dao_returning({
        "entity_type": "seller",
        "entity_id": 5123,
        "company_name": "ANI Technologies Private Limited",
        "brand_name": "Ola",
        "website": "https://olacabs.com",
    })

    entity = resolve_entity(dao, "seller", 5123)

    assert entity.search_term == "Ola"
    assert entity.company_name == "ANI Technologies Private Limited"
    assert entity.ref == "S5123"


def test_legal_suffix_is_stripped_when_no_brand_exists():
    dao = _dao_returning({
        "entity_type": "seller",
        "entity_id": 5123,
        "company_name": "Delhivery Limited",
        "brand_name": None,
        "website": None,
    })

    assert resolve_entity(dao, "seller", 5123).search_term == "Delhivery"


def test_untracked_entity_resolves_to_none():
    """A de-listed seller must not quietly serve news — the row is filtered out
    by the same active-record rules the watchlist uses."""
    assert resolve_entity(_dao_returning(None), "seller", 9999) is None


def test_resolve_ref_threads_the_reference_through():
    dao = _dao_returning({
        "entity_type": "buyer",
        "entity_id": 42,
        "company_name": "Meesho",
        "brand_name": None,
        "website": None,
    })

    entity = resolve_ref(dao, "B42")

    assert (entity.entity_type, entity.entity_id) == ("buyer", 42)
    assert entity.ref == "B42"
    assert entity.search_term == "Meesho"
