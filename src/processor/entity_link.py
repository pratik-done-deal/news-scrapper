"""Bridges a company-DB entity to the news graph.

The two systems share no key. The company DB identifies a company by
`(entity_type, entity_id)` — the seller card in the UI shows this as "S5123" —
while Neo4j identifies it by the company name the extractor read out of an
article. This module owns the crossing:

    "S5123"  ->  (seller, 5123)  ->  company DB row  ->  "Delhivery"  ->  Neo4j

The name is derived by `watchlist.derive_search_term()`, the same rule a scrape
uses, so the term a company's news is looked up by is the term its news was
fetched under. Diverging here would mean searching for a name no article was
ever stored against.
"""

import re
from dataclasses import dataclass
from typing import Optional

from ..db import mysql_queries as mq
from ..db.mysql_dao import MySQLDAO
from .watchlist import derive_search_term

# Reference prefix -> entity type. The company DB numbers each table
# independently, so the prefix is what makes "5123" unambiguous.
REF_PREFIXES = {
    "S": mq.SELLER,
    "B": mq.BUYER,
    "L": mq.LEAD,
}

_REF_RE = re.compile(r"^\s*([A-Za-z])\s*-?\s*(\d+)\s*$")


class InvalidEntityRef(ValueError):
    """Raised when a reference is not a recognised `<prefix><id>` pair."""


@dataclass(frozen=True)
class ResolvedEntity:
    """A company-DB entity and the name its news is filed under."""

    entity_type: str
    entity_id: int
    company_name: str
    brand_name: Optional[str]
    website: Optional[str]
    search_term: str

    @property
    def ref(self) -> str:
        for prefix, entity_type in REF_PREFIXES.items():
            if entity_type == self.entity_type:
                return f"{prefix}{self.entity_id}"
        return str(self.entity_id)


def parse_entity_ref(ref: str) -> tuple[str, int]:
    """Turn a UI reference into `(entity_type, entity_id)`.

    Accepts "S5123", "s5123" and "S-5123"; the numeric part is the company DB's
    own row id. A bare number is rejected rather than guessed at — seller 5123
    and buyer 5123 are different companies.
    """
    match = _REF_RE.match(ref or "")
    if not match:
        raise InvalidEntityRef(
            f"'{ref}' is not a valid entity reference — expected a prefix and an id, e.g. 'S5123'"
        )
    prefix, digits = match.group(1).upper(), match.group(2)
    if prefix not in REF_PREFIXES:
        known = ", ".join(sorted(REF_PREFIXES))
        raise InvalidEntityRef(f"Unknown entity prefix '{prefix}' — expected one of: {known}")
    return REF_PREFIXES[prefix], int(digits)


def resolve_entity(dao: MySQLDAO, entity_type: str, entity_id: int) -> Optional[ResolvedEntity]:
    """Look the entity up in the company DB, or None when it is not tracked."""
    row = mq.fetch_entity_by_id(dao, entity_type, entity_id)
    if not row:
        return None
    return ResolvedEntity(
        entity_type=row["entity_type"],
        entity_id=int(row["entity_id"]),
        company_name=row["company_name"],
        brand_name=row.get("brand_name"),
        website=row.get("website"),
        search_term=derive_search_term(row),
    )


def resolve_ref(dao: MySQLDAO, ref: str) -> Optional[ResolvedEntity]:
    """`parse_entity_ref()` then `resolve_entity()` — the UI's entry point."""
    entity_type, entity_id = parse_entity_ref(ref)
    return resolve_entity(dao, entity_type, entity_id)
