import logging
import multiprocessing
import queue
import sys
from datetime import datetime, timezone, timedelta
from multiprocessing.queues import Queue
from typing import Optional

from groq import Groq

from .db.repository import NewsRepository
from .processor.extractor import DealExtractor
from .processor.filter import NewsFilter
from .scraper.web_scraper import CNBCScraper, ETScraper, FEScraper, IndiaInfolineScraper, WebScraper

SCRAPER_REGISTRY: dict[str, type[WebScraper]] = {
    "et": ETScraper,
    "fe": FEScraper,
    "cnbc": CNBCScraper,
    "iifl": IndiaInfolineScraper,
}

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

STOP_PROCESSING = "__STOP_PROCESSING__"
PRODUCER_LABEL = "P1 producer"
CONSUMER_LABEL = "P2 consumer"
LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(processName)s] %(name)s: %(message)s"


def _to_ist_datetime(date_str: str, end_of_day: bool = False) -> datetime:
    """Convert 'YYYY-MM-DD' string to a timezone-aware IST datetime."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    if end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59)
    return dt.replace(tzinfo=IST)


def _ensure_worker_logging() -> None:
    """Make worker-process INFO logs visible even when spawn starts fresh."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if root.handlers:
        return
    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("news_agent.log"),
        ],
    )


def _process_source_articles(
    source_name: str,
    articles: list[dict],
    repo: NewsRepository,
    news_filter: NewsFilter,
    extractor: DealExtractor,
) -> tuple[int, int]:
    """
    Save scraped article data, filter it, and extract deals for one source batch.
    Runs inside the dedicated processing process.
    """
    process = multiprocessing.current_process().name
    logger.info(
        f"[{CONSUMER_LABEL}|{process}] Started processing [{source_name}]"
        f" — {len(articles)} article(s)"
    )
    new = deals = 0

    for article_data in articles:
        url = article_data["url"]
        if repo.url_exists(url):
            logger.info(f"  [{CONSUMER_LABEL}|{source_name}|{process}] Skip (already in DB): {url[-60:]}")
            continue

        title = article_data["title"]
        content = article_data["content"]
        published_date = article_data["published_date"]
        date_label = published_date.strftime("%Y-%m-%d") if published_date else "date unknown"
        logger.info(
            f"  [{CONSUMER_LABEL}|{source_name}|{process}]"
            f" Filtering/extracting [{date_label}]: {title or url[-60:]}"
        )

        article = repo.save_article(
            url, source_name, title, content, published_at=published_date
        )
        new += 1

        relevant = news_filter.is_ma_funding_relevant(title, content)
        repo.mark_ma_funding_relevant(article.id, relevant)

        if not relevant:
            logger.info(
                f"  [{CONSUMER_LABEL}|{source_name}|{process}]"
                " Not M&A or funding relevant — skipping extraction"
            )
            continue

        deal = extractor.extract(title, content)
        if deal:
            repo.save_deal(
                article_id=article.id,
                buyer=deal.buyer,      # split into company_deals by repo
                seller=deal.seller,    # split into company_deals by repo
                deal_value=deal.deal_value,
                sector=deal.sector,
                sub_sector=deal.sub_sector,
                country=deal.country,
                deal_type=deal.deal_type,
                summary=deal.summary,
            )
            deals += 1
            logger.info(
                f"  [{CONSUMER_LABEL}|{source_name}|{process}] Deal: [{deal.deal_type}]"
                f" {deal.buyer} / {deal.seller}"
                f" — {deal.deal_value or 'value undisclosed'}"
            )

    logger.info(
        f"[{CONSUMER_LABEL}|{process}] Finished [{source_name}]"
        f" — new: {new}, deals: {deals}"
    )
    return new, deals


