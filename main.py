import argparse
import sys

from src.agent import NewsAgent
from src.config import ConfigError, add_config_arguments, load_config
from src.logging_config import setup_logging
from src.paths import load_settings, load_sources_config


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
    # The pipeline serves no HTTP and validates no sessions, so the api and
    # auth flags are left off its help output.
    add_config_arguments(parser, only=("neo4j", "groq", "mysql", "logging"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args)

    # Logging is configured after the config is installed, so --log-level and
    # --log-file apply to this run's very first record.
    setup_logging()

    if bool(args.start_date) != bool(args.end_date):
        print("Error: --start-date and --end-date must be used together.", file=sys.stderr)
        sys.exit(1)

    try:
        neo4j_password = config.require_neo4j_password()
        groq_api_key = config.require_groq_api_key()
    except ConfigError as exc:
        sys.exit(f"Error: {exc}")

    settings = load_settings()
    sources_config = load_sources_config()

    agent = NewsAgent(
        settings,
        neo4j_uri=config.neo4j.uri,
        neo4j_user=config.neo4j.user,
        neo4j_password=neo4j_password,
        neo4j_database=config.neo4j.database,
        groq_api_key=groq_api_key,
    )
    agent.run(
        sources_config["sources"],
        start_date=args.start_date,
        end_date=args.end_date,
    )


if __name__ == "__main__":
    main()
