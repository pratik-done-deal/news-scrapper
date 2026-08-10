"""
Batch re-run deal extraction on all articles that are M&A-relevant but
not yet processed (is_ma_relevant=TRUE, is_processed=FALSE).

These are articles where the LLM call failed (e.g. token limit) during
the original pipeline run, leaving no deal node in the database.

Usage:
    python reprocess_unprocessed.py [--dry-run] [--limit N] --neo4j-password ... --groq-api-key ...

Options:
    --dry-run   Print articles that would be processed without calling the LLM.
    --limit N   Process at most N articles (default: all).
    Plus the configuration overrides listed by --help.
"""

import argparse
import logging
import sys

from groq import Groq
from neo4j import GraphDatabase

from src.config import ConfigError, add_config_arguments, load_config
from src.db.repository import NewsRepository
from src.logging_config import setup_logging
from src.paths import load_settings
from src.processor.extractor import DealExtractor

logger = logging.getLogger(__name__)


def fetch_unprocessed(driver, database: str, limit: int | None) -> list[dict]:
    cypher = """
        MATCH (a:NewsArticle)
        WHERE a.is_ma_relevant = true AND a.is_processed = false
        RETURN a.id AS id, a.title AS title, a.content AS content
        ORDER BY a.scraped_at ASC
    """
    params = {}
    if limit:
        cypher += " LIMIT $limit"
        params["limit"] = limit

    with driver.session(database=database) as session:
        result = session.run(cypher, **params)
        return [{"id": r["id"], "title": r["title"], "content": r["content"]} for r in result]


def mark_processed(driver, database: str, article_id: str) -> None:
    with driver.session(database=database) as session:
        session.run(
            "MATCH (a:NewsArticle {id: $id}) SET a.is_processed = true",
            id=article_id,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="List articles without processing")
    parser.add_argument("--limit", type=int, default=None, help="Max articles to process")
    add_config_arguments(parser, only=("neo4j", "groq", "logging"))
    args = parser.parse_args()

    config = load_config(args)
    setup_logging()

    try:
        neo4j_password = config.require_neo4j_password()
        groq_api_key = config.require_groq_api_key()
    except ConfigError as exc:
        sys.exit(f"Error: {exc}")

    neo4j_uri      = config.neo4j.uri
    neo4j_user     = config.neo4j.user
    neo4j_database = config.neo4j.database

    settings = load_settings()
    model = settings["groq"]["model"]

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    try:
        articles = fetch_unprocessed(driver, neo4j_database, args.limit)

        if not articles:
            logger.info("No unprocessed M&A-relevant articles found.")
            return

        logger.info(f"Found {len(articles)} article(s) to reprocess.")

        if args.dry_run:
            for a in articles:
                logger.info(f"  [{a['id']}] {(a['title'] or '(no title)')[:100]}")
            return

        repo = NewsRepository(
            uri=neo4j_uri,
            user=neo4j_user,
            password=neo4j_password,
            database=neo4j_database,
        )
        extractor = DealExtractor(Groq(api_key=groq_api_key), model)

        success = skipped = failed = 0

        for i, a in enumerate(articles, 1):
            article_id = a["id"]
            title      = a["title"]
            content    = a["content"]
            logger.info(f"[{i}/{len(articles)}] {(title or '(no title)')[:80]}")

            deal = extractor.extract(title, content)

            if not deal:
                logger.warning("  -> Extractor returned nothing, skipping.")
                failed += 1
                continue

            if not any([deal.buyer, deal.seller, deal.sector, deal.deal_type]):
                logger.info("  -> LLM says not a deal article, marking processed.")
                mark_processed(driver, neo4j_database, article_id)
                skipped += 1
                continue

            repo.save_deal(
                article_id=article_id,
                buyer=deal.buyer,
                seller=deal.seller,
                target_company=deal.target_company,
                deal_value=deal.deal_value,
                sector=deal.sector,
                sub_sector=deal.sub_sector,
                country=deal.country,
                deal_type=deal.deal_type,
                summary=deal.summary,
            )
            logger.info(
                f"  -> Saved: [{deal.deal_type}] {deal.buyer or '?'} / {deal.seller or '?'}"
                f" — {deal.deal_value or 'value undisclosed'}"
            )
            success += 1

    finally:
        driver.close()

    logger.info(
        f"\nDone — success: {success}, not-a-deal: {skipped}, failed: {failed}"
        f" (out of {len(articles)} articles)"
    )


if __name__ == "__main__":
    main()