def _processing_worker(
    job_queue: Queue,
    result_queue: Queue,
    neo4j_uri: str,
    neo4j_user: str,
    neo4j_password: str,
    neo4j_database: str,
    groq_api_key: str,
    groq_model: str,
    db_pool_size: int,
) -> None:
    """Dedicated process that consumes scraped source batches and processes articles."""
    _ensure_worker_logging()
    process = multiprocessing.current_process().name
    logger.info(f"[{CONSUMER_LABEL}|{process}] Worker booting and waiting for scraped batches")

    try:
        groq_client = Groq(api_key=groq_api_key)
        repo = NewsRepository(
            uri=neo4j_uri,
            user=neo4j_user,
            password=neo4j_password,
            database=neo4j_database,
            pool_size=db_pool_size,
        )
        news_filter = NewsFilter()
        extractor = DealExtractor(groq_client, groq_model)
    except Exception as exc:
        logger.exception(f"[{process}] Processing worker failed to initialize")
        result_queue.put({"type": "worker_error", "error": repr(exc)})
        return

    while True:
        job = job_queue.get()
        if job == STOP_PROCESSING:
            logger.info(f"[{CONSUMER_LABEL}|{process}] Stop signal received")
            break

        source_name = job["source_name"]
        logger.info(
            f"[{CONSUMER_LABEL}|{process}] Picked up [{source_name}]"
            f" from queue — {len(job['articles'])} article(s)"
        )
        try:
            new, deals = _process_source_articles(
                source_name=source_name,
                articles=job["articles"],
                repo=repo,
                news_filter=news_filter,
                extractor=extractor,
            )
            result_queue.put({
                "type": "source_done",
                "source_name": source_name,
                "new": new,
                "deals": deals,
            })
        except Exception as exc:
            logger.exception(f"[{CONSUMER_LABEL}|{source_name}|{process}] Processing failed")
            result_queue.put({
                "type": "source_error",
                "source_name": source_name,
                "error": repr(exc),
            })

    logger.info(f"[{CONSUMER_LABEL}|{process}] Worker exiting")
    result_queue.put({"type": "worker_done"})


