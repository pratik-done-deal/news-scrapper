#!/usr/bin/env python3
"""
One-time migration: PostgreSQL → Neo4j

Reads every row from Postgres and writes it to Neo4j using UNWIND batch queries.
The script is fully idempotent — safe to re-run if interrupted.

Required env vars (can be in .env):
  PG_DATABASE_URL   postgresql connection string
                    e.g. postgresql://newsuser:password@localhost:5432/news_db
  NEO4J_URI         bolt URI   (default: neo4j://127.0.0.1:7687)
  NEO4J_USER        username   (default: neo4j)
  NEO4J_PASSWORD    password
  NEO4J_DATABASE    database   (default: newsscrapedatabase)

Usage:
  python migrate_pg_to_neo4j.py
  python migrate_pg_to_neo4j.py --dry-run          # count rows only, no writes
  python migrate_pg_to_neo4j.py --batch-size 200
"""

import argparse
import logging
import os
import sys
import uuid
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

_ROLE_TO_REL = {
    "buyer":    "BOUGHT",
    "seller":   "SOLD",
    "investor": "INVESTED_IN",
    "company":  "INVOLVED_IN",
}


def _company_id(name: str) -> str:
    """Deterministic UUID5 — must match the logic in repository.py."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, name))


def _iso(value) -> str | None:
    """Convert a datetime (or None) to an ISO string for storage in Neo4j."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


# ---------------------------------------------------------------------------
# Per-entity migrators
# ---------------------------------------------------------------------------

def _migrate_articles(cur, neo4j_session, batch_size: int) -> int:
    cur.execute("SELECT id, url, url_hash, source, title, content, scraped_at, published_at, is_ma_relevant, is_processed FROM articles")
    total = 0
    while True:
        rows = cur.fetchmany(batch_size)
        if not rows:
            break
        batch = [
            {
                "id":            str(r[0]),
                "url":           r[1],
                "url_hash":      r[2],
                "source":        r[3],
                "title":         r[4],
                "content":       r[5],
                "scraped_at":    _iso(r[6]),
                "published_at":  _iso(r[7]),
                "is_ma_relevant": r[8],
                "is_processed":  r[9],
            }
            for r in rows
        ]
        neo4j_session.run(
            """
            UNWIND $rows AS row
            MERGE (a:Article {id: row.id})
            SET a.url            = row.url,
                a.url_hash       = row.url_hash,
                a.source         = row.source,
                a.title          = row.title,
                a.content        = row.content,
                a.scraped_at     = row.scraped_at,
                a.published_at   = row.published_at,
                a.is_ma_relevant = row.is_ma_relevant,
                a.is_processed   = row.is_processed
            """,
            rows=batch,
        )
        total += len(batch)
        logger.info(f"  articles — {total} rows written")
    return total


def _migrate_deals(cur, neo4j_session, batch_size: int) -> int:
    cur.execute(
        "SELECT id, article_id, deal_value, sector, sub_sector, country, deal_type, summary, extracted_at FROM deals"
    )
    total = 0
    while True:
        rows = cur.fetchmany(batch_size)
        if not rows:
            break
        batch = [
            {
                "id":           str(r[0]),
                "article_id":   str(r[1]),
                "deal_value":   r[2],
                "sector":       r[3],
                "sub_sector":   r[4],
                "country":      r[5],
                "deal_type":    r[6],
                "summary":      r[7],
                "extracted_at": _iso(r[8]),
            }
            for r in rows
        ]
        # Create Deal nodes and link to their Article in one query
        neo4j_session.run(
            """
            UNWIND $rows AS row
            MERGE (d:Deal {id: row.id})
            SET d.deal_value   = row.deal_value,
                d.sector       = row.sector,
                d.sub_sector   = row.sub_sector,
                d.country      = row.country,
                d.deal_type    = row.deal_type,
                d.summary      = row.summary,
                d.extracted_at = row.extracted_at
            WITH d, row
            MATCH (a:Article {id: row.article_id})
            MERGE (a)-[:HAS_DEAL]->(d)
            """,
            rows=batch,
        )
        total += len(batch)
        logger.info(f"  deals — {total} rows written")
    return total


