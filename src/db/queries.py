from datetime import date, datetime, time, timezone
from typing import Literal, Optional
from uuid import UUID

from neo4j import Driver


class Neo4jConnection:
    """Pairs a Driver with a target database name, mirroring the Engine pattern."""

    def __init__(self, driver: Driver, database: str) -> None:
        self.driver = driver
        self.database = database

    def session(self):
        return self.driver.session(database=self.database)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _deal_row(record) -> dict:
    deal = dict(record["d"])
    deal["article_id"] = record["article_id"]
    deal["companies"] = [
        {"id": c["id"], "name": c["name"], "role": c["role"]}
        for c in record["companies"]
        if c.get("id") is not None
    ]
    return deal


def _deal_row_with_article(record) -> dict:
    deal = _deal_row(record)
    art = record.get("article")
    deal["article"] = dict(art) if art else None
    return deal


# ---------------------------------------------------------------------------
# Article queries
# ---------------------------------------------------------------------------

def list_articles(
    conn: Neo4jConnection,
    source: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    is_ma_funding_relevant: Optional[bool] = None,
    offset: int = 0,
    limit: int = 20,
) -> tuple[int, list[dict]]:
    conditions = []
    params: dict = {}

    if source:
        conditions.append("a.source = $source")
        params["source"] = source
    if date_from:
        params["date_from"] = datetime.combine(date_from, time.min).replace(tzinfo=timezone.utc).isoformat()
        conditions.append("a.published_at >= $date_from")
    if date_to:
        params["date_to"] = datetime.combine(date_to, time(23, 59, 59)).replace(tzinfo=timezone.utc).isoformat()
        conditions.append("a.published_at <= $date_to")
    if is_ma_funding_relevant is not None:
        conditions.append("a.is_ma_funding_relevant = $is_ma_funding_relevant")
        params["is_ma_funding_relevant"] = is_ma_funding_relevant

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with conn.session() as session:
        total = session.run(
            f"MATCH (a:Article) {where} RETURN count(a) AS total", **params
        ).single()["total"]

        result = session.run(
            f"""
            MATCH (a:Article)
            {where}
            RETURN a
            ORDER BY a.published_at DESC
            SKIP $offset LIMIT $limit
            """,
            **params,
            offset=offset,
            limit=limit,
        )
        items = [dict(record["a"]) for record in result]

    return total, items


def get_article(conn: Neo4jConnection, article_id: UUID) -> Optional[dict]:
    with conn.session() as session:
        record = session.run(
            "MATCH (a:Article {id: $id}) RETURN a", id=str(article_id)
        ).single()
        return dict(record["a"]) if record else None


# ---------------------------------------------------------------------------
# Deal queries
# ---------------------------------------------------------------------------

def list_deals(
    conn: Neo4jConnection,
    sector: Optional[str] = None,
    deal_type: Optional[str] = None,
    offset: int = 0,
    limit: int = 20,
) -> tuple[int, list[dict]]:
    conditions = []
    params: dict = {}

    if sector:
        conditions.append("toLower(d.sector) CONTAINS toLower($sector)")
        params["sector"] = sector
    if deal_type:
        conditions.append("toLower(d.deal_type) CONTAINS toLower($deal_type)")
        params["deal_type"] = deal_type

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with conn.session() as session:
        total = session.run(
            f"MATCH (d:Deal) {where} RETURN count(d) AS total", **params
        ).single()["total"]

        result = session.run(
            f"""
            MATCH (art:Article)-[:HAS_DEAL]->(d:Deal)
            {where}
            WITH d, art.id AS article_id
            ORDER BY d.extracted_at DESC
            SKIP $offset LIMIT $limit
            OPTIONAL MATCH (c:Company)-[r]->(d)
            RETURN d, article_id,
                   collect(CASE WHEN c IS NOT NULL
                           THEN {{id: c.id, name: c.name, role: type(r)}}
                           END) AS companies
            """,
            **params,
            offset=offset,
            limit=limit,
        )
        items = [_deal_row(record) for record in result]

    return total, items


def get_deal(conn: Neo4jConnection, deal_id: UUID) -> Optional[dict]:
    with conn.session() as session:
        record = session.run(
            """
            MATCH (art:Article)-[:HAS_DEAL]->(d:Deal {id: $id})
            OPTIONAL MATCH (c:Company)-[r]->(d)
            RETURN d, art.id AS article_id,
                   collect(CASE WHEN c IS NOT NULL
                           THEN {id: c.id, name: c.name, role: type(r)}
                           END) AS companies
            """,
            id=str(deal_id),
        ).single()
        return _deal_row(record) if record else None


def get_company(conn: Neo4jConnection, company_id: UUID) -> Optional[dict]:
    with conn.session() as session:
        record = session.run(
            "MATCH (c:Company {id: $id}) RETURN c", id=str(company_id)
        ).single()
        return dict(record["c"]) if record else None


