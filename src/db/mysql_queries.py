"""Read queries against the company MySQL database.

Mirrors the Neo4j split: `mysql_dao.py` owns the pool and the read-only guard,
this module owns the SQL that business logic runs.

Three tables hold the companies the business tracks — `company` (sellers),
`buyer`, and `leads` — each with its own column names and active-record filter.
Every query here projects them onto one shape so callers do not repeat the
filters:

    {entity_type, entity_id, company_name, brand_name, website}

`entity_id` is only unique within a table, so the identity of a row is the
`(entity_type, entity_id)` pair.
"""

from datetime import datetime
from typing import Iterable, Optional, Sequence

from .mysql_dao import MySQLDAO

SELLER = "seller"
BUYER = "buyer"
LEAD = "lead"
ENTITY_TYPES = (SELLER, BUYER, LEAD)

# Statuses that mean "not a live record". Kept here rather than inline so the
# business rule is visible in one place.
_SELLER_EXCLUDED_STATUSES = ("junk", "archived", "delist", "Inactive")
_LEAD_EXCLUDED_STATUSES = ("DROPPED", "CONVERTED")
_LEAD_ID_TYPES = ("seller_lead", "buyer_lead")


def _placeholders(values: Sequence) -> str:
    return ", ".join(["%s"] * len(values))


# Each entry is (SELECT ... FROM ... WHERE <active filter>, params, name_column).
# `brand_name` only exists on `company`; the other two select NULL so the
# UNION keeps one column list.
def _seller_source() -> tuple[str, list]:
    sql = f"""
        SELECT '{SELLER}' AS entity_type,
               c.id         AS entity_id,
               c.name       AS company_name,
               c.brand_name AS brand_name,
               c.website    AS website
        FROM company c
        WHERE TRIM(COALESCE(c.name, '')) <> ''
          AND (c.status IS NULL OR c.status NOT IN ({_placeholders(_SELLER_EXCLUDED_STATUSES)}))
    """
    return sql, list(_SELLER_EXCLUDED_STATUSES)


def _buyer_source() -> tuple[str, list]:
    sql = f"""
        SELECT '{BUYER}' AS entity_type,
               b.id           AS entity_id,
               b.company_name AS company_name,
               NULL           AS brand_name,
               b.website      AS website
        FROM buyer b
        WHERE TRIM(COALESCE(b.company_name, '')) <> ''
    """
    return sql, []


def _lead_source() -> tuple[str, list]:
    sql = f"""
        SELECT '{LEAD}' AS entity_type,
               l.id      AS entity_id,
               l.name    AS company_name,
               NULL      AS brand_name,
               l.website AS website
        FROM leads l
        WHERE l.primary_id_type IN ({_placeholders(_LEAD_ID_TYPES)})
          AND TRIM(COALESCE(l.name, '')) <> ''
          AND l.status NOT IN ({_placeholders(_LEAD_EXCLUDED_STATUSES)})
    """
    return sql, [*_LEAD_ID_TYPES, *_LEAD_EXCLUDED_STATUSES]


_SOURCES = {
    SELLER: _seller_source,
    BUYER: _buyer_source,
    LEAD: _lead_source,
}

# Columns a name search looks at, per source. Only `company` has a brand name.
_NAME_COLUMNS = {
    SELLER: ("c.name", "c.brand_name"),
    BUYER: ("b.company_name",),
    LEAD: ("l.name",),
}

# Row-creation timestamp per source, used to pull only newly added entities.
_CREATED_COLUMNS = {
    SELLER: "c.created_at",
    BUYER: "b.created_at",
    LEAD: "l.created_at",
}


def _escape_like(term: str) -> str:
    """Escape LIKE wildcards so a user-typed `%` matches a literal percent."""
    return term.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


def _resolve_types(entity_types: Optional[Iterable[str]]) -> list[str]:
    if entity_types is None:
        return list(ENTITY_TYPES)
    resolved = [t for t in entity_types]
    unknown = [t for t in resolved if t not in _SOURCES]
    if unknown:
        raise ValueError(f"Unknown entity type(s): {', '.join(unknown)}")
    if not resolved:
        raise ValueError("entity_types must not be empty")
    return resolved


