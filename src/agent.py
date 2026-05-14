import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from groq import Groq

from .db.repository import NewsRepository
from .processor.extractor import DealExtractor
from .processor.filter import NewsFilter
from .scraper.web_scraper import CNBCScraper, ETScraper, FEScraper, WebScraper

SCRAPER_REGISTRY: dict[str, type[WebScraper]] = {
    "et": ETScraper,
    "fe": FEScraper,
    "cnbc": CNBCScraper,
}

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


def _to_ist_datetime(date_str: str, end_of_day: bool = False) -> datetime:
    """Convert 'YYYY-MM-DD' string to a timezone-aware IST datetime."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    if end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59)
    return dt.replace(tzinfo=IST)


class NewsAgent:
    def __init__(self, settings: dict, database_url: str, groq_api_key: str):
        groq_client = Groq(api_key=groq_api_key)
        model = settings["groq"]["model"]
        scraping = settings["scraping"]
        db_cfg = settings.get("database", {})

        self._scraper_kwargs = {
            "request_timeout": scraping["request_timeout"],
            "delay": scraping["delay_between_requests"],
        }
        self._scrapers: dict[str, WebScraper] = {}
        self.filter = NewsFilter()
        self.extractor = DealExtractor(groq_client, model)
        self.repo = NewsRepository(
            database_url,
            pool_size=db_cfg.get("pool_size", 5),
            max_overflow=db_cfg.get("max_overflow", 10),
        )
        self.max_articles = scraping["max_articles_per_source"]

    def _get_scraper(self, scraper_type: str) -> WebScraper:
        if scraper_type not in self._scrapers:
            cls = SCRAPER_REGISTRY[scraper_type]
            self._scrapers[scraper_type] = cls(**self._scraper_kwargs)
        return self._scrapers[scraper_type]

    def run(
        self,
        sources: list[dict],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> None:
        """
        Scrape all sources.

        When start_date and end_date (YYYY-MM-DD) are provided, only sources
        that have `paginate: true` in sources.yaml use multi-page date-range
        scraping. All fetched articles are also date-filtered before processing.
        """
        dt_start: Optional[datetime] = None
        dt_end: Optional[datetime] = None
        if start_date and end_date:
            dt_start = _to_ist_datetime(start_date, end_of_day=False)
            dt_end = _to_ist_datetime(end_date, end_of_day=True)
            logger.info(f"Date range filter: {start_date} → {end_date} (IST)")

        logger.info(f"Agent run started — {len(sources)} source(s)")

        total_scraped = total_new = total_deals = 0

        for source in sources:
            name = source["name"]
            logger.info(f"Scraping: {name}")

            scraper_type = source.get("scraper", "et")
            scraper = self._get_scraper(scraper_type)
            use_date_range = dt_start and dt_end and source.get("paginate", False)

            if use_date_range:
                links = scraper.get_article_links_in_date_range(
                    source_url=source["url"],
                    domain=source["domain"],
                    link_contains=source["link_contains"],
                    start_date=dt_start,
                    end_date=dt_end,
                    max_pages=source.get("max_pages", 10),
                )
            else:
                links = scraper.get_article_links(
                    source_url=source["url"],
                    domain=source["domain"],
                    link_contains=source["link_contains"],
                    max_articles=self.max_articles,
                )

            total_scraped += len(links)
            logger.info(f"  Found {len(links)} links")

            for url in links:
                if self.repo.url_exists(url):
                    logger.info(f"  Skip (already in DB): {url[-60:]}")
                    continue

                title, content, published_date = scraper.extract_article(url)
                if not content:
                    logger.warning(f"  Skip (no content extracted): {url}")
                    continue

                # Date-range check at article level (catches any articles that slipped past listing filter)
                if dt_start and dt_end and published_date:
                    if published_date < dt_start or published_date > dt_end:
                        logger.info(
                            f"  REJECTED (date {published_date.strftime('%Y-%m-%d')} outside range): {url[-60:]}"
                        )
                        continue

                date_label = published_date.strftime('%Y-%m-%d') if published_date else "date unknown"
                logger.info(f"  ACCEPTED [{date_label}]: {title or url[-60:]}")

                article = self.repo.save_article(
                    url, name, title, content, published_at=published_date
                )
                total_new += 1

                relevant = self.filter.is_ma_relevant(title, content)
                self.repo.mark_ma_relevant(article.id, relevant)

                if not relevant:
                    logger.info(f"  Not M&A relevant — skipping extraction")
                    continue

                deal = self.extractor.extract(title, content)
                if deal:
                    self.repo.save_deal(
                        article_id=article.id,
                        buyer=deal.buyer,
                        seller=deal.seller,
                        deal_value=deal.deal_value,
                        sector=deal.sector,
                        sub_sector=deal.sub_sector,
                        country=deal.country,
                        deal_type=deal.deal_type,
                        summary=deal.summary,
                    )
                    total_deals += 1
                    logger.info(
                        f"  Deal: [{deal.deal_type}] {deal.buyer} / {deal.seller}"
                        f" — {deal.deal_value or 'value undisclosed'}"
                    )

        logger.info(
            f"Run complete — scraped: {total_scraped}, new: {total_new}, deals: {total_deals}"
        )
