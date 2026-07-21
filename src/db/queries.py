import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal, Optional
from uuid import UUID

from neo4j import Driver

from ..processor.company_signal import CompanySignalSnapshot
from .models import SCHEMA_CONSTRAINTS, SCHEMA_INDEXES


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


def _signal_row(record) -> dict:
    signal = dict(record["s"])
    for key in ("positive_signals", "negative_signals", "evidence_articles"):
        signal[key] = json.loads(signal.pop(f"{key}_json", "[]"))
    return signal


def ensure_signal_schema(conn: Neo4jConnection) -> None:
    with conn.session() as session:
        for stmt in SCHEMA_CONSTRAINTS + SCHEMA_INDEXES:
            if "CompanySignal" in stmt:
                session.run(stmt)


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
    days: Optional[int] = None,
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
    if days is not None:
        conditions.append("art.published_at >= $cutoff")
        params["cutoff"] = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with conn.session() as session:
        total = session.run(
            f"""
            MATCH (art:Article)-[:HAS_DEAL]->(d:Deal)
            {where}
            RETURN count(d) AS total
            """,
            **params,
        ).single()["total"]

        result = session.run(
            f"""
            MATCH (art:Article)-[:HAS_DEAL]->(d:Deal)
            {where}
            WITH d, art
            ORDER BY art.published_at DESC
            SKIP $offset LIMIT $limit
            OPTIONAL MATCH (c:Company)-[r]->(d)
            RETURN d, art.id AS article_id, art AS article,
                   collect(CASE WHEN c IS NOT NULL
                           THEN {{id: c.id, name: c.name, role: type(r)}}
                           END) AS companies
            """,
            **params,
            offset=offset,
            limit=limit,
        )
        items = [_deal_row_with_article(record) for record in result]

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
# Company signal queries
# ---------------------------------------------------------------------------

def get_company_signal_context(
    conn: Neo4jConnection,
    company_id: UUID,
    horizon_days: int = 30,
    article_limit: int = 60,
    deal_limit: int = 25,
) -> tuple[dict, list[dict], list[dict]]:
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=horizon_days)
    ).isoformat()

    with conn.session() as session:
        company_record = session.run(
            "MATCH (c:Company {id: $id}) RETURN c",
            id=str(company_id),
        ).single()
        if not company_record:
            return {}, [], []

        company = dict(company_record["c"])
        articles_result = session.run(
            """
            MATCH (c:Company {id: $company_id})
            OPTIONAL MATCH (c)-[]->(:Deal)<-[:HAS_DEAL]-(dealArticle:Article)
            WITH c, collect(DISTINCT dealArticle) AS dealArticles
            MATCH (a:Article)
            WHERE coalesce(a.published_at, a.scraped_at) >= $cutoff
              AND (
                toLower(coalesce(a.title, "")) CONTAINS toLower(c.name)
                OR toLower(coalesce(a.content, "")) CONTAINS toLower(c.name)
                OR a IN dealArticles
              )
            RETURN DISTINCT a
            ORDER BY coalesce(a.published_at, a.scraped_at) DESC
            LIMIT $limit
            """,
            company_id=str(company_id),
            cutoff=cutoff,
            limit=article_limit,
        )
        articles = [dict(record["a"]) for record in articles_result]

        deals_result = session.run(
            """
            MATCH (c:Company {id: $company_id})-[r]->(d:Deal)<-[:HAS_DEAL]-(a:Article)
            RETURN type(r) AS role,
                   d.deal_type AS deal_type,
                   d.summary AS summary,
                   d.deal_value AS deal_value,
                   d.extracted_at AS extracted_at,
                   a.id AS article_id,
                   a.title AS article_title
            ORDER BY d.extracted_at DESC
            LIMIT $limit
            """,
            company_id=str(company_id),
            limit=deal_limit,
        )
        deal_history = [dict(record) for record in deals_result]

    return company, articles, deal_history


def save_company_signal_snapshot(
    conn: Neo4jConnection,
    snapshot: CompanySignalSnapshot,
) -> dict:
    ensure_signal_schema(conn)
    data = snapshot.model_dump(mode="json")
    payload = {
        **data,
        "positive_signals_json": json.dumps(data.pop("positive_signals")),
        "negative_signals_json": json.dumps(data.pop("negative_signals")),
        "evidence_articles_json": json.dumps(data.pop("evidence_articles")),
    }
    payload.pop("positive_signals", None)
    payload.pop("negative_signals", None)
    payload.pop("evidence_articles", None)

    with conn.session() as session:
        record = session.run(
            """
            MATCH (c:Company {id: $company_id})
            CREATE (s:CompanySignal {
                id: $id,
                company_id: $company_id,
                company_name: $company_name,
                horizon_days: $horizon_days,
                generated_at: $generated_at,
                valid_until: $valid_until,
                invest_probability: $invest_probability,
                fundraise_probability: $fundraise_probability,
                acquisition_target_probability: $acquisition_target_probability,
                confidence: $confidence,
                direction: $direction,
                is_speculative: $is_speculative,
                articles_analyzed: $articles_analyzed,
                duplicates_collapsed: $duplicates_collapsed,
                positive_signals_json: $positive_signals_json,
                negative_signals_json: $negative_signals_json,
                evidence_articles_json: $evidence_articles_json,
                explanation: $explanation
            })
            CREATE (c)-[:HAS_SIGNAL]->(s)
            RETURN s
            """,
            **payload,
        ).single()

    return _signal_row(record)


def get_latest_company_signal(
    conn: Neo4jConnection,
    company_id: UUID,
) -> Optional[dict]:
    with conn.session() as session:
        record = session.run(
            """
            MATCH (:Company {id: $company_id})-[:HAS_SIGNAL]->(s:CompanySignal)
            RETURN s
            ORDER BY s.generated_at DESC
            LIMIT 1
            """,
            company_id=str(company_id),
        ).single()
    return _signal_row(record) if record else None


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
