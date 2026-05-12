import logging

from groq import Groq

from .db.repository import NewsRepository
from .processor.extractor import DealExtractor
from .processor.filter import NewsFilter
from .scraper.web_scraper import WebScraper

logger = logging.getLogger(__name__)


class NewsAgent:
    def __init__(self, settings: dict, database_url: str, groq_api_key: str):
        groq_client = Groq(api_key=groq_api_key)
        model = settings["groq"]["model"]
        scraping = settings["scraping"]
        db_cfg = settings.get("database", {})

        self.scraper = WebScraper(
            request_timeout=scraping["request_timeout"],
            delay=scraping["delay_between_requests"],
        )
        self.filter = NewsFilter()
        self.extractor = DealExtractor(groq_client, model)
        self.repo = NewsRepository(
            database_url,
            pool_size=db_cfg.get("pool_size", 5),
            max_overflow=db_cfg.get("max_overflow", 10),
        )
        self.max_articles = scraping["max_articles_per_source"]

    def run(self, sources: list[dict]) -> None:
        logger.info(f"Agent run started — {len(sources)} source(s)")
        total_scraped = total_new = total_deals = 0

        for source in sources:
            name = source["name"]
            logger.info(f"Scraping: {name}")

            links = self.scraper.get_article_links(
                source_url=source["url"],
                domain=source["domain"],
                link_contains=source["link_contains"],
                max_articles=self.max_articles,
            )
            total_scraped += len(links)
            logger.info(f"  Found {len(links)} links")

            for url in links:
                if self.repo.url_exists(url):
                    logger.debug(f"  Skip (seen): {url}")
                    continue

                title, content = self.scraper.extract_article(url)
                if not content:
                    logger.debug(f"  Skip (no content): {url}")
                    continue

                article = self.repo.save_article(url, name, title, content)
                total_new += 1

                relevant = self.filter.is_ma_relevant(title, content)
                self.repo.mark_ma_relevant(article.id, relevant)

                if not relevant:
                    logger.debug(f"  Not M&A: {title}")
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
                        f"  Deal: [{deal.deal_type}] {deal.buyer} / {deal.seller} — {deal.deal_value or 'value undisclosed'}"
                    )

        logger.info(
            f"Run complete — scraped: {total_scraped}, new: {total_new}, deals: {total_deals}"
        )
