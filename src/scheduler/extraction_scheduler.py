import logging
from typing import Optional

from ..agent import NewsAgent

logger = logging.getLogger(__name__)


class ExtractionScheduler:
    """Ticks on its own interval, filtering/extracting articles pending in the DB."""

    def __init__(self, agent: NewsAgent, interval_minutes: int, batch_limit: Optional[int] = None):
        self.agent = agent
        self.interval_minutes = interval_minutes
        self.batch_limit = batch_limit

    def run_once(self) -> None:
        """A tick failing must never kill the scheduler or block the next tick."""
        try:
            self.agent.extract_pending(limit=self.batch_limit)
        except Exception:
            logger.exception("ExtractionScheduler tick failed")
