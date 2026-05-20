"""
Re-run deal extraction on a single article by its ID.
Deletes the existing deal row (if any) and inserts a fresh one.

Usage:
    python reprocess_article.py <article_id>
"""

import os
import sys

import yaml
from dotenv import load_dotenv
from groq import Groq
from sqlalchemy import create_engine, text

from src.processor.extractor import DealExtractor

load_dotenv()


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Usage: python reprocess_article.py <article_id>")

    article_id = sys.argv[1]
    database_url = os.environ["DATABASE_URL"]
    groq_api_key = os.environ["GROQ_API_KEY"]
    settings = yaml.safe_load(open("config/settings.yaml"))
    model = settings["groq"]["model"]

    engine = create_engine(database_url)
    extractor = DealExtractor(Groq(api_key=groq_api_key), model)

    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT title, content FROM articles WHERE id = :id"),
            {"id": article_id},
        ).fetchone()

        if not row:
            sys.exit(f"Article {article_id} not found.")

        title, content = row
        print(f"Title   : {title}")
        print(f"Content : {(content or '')[:120]}...")
        print()

        deal = extractor.extract(title, content)
        if not deal:
            sys.exit("Extractor returned nothing — check logs.")

        print(f"buyer      : {deal.buyer}")
        print(f"seller     : {deal.seller}")
        print(f"deal_value : {deal.deal_value}")
        print(f"deal_type  : {deal.deal_type}")
        print(f"sector     : {deal.sector}")
        print(f"summary    : {deal.summary}")
        print()

        conn.execute(text("DELETE FROM deals WHERE article_id = :id"), {"id": article_id})
        conn.execute(
            text("""
                INSERT INTO deals (id, article_id, buyer, seller, deal_value,
                                   sector, sub_sector, country, deal_type, summary)
                VALUES (gen_random_uuid(), :article_id, :buyer, :seller, :deal_value,
                        :sector, :sub_sector, :country, :deal_type, :summary)
            """),
            {
                "article_id": article_id,
                "buyer": deal.buyer,
                "seller": deal.seller,
                "deal_value": deal.deal_value,
                "sector": deal.sector,
                "sub_sector": deal.sub_sector,
                "country": deal.country,
                "deal_type": deal.deal_type,
                "summary": deal.summary,
            },
        )

    print("Deal updated successfully.")


if __name__ == "__main__":
    main()
