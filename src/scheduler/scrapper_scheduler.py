import logging

from ..agent import NewsAgent

logger = logging.getLogger(__name__)


class ScrapperScheduler:
    """Ticks on its own interval, scraping all sources and storing them in the DB."""

    def __init__(self, agent: NewsAgent, sources: list[dict], interval_minutes: int):
        self.agent = agent
        self.sources = sources
        self.interval_minutes = interval_minutes

    def run_once(self) -> None:
        """A tick failing must never kill the scheduler or block the next tick."""
        try:
            self.agent.scrape_and_store(self.sources)
        except Exception:
            logger.exception("ScrapperScheduler tick failed")
