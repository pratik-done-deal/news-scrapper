import argparse
import logging
import os
import sys

import yaml
from dotenv import load_dotenv

from src.agent import NewsAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("news_agent.log"),
    ],
)

load_dotenv()


def load_yaml(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


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

    database_url = os.environ.get("DATABASE_URL")
    groq_api_key = os.environ.get("GROQ_API_KEY")

    if not database_url:
        raise EnvironmentError("DATABASE_URL is not set in environment")
    if not groq_api_key:
        raise EnvironmentError("GROQ_API_KEY is not set in environment")

    settings = load_yaml("config/settings.yaml")
    sources_config = load_yaml("config/sources.yaml")

    agent = NewsAgent(settings, database_url, groq_api_key)
    agent.run(
        sources_config["sources"],
        start_date=args.start_date,
        end_date=args.end_date,
    )


if __name__ == "__main__":
    main()
