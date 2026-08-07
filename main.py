import argparse
import os
import sys

from dotenv import load_dotenv

from src.agent import NewsAgent
from src.logging_config import setup_logging
from src.paths import ENV_PATH, load_settings, load_sources_config

setup_logging()

load_dotenv(ENV_PATH)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="News scraping agent")
    parser.add_argument(
        "--start-date",
        metavar="YYYY-MM-DD",
        help="Only scrape articles published on or after this date (IST). "
             "Requires --end-date. Only applies to sources with paginate: true.",
    )
    parser.add_argument(
        "--end-date",
        metavar="YYYY-MM-DD",
        help="Only scrape articles published on or before this date (IST). "
             "Requires --start-date.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if bool(args.start_date) != bool(args.end_date):
        print("Error: --start-date and --end-date must be used together.", file=sys.stderr)
        sys.exit(1)

    neo4j_uri = os.environ.get("NEO4J_URI", "neo4j://127.0.0.1:7687")
    neo4j_user = os.environ.get("NEO4J_USER", "neo4j")
    neo4j_password = os.environ.get("NEO4J_PASSWORD")
    neo4j_database = os.environ.get("NEO4J_DATABASE", "neo4j")
    groq_api_key = os.environ.get("GROQ_API_KEY")

    if not neo4j_password:
        raise EnvironmentError("NEO4J_PASSWORD is not set in environment")
    if not groq_api_key:
        raise EnvironmentError("GROQ_API_KEY is not set in environment")

    settings = load_settings()
    sources_config = load_sources_config()

    agent = NewsAgent(
        settings,
        neo4j_uri=neo4j_uri,
        neo4j_user=neo4j_user,
        neo4j_password=neo4j_password,
        neo4j_database=neo4j_database,
        groq_api_key=groq_api_key,
    )
    agent.run(
        sources_config["sources"],
        start_date=args.start_date,
        end_date=args.end_date,
    )


if __name__ == "__main__":
    main()