class NewsAgent:
    def __init__(
        self,
        settings: dict,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        neo4j_database: str,
        groq_api_key: str,
    ):
        model = settings["groq"]["model"]
        scraping = settings["scraping"]
        db_cfg = settings.get("database", {})

        self.neo4j_uri = neo4j_uri
        self.neo4j_user = neo4j_user
        self.neo4j_password = neo4j_password
        self.neo4j_database = neo4j_database
        self.groq_api_key = groq_api_key
        self.groq_model = model
        self.db_pool_size = db_cfg.get("pool_size", 5)
        self._scraper_kwargs = {
            "request_timeout": scraping["request_timeout"],
            "delay": scraping["delay_between_requests"],
        }
        self._scrapers: dict[str, WebScraper] = {}
        self.repo = NewsRepository(
            uri=neo4j_uri,
            user=neo4j_user,
            password=neo4j_password,
            database=neo4j_database,
            pool_size=self.db_pool_size,
        )
        self.max_articles = scraping["max_articles_per_source"]

    def _get_scraper(self, scraper_type: str) -> WebScraper:
        if scraper_type not in self._scrapers:
            cls = SCRAPER_REGISTRY[scraper_type]
            self._scrapers[scraper_type] = cls(**self._scraper_kwargs)
        return self._scrapers[scraper_type]

    def _scrape_links(
        self,
        source: dict,
        dt_start: Optional[datetime],
        dt_end: Optional[datetime],
    ) -> list[str]:
        """Collect article URLs for one source without fetching article content."""
        scraper_type = source.get("scraper", "et")
        scraper = self._get_scraper(scraper_type)
        use_date_range = dt_start and dt_end and source.get("paginate", False)

        if use_date_range:
            return scraper.get_article_links_in_date_range(
                source_url=source["url"],
                domain=source["domain"],
                link_contains=source["link_contains"],
                start_date=dt_start,
                end_date=dt_end,
                max_pages=source.get("max_pages", 10),
            )
        return scraper.get_article_links(
            source_url=source["url"],
            domain=source["domain"],
            link_contains=source["link_contains"],
            max_articles=self.max_articles,
        )

    def _scrape_articles(
        self,
        source: dict,
        dt_start: Optional[datetime],
        dt_end: Optional[datetime],
    ) -> tuple[int, list[dict]]:
        """Scrape article content for one source and return data for processing."""
        source_name = source["name"]
        scraper_type = source.get("scraper", "et")
        scraper = self._get_scraper(scraper_type)
        logger.info(f"[{PRODUCER_LABEL}] Starting scrape for [{source_name}]")
        links = self._scrape_links(source, dt_start, dt_end)
        articles: list[dict] = []

        logger.info(f"  [{PRODUCER_LABEL}|{source_name}] Found {len(links)} links")

        for url in links:
            if self.repo.url_exists(url):
                logger.info(f"  [{PRODUCER_LABEL}|{source_name}] Skip (already in DB): {url[-60:]}")
                continue

            title, content, published_date = scraper.extract_article(url)
            if not content:
                logger.warning(f"  [{PRODUCER_LABEL}|{source_name}] Skip (no content extracted): {url}")
                continue

            if dt_start and dt_end and published_date:
                if published_date < dt_start or published_date > dt_end:
                    logger.info(
                        f"  [{PRODUCER_LABEL}|{source_name}] REJECTED"
                        f" (date {published_date.strftime('%Y-%m-%d')} outside range): {url[-60:]}"
                    )
                    continue

            date_label = published_date.strftime("%Y-%m-%d") if published_date else "date unknown"
            logger.info(
                f"  [{PRODUCER_LABEL}|{source_name}] SCRAPED [{date_label}]:"
                f" {title or url[-60:]}"
            )
            articles.append({
                "url": url,
                "title": title,
                "content": content,
                "published_date": published_date,
            })

        logger.info(
            f"[{PRODUCER_LABEL}] Completed scrape for [{source_name}]"
            f" — {len(articles)} article(s) ready for {CONSUMER_LABEL}"
        )
        return len(links), articles

    def _handle_processor_message(
        self,
        counters: dict,
        active_sources: list[str],
        message: dict,
    ) -> bool:
        """Apply one processor result message. Returns True when the worker is done."""
        message_type = message.get("type")

        if message_type == "source_done":
            source_name = message["source_name"]
            if source_name in active_sources:
                active_sources.remove(source_name)
            counters["new"] += message["new"]
            counters["deals"] += message["deals"]
            logger.info(
                f"[{CONSUMER_LABEL}->MainProcess] Completed [{source_name}]"
                f" | active queue: {active_sources or 'empty'}"
            )
            return False

        if message_type == "source_error":
            source_name = message["source_name"]
            if source_name in active_sources:
                active_sources.remove(source_name)
            error = f"{source_name}: {message['error']}"
            counters["errors"].append(error)
            logger.error(f"[{CONSUMER_LABEL}->MainProcess] Error — {error}")
            return False

        if message_type == "worker_error":
            raise RuntimeError(f"Processing process failed to initialize: {message['error']}")

        if message_type == "worker_done":
            return True

        logger.warning(f"[{CONSUMER_LABEL}->MainProcess] Unknown message: {message}")
        return False

    def _drain_processor_results(
        self,
        result_queue: Queue,
        counters: dict,
        active_sources: list[str],
    ) -> bool:
        """Read any currently available worker messages without blocking."""
        worker_done = False
        while True:
            try:
                message = result_queue.get_nowait()
            except queue.Empty:
                break
            worker_done = (
                self._handle_processor_message(counters, active_sources, message)
                or worker_done
            )
        return worker_done

    def _wait_for_processor(
        self,
        processor: multiprocessing.Process,
        result_queue: Queue,
        counters: dict,
        active_sources: list[str],
    ) -> None:
        """Block until the processing process reports completion or exits unexpectedly."""
        worker_done = False
        while not worker_done:
            try:
                message = result_queue.get(timeout=1)
            except queue.Empty:
                worker_done = self._drain_processor_results(
                    result_queue, counters, active_sources
                )
                if worker_done:
                    break
                if not processor.is_alive():
                    raise RuntimeError(
                        "Processing process exited unexpectedly "
                        f"with code {processor.exitcode}"
                    )
                continue

            worker_done = self._handle_processor_message(
                counters, active_sources, message
            )

        processor.join()
        if processor.exitcode not in (0, None):
            raise RuntimeError(
                f"Processing process exited with code {processor.exitcode}"
            )

    def run(
        self,
        sources: list[dict],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> None:
        """
        Pipeline execution:
          Process 1 scrapes source listing pages and article content in order.
          Process 2 consumes each completed source batch for database save,
          filtering, and extraction.

        This keeps processing concurrency fixed at one worker process instead
        of scaling workers with the number of configured sources.
        """
        dt_start: Optional[datetime] = None
        dt_end: Optional[datetime] = None
        if start_date and end_date:
            dt_start = _to_ist_datetime(start_date, end_of_day=False)
            dt_end = _to_ist_datetime(end_date, end_of_day=True)
            logger.info(f"Date range filter: {start_date} → {end_date} (IST)")

        main_process = multiprocessing.current_process().name
        logger.info(
            f"Agent run started — {PRODUCER_LABEL} on [{main_process}],"
            f" {CONSUMER_LABEL} will run in one dedicated process,"
            f" sources: {len(sources)}"
        )

        total_scraped = 0
        counters = {"new": 0, "deals": 0, "errors": []}
        active_sources: list[str] = []

        ctx = multiprocessing.get_context("spawn")
        job_queue = ctx.Queue()
        result_queue = ctx.Queue()
        processor = ctx.Process(
            target=_processing_worker,
            name="article-processor",
            args=(
                job_queue,
                result_queue,
                self.neo4j_uri,
                self.neo4j_user,
                self.neo4j_password,
                self.neo4j_database,
                self.groq_api_key,
                self.groq_model,
                self.db_pool_size,
            ),
        )

        stop_sent = False
        processor.start()

        try:
            for source in sources:
                worker_done = self._drain_processor_results(
                    result_queue, counters, active_sources
                )
                if worker_done:
                    raise RuntimeError(
                        "Processing process exited before all sources were dispatched"
                    )
                if not processor.is_alive():
                    self._drain_processor_results(
                        result_queue, counters, active_sources
                    )
                    raise RuntimeError(
                        "Processing process exited unexpectedly "
                        f"with code {processor.exitcode}"
                    )

                name = source["name"]
                logger.info(
                    f"[{PRODUCER_LABEL}|{main_process}] Scraping articles for [{name}]"
                    + (f" | processing queue active: {active_sources}" if active_sources else "")
                )

                link_count, articles = self._scrape_articles(source, dt_start, dt_end)
                total_scraped += link_count

                active_sources.append(name)
                job_queue.put({
                    "source_name": name,
                    "articles": articles,
                })

                logger.info(
                    f"[{PRODUCER_LABEL}->{CONSUMER_LABEL}] Handoff [{name}]"
                    f" — {len(articles)} article(s) queued"
                    f" | active queue: {active_sources}"
                )

            job_queue.put(STOP_PROCESSING)
            stop_sent = True
            logger.info(
                f"[{PRODUCER_LABEL}|{main_process}] All sources scraped."
                f" Stop signal queued; waiting for {CONSUMER_LABEL}:"
                f" {active_sources or 'empty'}"
            )
            self._wait_for_processor(
                processor, result_queue, counters, active_sources
            )
        finally:
            if not stop_sent:
                try:
                    job_queue.put(STOP_PROCESSING)
                except Exception:
                    logger.exception("Failed to send processing worker stop signal")

            processor.join(timeout=5)
            if processor.is_alive():
                logger.warning(f"{CONSUMER_LABEL} did not stop in time; terminating")
                processor.terminate()
                processor.join(timeout=5)

            job_queue.close()
            result_queue.close()

        logger.info(
            f"Run complete — scraped: {total_scraped},"
            f" new: {counters['new']}, deals: {counters['deals']}"
        )
        if counters["errors"]:
            logger.error(f"Run completed with processing errors: {counters['errors']}")
