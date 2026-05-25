"""
Batch re-run deal extraction on all articles that are M&A-relevant but
not yet processed (is_ma_relevant=TRUE, is_processed=FALSE).

These are articles where the LLM call failed (e.g. token limit) during
the original pipeline run, leaving no deal row in the database.

Usage:
    python reprocess_unprocessed.py [--dry-run] [--limit N]

Options:
    --dry-run   Print articles that would be processed without calling the LLM.
    --limit N   Process at most N articles (default: all).
"""

import argparse
import logging
import os
import sys

import yaml
from dotenv import load_dotenv
from groq import Groq
from sqlalchemy import create_engine, text

from src.db.repository import NewsRepository
from src.processor.extractor import DealExtractor

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def fetch_unprocessed(conn, limit: int | None) -> list[dict]:
    query = """
        SELECT id, title, content
        FROM articles
        WHERE is_ma_relevant = TRUE AND is_processed = FALSE
        ORDER BY scraped_at ASC
    """
    if limit:
        query += f" LIMIT {limit}"
    rows = conn.execute(text(query)).fetchall()
    return [{"id": str(r.id), "title": r.title, "content": r.content} for r in rows]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="List articles without processing")
    parser.add_argument("--limit", type=int, default=None, help="Max articles to process")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    groq_api_key = os.environ.get("GROQ_API_KEY")
    if not database_url or not groq_api_key:
        sys.exit("DATABASE_URL and GROQ_API_KEY must be set in environment.")

    settings = yaml.safe_load(open("config/settings.yaml"))
    model = settings["groq"]["model"]

    engine = create_engine(database_url)

    with engine.connect() as conn:
        articles = fetch_unprocessed(conn, args.limit)

    if not articles:
        logger.info("No unprocessed M&A-relevant articles found.")
        return

    logger.info(f"Found {len(articles)} article(s) to reprocess.")

    if args.dry_run:
        for a in articles:
            logger.info(f"  [{a['id']}] {(a['title'] or '(no title)')[:100]}")
        return

    repo = NewsRepository(database_url)
    extractor = DealExtractor(Groq(api_key=groq_api_key), model)

    success = 0
    failed = 0
    skipped = 0

    for i, a in enumerate(articles, 1):
        article_id = a["id"]
        title = a["title"]
        content = a["content"]
        logger.info(f"[{i}/{len(articles)}] {(title or '(no title)')[:80]}")

        deal = extractor.extract(title, content)

        if not deal:
            logger.warning(f"  -> Extractor returned nothing, skipping.")
            failed += 1
            continue

        if not any([deal.buyer, deal.seller, deal.sector, deal.deal_type]):
            # LLM returned all-null (not actually a deal article)
            logger.info(f"  -> LLM says not a deal article, marking processed.")
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE articles SET is_processed = TRUE WHERE id = :id"),
                    {"id": article_id},
                )
            skipped += 1
            continue

        repo.save_deal(
            article_id=article_id,
            buyer=deal.buyer,
            seller=deal.seller,
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

    logger.info(
        f"\nDone — success: {success}, not-a-deal: {skipped}, failed: {failed}"
        f" (out of {len(articles)} articles)"
    )


if __name__ == "__main__":
    main()
