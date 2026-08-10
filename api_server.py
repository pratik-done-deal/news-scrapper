"""Uvicorn entry point for the API.

The in-process APScheduler in `src/api/app.py` is off by default, so this
serves HTTP only unless `--scheduler-enabled true` is passed. Pass it on at
most one instance and give that instance a single worker — a second worker
duplicates every scrape and extraction tick. Scale the HTTP layer with extra
instances that leave the scheduler off, not by raising the worker count here.

Configuration defaults live in `src/config.py`; every one of them can be
overridden on this command line (`--help` lists them). The resolved config is
exported to the environment before uvicorn starts, so `--api-reload true`,
which runs the app in a child process, still sees what was passed here.
"""

import argparse
import sys

import uvicorn

from src.config import ConfigError, add_config_arguments, load_config
from src.logging_config import setup_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="News scraping API server")
    add_config_arguments(parser)
    return parser.parse_args()


def main() -> None:
    config = load_config(parse_args())
    setup_logging()

    # Fail here rather than inside uvicorn's lifespan, where the traceback is
    # buried under a startup error.
    try:
        config.require_neo4j_password()
        config.require_groq_api_key()
    except ConfigError as exc:
        sys.exit(f"Error: {exc}")

    uvicorn.run(
        "src.api.app:app",
        host=config.api.host,
        port=config.api.port,
        reload=config.api.reload,
        workers=1,
        log_level=config.logging.level.lower(),
    )


if __name__ == "__main__":
    main()
