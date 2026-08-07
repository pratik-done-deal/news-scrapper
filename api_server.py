"""Uvicorn entry point for the API.

Single process on purpose: `src/api/app.py` starts an in-process APScheduler,
so a second worker duplicates every scrape and extraction tick. To scale the
HTTP layer, run additional instances with SCHEDULER_ENABLED=false rather than
raising the worker count here.

Env vars:
    API_HOST    default 0.0.0.0
    API_PORT    default 8000
    API_RELOAD  default off — dev only, never set this in production
    LOG_LEVEL   default INFO
"""

import os

import uvicorn

from src.logging_config import setup_logging

_TRUTHY = {"1", "true", "yes", "on"}


def main() -> None:
    setup_logging()
    uvicorn.run(
        "src.api.app:app",
        host=os.environ.get("API_HOST", "0.0.0.0"),
        port=int(os.environ.get("API_PORT", "8000")),
        reload=os.environ.get("API_RELOAD", "false").strip().lower() in _TRUTHY,
        workers=1,
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()