def get_deals_by_company_name(
    conn: Neo4jConnection,
    name: str,
    offset: int = 0,
    limit: int = 20,
) -> tuple[int, list[dict]]:
    with conn.session() as session:
        total = session.run(
            """
            MATCH (c:Company)-[]->(d:Deal)
            WHERE toLower(c.name) CONTAINS toLower($name)
            RETURN count(DISTINCT d) AS total
            """,
            name=name,
        ).single()["total"]

        result = session.run(
            """
            MATCH (c:Company)-[]->(d:Deal)<-[:HAS_DEAL]-(art:Article)
            WHERE toLower(c.name) CONTAINS toLower($name)
            WITH DISTINCT d, art
            ORDER BY d.extracted_at DESC
            SKIP $offset LIMIT $limit
            OPTIONAL MATCH (co:Company)-[r]->(d)
            RETURN d, art.id AS article_id, art AS article,
                   collect(CASE WHEN co IS NOT NULL
                           THEN {id: co.id, name: co.name, role: type(r)}
                           END) AS companies
            """,
            name=name,
            offset=offset,
            limit=limit,
        )
        items = [_deal_row_with_article(record) for record in result]

    return total, items


def get_deals_by_company(
    conn: Neo4jConnection,
    company_id: UUID,
    offset: int = 0,
    limit: int = 20,
) -> tuple[int, list[dict]]:
    with conn.session() as session:
        total = session.run(
            """
            MATCH (c:Company {id: $company_id})-[]->(d:Deal)
            RETURN count(d) AS total
            """,
            company_id=str(company_id),
        ).single()["total"]

        result = session.run(
            """
            MATCH (c:Company {id: $company_id})-[]->(d:Deal)<-[:HAS_DEAL]-(art:Article)
            WITH d, art
            ORDER BY d.extracted_at DESC
            SKIP $offset LIMIT $limit
            OPTIONAL MATCH (co:Company)-[r]->(d)
            RETURN d, art.id AS article_id, art AS article,
                   collect(CASE WHEN co IS NOT NULL
                           THEN {id: co.id, name: co.name, role: type(r)}
                           END) AS companies
            """,
            company_id=str(company_id),
            offset=offset,
            limit=limit,
        )
        items = [_deal_row_with_article(record) for record in result]

    return total, items


# ---------------------------------------------------------------------------
# Analytics queries
# ---------------------------------------------------------------------------

def analytics_deals_by_sector(conn: Neo4jConnection) -> list[dict]:
    with conn.session() as session:
        result = session.run(
            """
            MATCH (d:Deal)
            WHERE d.sector IS NOT NULL
            RETURN d.sector AS sector, count(d) AS deal_count
            ORDER BY deal_count DESC
            """
        )
        return [{"sector": r["sector"], "deal_count": r["deal_count"]} for r in result]


def analytics_top_buyers(
    conn: Neo4jConnection,
    role: str = "buyer",
    limit: int = 10,
) -> list[dict]:
    rel_map = {
        "buyer": "BOUGHT",
        "seller": "SOLD",
        "investor": "INVESTED_IN",
        "company": "INVOLVED_IN",
    }
    rel_type = rel_map.get(role, "BOUGHT")

    with conn.session() as session:
        result = session.run(
            f"""
            MATCH (c:Company)-[:{rel_type}]->(d:Deal)
            RETURN c.id AS company_id, c.name AS company_name, count(d) AS deal_count
            ORDER BY deal_count DESC
            LIMIT $limit
            """,
            limit=limit,
        )
        return [
            {"company_id": r["company_id"], "company_name": r["company_name"], "deal_count": r["deal_count"]}
            for r in result
        ]


def analytics_deal_volume(
    conn: Neo4jConnection,
    group_by: Literal["day", "month", "year"] = "month",
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> list[dict]:
    # ISO string prefix lengths: day=10 (2024-01-15), month=7 (2024-01), year=4 (2024)
    trunc_len = {"day": 10, "month": 7, "year": 4}[group_by]

    conditions = ["a.published_at IS NOT NULL"]
    params: dict = {"trunc_len": trunc_len}

    if date_from:
        params["date_from"] = datetime.combine(date_from, time.min).replace(tzinfo=timezone.utc).isoformat()
        conditions.append("a.published_at >= $date_from")
    if date_to:
        params["date_to"] = datetime.combine(date_to, time(23, 59, 59)).replace(tzinfo=timezone.utc).isoformat()
        conditions.append("a.published_at <= $date_to")

    where = "WHERE " + " AND ".join(conditions)

    with conn.session() as session:
        result = session.run(
            f"""
            MATCH (a:Article)-[:HAS_DEAL]->(d:Deal)
            {where}
            RETURN substring(a.published_at, 0, $trunc_len) AS period, count(d) AS deal_count
            ORDER BY period ASC
            """,
            **params,
        )
        return [{"period": r["period"], "deal_count": r["deal_count"]} for r in result]
