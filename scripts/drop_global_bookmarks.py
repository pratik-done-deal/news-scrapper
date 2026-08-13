"""
One-time migration: retire the global `NewsDeal.is_bookmarked` property.

A bookmark used to be a boolean on the deal node, which meant there was one
bookmark bit per deal for the entire service — whoever bookmarked a news item
bookmarked it for everybody. Bookmarks are now edges,
`(:NewsUser {user_id})-[:BOOKMARKED]->(:NewsDeal)`, so the old property is dead
weight that only misleads.

The existing values are *deleted, not converted*: the property records that
someone bookmarked the deal but not who, and there is no honest way to guess an
owner. Everyone starts with an empty bookmark list.

Idempotent — safe to re-run, and a no-op once the property is gone. The API
tolerates a graph that has not run this yet (`_bookmarked_flag` in queries.py
discards the stale property), so this is cleanup rather than a prerequisite.

Usage:
    python scripts/drop_global_bookmarks.py --neo4j-password <password>
    python scripts/drop_global_bookmarks.py --neo4j-password <pw> --dry-run
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import ConfigError, add_config_arguments, load_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# The index that only ever served the old property. Dropped by name because
# `SCHEMA_INDEXES` no longer creates it, so nothing would replace it.
STALE_INDEX = "news_deal_is_bookmarked"

COUNT_BOOKMARKED = """
    MATCH (d:NewsDeal) WHERE d.is_bookmarked = true RETURN count(d) AS total
"""
COUNT_PROPERTY = """
    MATCH (d:NewsDeal) WHERE d.is_bookmarked IS NOT NULL RETURN count(d) AS total
"""
# Batched so a large graph is not held in one transaction.
REMOVE_PROPERTY = """
    MATCH (d:NewsDeal) WHERE d.is_bookmarked IS NOT NULL
    CALL (d) {
        REMOVE d.is_bookmarked
    } IN TRANSACTIONS OF 1000 ROWS
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--dry-run", action="store_true", help="Report what would be cleared, write nothing"
    )
    add_config_arguments(parser, only=("neo4j",))
    args = parser.parse_args()

    try:
        config = load_config(args)
        password = config.require_neo4j_password()
    except ConfigError as exc:
        logger.error(str(exc))
        return 1

    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(config.neo4j.uri, auth=(config.neo4j.user, password))
    try:
        with driver.session(database=config.neo4j.database) as session:
            carrying = session.run(COUNT_PROPERTY).single()["total"]
            bookmarked = session.run(COUNT_BOOKMARKED).single()["total"]
            logger.info(
                "%s deals carry is_bookmarked, %s of them set to true", carrying, bookmarked
            )

            if args.dry_run:
                logger.info("Dry run — nothing written. Would drop index %s.", STALE_INDEX)
                return 0

            if carrying:
                session.run(REMOVE_PROPERTY).consume()
            session.run(f"DROP INDEX {STALE_INDEX} IF EXISTS").consume()

            remaining = session.run(COUNT_PROPERTY).single()["total"]
            if remaining:
                logger.error("%s deals still carry is_bookmarked — re-run", remaining)
                return 1

        logger.info("Cleared %s deals and dropped index %s", carrying, STALE_INDEX)
        return 0
    finally:
        driver.close()


if __name__ == "__main__":
    sys.exit(main())