def _union_query(
    entity_types: Optional[Iterable[str]],
    name_like: Optional[str],
    created_since: Optional[datetime] = None,
) -> tuple[str, list]:
    """Build the UNION ALL over the requested entity sources, with the optional
    name and created-since filters applied inside each branch so table indexes
    can serve them."""
    parts: list[str] = []
    params: list = []
    for entity_type in _resolve_types(entity_types):
        sql, source_params = _SOURCES[entity_type]()
        params.extend(source_params)
        if created_since is not None:
            sql += f" AND {_CREATED_COLUMNS[entity_type]} >= %s"
            params.append(created_since)
        if name_like:
            # `company_name` is a projection alias and is not usable in WHERE,
            # so filter the underlying columns of each branch. Sellers also
            # match on brand_name: press coverage uses "Ola", not the
            # registered "ANI Technologies Private Limited".
            columns = _NAME_COLUMNS[entity_type]
            term = f"%{_escape_like(name_like)}%"
            predicate = " OR ".join(f"{col} LIKE %s ESCAPE '\\\\'" for col in columns)
            sql += f" AND ({predicate})"
            params.extend([term] * len(columns))
        parts.append(f"({sql.strip()})")
    return "\n        UNION ALL\n        ".join(parts), params


def fetch_entities(
    dao: MySQLDAO,
    entity_types: Optional[Iterable[str]] = None,
    name_like: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
    created_since: Optional[datetime] = None,
) -> list[dict]:
    """Active sellers, buyers, and leads in one normalized list.

    `entity_types` narrows the sources (default: all three). `name_like` does a
    substring match on the company name. `created_since` keeps only rows added
    on or after that moment. Rows are ordered by name so paging with
    `limit`/`offset` is stable.
    """
    union_sql, params = _union_query(entity_types, name_like, created_since)
    sql = f"""
        SELECT entity_type, entity_id, company_name, brand_name, website
        FROM (
        {union_sql}
        ) AS entities
        ORDER BY company_name, entity_type, entity_id
    """
    if limit is not None:
        sql += " LIMIT %s OFFSET %s"
        params.extend([max(0, int(limit)), max(0, int(offset))])
    return dao.fetch_all(sql, params)


def count_entities(
    dao: MySQLDAO,
    entity_types: Optional[Iterable[str]] = None,
    name_like: Optional[str] = None,
    created_since: Optional[datetime] = None,
) -> int:
    """Total rows `fetch_entities()` would return without paging."""
    union_sql, params = _union_query(entity_types, name_like, created_since)
    sql = f"""
        SELECT COUNT(*) AS total
        FROM (
        {union_sql}
        ) AS entities
    """
    return int(dao.fetch_value(sql, params, default=0) or 0)


def fetch_sellers(dao: MySQLDAO, **kwargs) -> list[dict]:
    """Active records from `company`."""
    return fetch_entities(dao, entity_types=[SELLER], **kwargs)


def fetch_buyers(dao: MySQLDAO, **kwargs) -> list[dict]:
    """Records from `buyer` with a non-empty company name."""
    return fetch_entities(dao, entity_types=[BUYER], **kwargs)


def fetch_leads(dao: MySQLDAO, **kwargs) -> list[dict]:
    """Seller/buyer leads that are neither dropped nor converted."""
    return fetch_entities(dao, entity_types=[LEAD], **kwargs)


def fetch_watchlist(
    dao: MySQLDAO,
    created_since: Optional[datetime] = None,
    entity_types: Optional[Iterable[str]] = None,
    limit: Optional[int] = None,
    offset: int = 0,
) -> list[dict]:
    """The entities a news run should be restricted to.

    With `created_since` this is the incremental slice — the companies added to
    the company DB since that moment, which is what a nightly run searches for.
    Without it, the full tracked universe, which is what the listing-source
    entity gate matches against.

    Returns raw rows; `src/processor/watchlist.py` turns them into search terms.
    """
    return fetch_entities(
        dao,
        entity_types=entity_types,
        limit=limit,
        offset=offset,
        created_since=created_since,
    )


def search_entities_by_name(dao: MySQLDAO, name: str, limit: int = 25) -> list[dict]:
    """Substring search across all three sources — the lookup path for matching
    a scraped company name back to a company DB record."""
    name = (name or "").strip()
    if not name:
        return []
    return fetch_entities(dao, name_like=name, limit=limit)


def fetch_entity_names(
    dao: MySQLDAO,
    entity_types: Optional[Iterable[str]] = None,
) -> list[str]:
    """Distinct company names, for feeding company-specific scrape runs.

    Brand names are included when they differ from the registered name, since
    news coverage usually uses the brand.
    """
    names: list[str] = []
    seen: set[str] = set()
    for row in fetch_entities(dao, entity_types=entity_types):
        for value in (row.get("company_name"), row.get("brand_name")):
            if not value:
                continue
            cleaned = str(value).strip()
            key = cleaned.casefold()
            if cleaned and key not in seen:
                seen.add(key)
                names.append(cleaned)
    return names
