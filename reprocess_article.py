"""
Re-run deal extraction on a single article by its ID.
Deletes any existing Deal node(s) for the article and inserts a fresh one.

Usage:
    python reprocess_article.py <article_id> --neo4j-password ... --groq-api-key ...
"""

import argparse
import sys

from neo4j import GraphDatabase

from src.config import ConfigError, add_config_arguments, load_config
from src.db.repository import NewsRepository
from src.llm_client import create_llm_client
from src.paths import load_settings
from src.processor.extractor import DealExtractor


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-run deal extraction on one article")
    parser.add_argument("article_id", help="Article node id")
    add_config_arguments(parser, only=("neo4j", "groq", "logging"))
    args = parser.parse_args()

    config = load_config(args)
    article_id = args.article_id
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
        # Fetch article content
        with driver.session(database=neo4j_database) as session:
            record = session.run(
                "MATCH (a:NewsArticle {id: $id}) RETURN a.title AS title, a.content AS content",
                id=article_id,
            ).single()

        if not record:
            sys.exit(f"Article {article_id} not found.")

        title   = record["title"]
        content = record["content"]
        print(f"Title   : {title}")
        print(f"Content : {(content or '')[:120]}...")
        print()

        extractor = DealExtractor(create_llm_client(groq_api_key, settings), model)
        deal = extractor.extract(title, content)

        if not deal:
            sys.exit("Extractor returned nothing — check logs.")

        print(f"buyer      : {deal.buyer}")
        print(f"seller     : {deal.seller}")
        print(f"target     : {deal.target_company}")
        print(f"deal_value : {deal.deal_value}")
        print(f"deal_type  : {deal.deal_type}")
        print(f"sector     : {deal.sector}")
        print(f"summary    : {deal.summary}")
        print()

        # Delete existing Deal node(s) for this article (DETACH removes all relationships)
        with driver.session(database=neo4j_database) as session:
            session.run(
                "MATCH (a:NewsArticle {id: $id})-[:HAS_DEAL]->(d:NewsDeal) DETACH DELETE d",
                id=article_id,
            )

        # Create fresh Deal node via the repository (handles companies + relationships)
        repo = NewsRepository(
            uri=neo4j_uri,
            user=neo4j_user,
            password=neo4j_password,
            database=neo4j_database,
        )
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

    finally:
        driver.close()

    print("Deal updated successfully.")


if __name__ == "__main__":
    main()
