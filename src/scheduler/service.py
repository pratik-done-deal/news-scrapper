import logging

from apscheduler.schedulers.background import BackgroundScheduler

from .extraction_scheduler import ExtractionScheduler
from .scrapper_scheduler import ScrapperScheduler
from ..agent import NewsAgent

logger = logging.getLogger(__name__)


class SchedulerService:
    """
    Owns two independent, timer-driven jobs on one BackgroundScheduler:
      - ScrapperScheduler: scrapes all sources and stores them in the DB.
      - ExtractionScheduler: filters/extracts articles pending in the DB.

    BackgroundScheduler runs jobs on its own thread pool, so calling
    synchronous/blocking code (scraping, Neo4j, Groq) from a tick doesn't
    stall the FastAPI event loop.
    """

    def __init__(self, agent: NewsAgent, sources: list[dict], scheduler_cfg: dict):
        self._scraper_scheduler = ScrapperScheduler(
            agent=agent,
            sources=sources,
            interval_minutes=scheduler_cfg.get("scrape_interval_minutes", 10),
        )
        self._extraction_scheduler = ExtractionScheduler(
            agent=agent,
            interval_minutes=scheduler_cfg.get("extraction_interval_minutes", 10),
            batch_limit=scheduler_cfg.get("extraction_batch_limit"),
        )
        self._scheduler = BackgroundScheduler()

    def start(self) -> None:
        self._scheduler.add_job(
            self._scraper_scheduler.run_once,
            trigger="interval",
            minutes=self._scraper_scheduler.interval_minutes,
            id="scrapper_scheduler",
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.add_job(
            self._extraction_scheduler.run_once,
            trigger="interval",
            minutes=self._extraction_scheduler.interval_minutes,
            id="extraction_scheduler",
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.start()
        logger.info(
            "SchedulerService started —"
            f" scrape every {self._scraper_scheduler.interval_minutes}m,"
            f" extraction every {self._extraction_scheduler.interval_minutes}m"
        )

    def shutdown(self) -> None:
        self._scheduler.shutdown(wait=False)
