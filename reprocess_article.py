"""
Re-run deal extraction on a single article by its ID.
Deletes any existing Deal node(s) for the article and inserts a fresh one.

Usage:
    python reprocess_article.py <article_id>
"""

import os
import sys

import yaml
from dotenv import load_dotenv
from groq import Groq
from neo4j import GraphDatabase

from src.db.repository import NewsRepository
from src.processor.extractor import DealExtractor

load_dotenv()


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Usage: python reprocess_article.py <article_id>")

    article_id     = sys.argv[1]
    neo4j_uri      = os.environ.get("NEO4J_URI", "neo4j://127.0.0.1:7687")
    neo4j_user     = os.environ.get("NEO4J_USER", "neo4j")
    neo4j_password = os.environ["NEO4J_PASSWORD"]
    neo4j_database = os.environ.get("NEO4J_DATABASE", "newsscrapedatabase")
    groq_api_key   = os.environ["GROQ_API_KEY"]

    settings = yaml.safe_load(open("config/settings.yaml"))
    model = settings["groq"]["model"]

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    try:
        # Fetch article content
        with driver.session(database=neo4j_database) as session:
            record = session.run(
                "MATCH (a:Article {id: $id}) RETURN a.title AS title, a.content AS content",
                id=article_id,
            ).single()

        if not record:
            sys.exit(f"Article {article_id} not found.")

        title   = record["title"]
        content = record["content"]
        print(f"Title   : {title}")
        print(f"Content : {(content or '')[:120]}...")
        print()

        extractor = DealExtractor(Groq(api_key=groq_api_key), model)
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
                "MATCH (a:Article {id: $id})-[:HAS_DEAL]->(d:Deal) DETACH DELETE d",
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
