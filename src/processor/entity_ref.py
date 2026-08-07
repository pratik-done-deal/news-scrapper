"""Parsing the Done Deal entity reference the UI shows on a company card.

"S5124" is a prefix plus the row id in the system that owns the entity. The
prefix is not decoration: the company DB numbers sellers, buyers and leads
independently, so seller 5124 and buyer 5124 are different companies and a bare
number cannot be resolved. Rejecting it is the point.

This is pure parsing — no I/O and no dependency on the company DB. The
reference itself is stored on the Company node (`external_id`) when Done Deal
registers a company, which is what lets the news feed be read by id alone.
"""

import re

# Reference prefix -> the Done Deal entity type it identifies.
REF_PREFIXES = {
    "S": "seller",
    "B": "buyer",
    "L": "lead",
}

_REF_RE = re.compile(r"^\s*([A-Za-z])\s*-?\s*(\d+)\s*$")


class InvalidEntityRef(ValueError):
    """Raised when a reference is not a recognised `<prefix><id>` pair."""


def parse_entity_ref(ref: str) -> tuple[str, int]:
    """Turn a UI reference into `(entity_type, entity_id)`.

    Accepts "S5124", "s5124" and "S-5124". A bare number is rejected rather
    than guessed at.
    """
    match = _REF_RE.match(ref or "")
    if not match:
        raise InvalidEntityRef(
            f"'{ref}' is not a valid entity reference — expected a prefix and an id, e.g. 'S5124'"
        )
    prefix, digits = match.group(1).upper(), match.group(2)
    if prefix not in REF_PREFIXES:
        known = ", ".join(sorted(REF_PREFIXES))
        raise InvalidEntityRef(f"Unknown entity prefix '{prefix}' — expected one of: {known}")
    return REF_PREFIXES[prefix], int(digits)


def normalise_ref(ref: str) -> str:
    """Canonical form of a reference: uppercase, no separator ("s-5124" → "S5124").

    One company must have exactly one stored reference, so casing and hyphen
    differences have to collapse before the value reaches the graph.
    """
    entity_type, entity_id = parse_entity_ref(ref)
    prefix = next(p for p, t in REF_PREFIXES.items() if t == entity_type)
    return f"{prefix}{entity_id}"