def _migrate_company_deals(cur, neo4j_session, batch_size: int) -> int:
    cur.execute(
        """
        SELECT c.name, cd.deal_id, cd.role
        FROM company_deals cd
        JOIN companies c ON c.id = cd.company_id
        """
    )
    total = 0
    # Group by relationship type so we can use a fixed rel-type in each UNWIND
    by_rel: dict[str, list[dict]] = {rel: [] for rel in _ROLE_TO_REL.values()}

    while True:
        rows = cur.fetchmany(batch_size)
        if not rows:
            # Flush remaining
            for rel_type, batch in by_rel.items():
                if batch:
                    total += _write_company_rel_batch(neo4j_session, rel_type, batch)
                    by_rel[rel_type] = []
            break

        for company_name, deal_id, role in rows:
            rel_type = _ROLE_TO_REL.get(role)
            if not rel_type:
                logger.warning(f"Unknown role '{role}' for company '{company_name}' — skipping")
                continue
            by_rel[rel_type].append({
                "company_name": company_name,
                "company_id":   _company_id(company_name),
                "deal_id":      str(deal_id),
            })

        # Flush each bucket when it hits batch_size
        for rel_type, batch in by_rel.items():
            if len(batch) >= batch_size:
                total += _write_company_rel_batch(neo4j_session, rel_type, batch)
                by_rel[rel_type] = []

    logger.info(f"  company relationships — {total} rows written")
    return total


def _write_company_rel_batch(neo4j_session, rel_type: str, batch: list[dict]) -> int:
    neo4j_session.run(
        f"""
        UNWIND $rows AS row
        MERGE (c:Company {{name: row.company_name}})
        ON CREATE SET c.id = row.company_id
        WITH c, row
        MATCH (d:Deal {{id: row.deal_id}})
        MERGE (c)-[:{rel_type}]->(d)
        """,
        rows=batch,
    )
    return len(batch)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def migrate(pg_url: str, batch_size: int, dry_run: bool) -> None:
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        logger.error("psycopg2 is not installed. Run: pip install psycopg2-binary")
        sys.exit(1)

    from neo4j import GraphDatabase
    from src.db.models import SCHEMA_CONSTRAINTS, SCHEMA_INDEXES

    neo4j_uri      = os.environ.get("NEO4J_URI", "neo4j://127.0.0.1:7687")
    neo4j_user     = os.environ.get("NEO4J_USER", "neo4j")
    neo4j_password = os.environ["NEO4J_PASSWORD"]
    neo4j_database = os.environ.get("NEO4J_DATABASE", "newsscrapedatabase")

    logger.info(f"Connecting to PostgreSQL …")
    pg_conn = psycopg2.connect(pg_url)
    psycopg2.extras.register_uuid()

    logger.info(f"Connecting to Neo4j at {neo4j_uri} / db={neo4j_database} …")
    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    try:
        with pg_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM articles")
            n_articles = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM deals")
            n_deals = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM company_deals")
            n_cd = cur.fetchone()[0]

        logger.info(
            f"PostgreSQL row counts — articles: {n_articles}, "
            f"deals: {n_deals}, company_deals: {n_cd}"
        )

        if dry_run:
            logger.info("Dry-run mode — no data written to Neo4j.")
            return

        with driver.session(database=neo4j_database) as session:
            logger.info("Applying schema constraints and indexes …")
            for stmt in SCHEMA_CONSTRAINTS + SCHEMA_INDEXES:
                session.run(stmt)

            with pg_conn.cursor() as cur:
                logger.info(f"Migrating articles (batch={batch_size}) …")
                _migrate_articles(cur, session, batch_size)

                logger.info(f"Migrating deals (batch={batch_size}) …")
                _migrate_deals(cur, session, batch_size)

                logger.info(f"Migrating company relationships (batch={batch_size}) …")
                _migrate_company_deals(cur, session, batch_size)

        logger.info("Migration complete.")

    finally:
        pg_conn.close()
        driver.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate data from PostgreSQL to Neo4j")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count rows in Postgres only; do not write to Neo4j",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        metavar="N",
        help="Rows per UNWIND batch (default: 100)",
    )
    args = parser.parse_args()

    pg_url = os.environ.get("PG_DATABASE_URL")
    if not pg_url:
        logger.error(
            "PG_DATABASE_URL is not set.\n"
            "Add it to .env: PG_DATABASE_URL=postgresql://user:pass@host:5432/dbname"
        )
        sys.exit(1)

    migrate(pg_url=pg_url, batch_size=args.batch_size, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
