"""One place to configure logging for every entry point.

Two problems this solves:

1. Under uvicorn nothing configured the root logger, so all `src.*` output —
   the scheduler ticks, the scrape and extraction pipeline — was dropped and
   the deployed API looked silent.
2. The file handler was a plain `FileHandler` with no rotation, so
   `news_agent.log` grew without bound.

Scrape workers are separate processes (`spawn`) that inherit the parent's
stdout, so they log to the stream only: several processes rotating the same
file concurrently loses and interleaves records.

Settings come from `src/config.py` (`logging.level`, `logging.file`,
`logging.max_bytes`, `logging.backup_count`), overridable with --log-level,
--log-file, --log-max-bytes and --log-backup-count.
"""

import logging
import sys
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from .config import get_config
from .paths import PROJECT_ROOT

LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(processName)s] [%(profile_id)s] %(name)s: %(message)s"
_DISABLED = {"", "none", "off", "false", "0", "stdout"}

# The authenticated caller, for the duration of one request. Set by the auth
# dependency; "-" on the pipeline, the scheduler, and anything else with no
# request behind it.
profile_id_ctx: ContextVar[str] = ContextVar("profile_id", default="-")


def _install_record_factory() -> None:
    """Stamp `profile_id` onto every record, whoever created the logger.

    A logging Filter would only cover the handlers attached here, and any
    handler configured elsewhere (`migrate_pg_to_neo4j.py` calls
    `basicConfig`) would then blow up formatting a record with no such
    attribute. Doing it in the factory means the attribute always exists and
    formats that ignore it keep working.
    """
    current = logging.getLogRecordFactory()
    if getattr(current, "_injects_profile_id", False):
        return

    def factory(*args, **kwargs):
        record = current(*args, **kwargs)
        record.profile_id = profile_id_ctx.get()
        return record

    factory._injects_profile_id = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)


def log_file_path() -> Optional[Path]:
    """Resolved log file, or None when file logging is switched off."""
    raw = (get_config().logging.file or "").strip()
    if raw.lower() in _DISABLED:
        return None
    path = Path(raw)
    return path if path.is_absolute() else PROJECT_ROOT / path


def setup_logging(to_file: bool = True, force: bool = False) -> None:
    """Attach stdout (and optionally a rotating file) to the root logger.

    Idempotent: a root logger that already has handlers is left alone unless
    `force`, so an entry point that configures logging before starting uvicorn
    is not reconfigured again by the app's lifespan.
    """
    _install_record_factory()

    log_cfg = get_config().logging

    root = logging.getLogger()
    root.setLevel(log_cfg.level.upper())

    if root.handlers and not force:
        return
    if force:
        for handler in list(root.handlers):
            root.removeHandler(handler)
            handler.close()

    formatter = logging.Formatter(LOG_FORMAT)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    if not to_file:
        return

    path = log_file_path()
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            path,
            maxBytes=log_cfg.max_bytes,
            backupCount=log_cfg.backup_count,
            encoding="utf-8",
        )
    except OSError as exc:
        # A read-only or missing log directory must not stop the service:
        # stdout is already attached and containers collect it anyway.
        root.warning("File logging disabled, cannot open %s: %s", path, exc)
        return
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
