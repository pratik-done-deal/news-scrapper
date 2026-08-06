import logging
import multiprocessing
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

from groq import Groq

from .db.repository import NewsRepository
from .processor.company_signal import deal_amount_token, is_duplicate_of_deal
from .processor.extractor import DealExtractor
from .processor.filter import NewsFilter
from .processor.watchlist import gate_articles
from .scraper.rss_scraper import RSSScraper
from .scraper.web_scraper import (
    CNBCScraper,
    EntrackrScraper,
    ETScraper,
    FEScraper,
    Inc42Scraper,
    IndianStartupNewsScraper,
    IndiaInfolineScraper,
    WebScraper,
)

SCRAPER_REGISTRY: dict[str, type[WebScraper]] = {
    "et": ETScraper,
    "fe": FEScraper,
    "cnbc": CNBCScraper,
    "iifl": IndiaInfolineScraper,
    "isn": IndianStartupNewsScraper,
    "inc42": Inc42Scraper,
    "entrackr": EntrackrScraper,
}

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

SCRAPER_LABEL = "Scraper"
STORAGE_LABEL = "Storage"
LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(processName)s] %(name)s: %(message)s"
MAX_THREADS = 6


@dataclass(frozen=True)
class ScraperDBConfig:
    """Neo4j connection info a scrape worker needs for its per-link URL dedup check."""

    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    neo4j_database: str
    db_pool_size: int


def _tag(*parts: str) -> str:
    """Build a '[part1|part2|...]' log prefix."""
    return "[" + "|".join(parts) + "]"


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


def _build_scraper(
    source: dict,
    company: Optional[str],
    dt_start: Optional[datetime],
    dt_end: Optional[datetime],
    scraper_kwargs: dict,
) -> tuple[WebScraper, str]:
    """Pick the scraper for this job and the listing URL it should read.

    RSS covers the routine firehose: one request per source, publisher-supplied
    dates, and often the full article body — so it replaces both the listing walk
    and the per-article fetch. What a feed cannot do is search or reach back more
    than a few days, so a company-scoped job or an explicit date range still runs
    through the site scraper, which is what `paginate`/`search_url` exist for.
    """
    rss_url = source.get("rss_url")
    if rss_url and not company and not (dt_start and dt_end):
        return RSSScraper(**scraper_kwargs), rss_url
    return SCRAPER_REGISTRY[source.get("scraper", "et")](**scraper_kwargs), source["url"]


def _scrape_links(
    scraper: WebScraper,
    source: dict,
    max_articles: int,
    dt_start: Optional[datetime],
    dt_end: Optional[datetime],
    company: Optional[str] = None,
    listing_url: Optional[str] = None,
) -> list[str]:
    """Collect article URLs for one source without fetching article content.

    When `company` is given, the source's on-site search (`search_url`) is used
    instead of its section listing, pulling that company's news from the site's
    archive. Dates are always passed on the company path: for a search they are a
    filter on the results, not a pagination concern, and a source that cannot
    paginate simply stops after its first page of results.

    `listing_url` is what the non-company path reads — the source's section URL,
    or its feed when `_build_scraper` chose RSS.
    """
    listing_url = listing_url or source["url"]
    if company:
        return scraper.get_company_article_links(
            search_url=source["search_url"],
            domain=source["domain"],
            link_contains=source["link_contains"],
            company=company,
            start_date=dt_start,
            end_date=dt_end,
            max_pages=source.get("max_pages", 10),
            max_articles=max_articles,
        )
    use_date_range = dt_start and dt_end and source.get("paginate", False)
    if use_date_range:
        return scraper.get_article_links_in_date_range(
            source_url=listing_url,
            domain=source["domain"],
            link_contains=source["link_contains"],
            start_date=dt_start,
            end_date=dt_end,
            max_pages=source.get("max_pages", 10),
        )
    return scraper.get_article_links(
        source_url=listing_url,
        domain=source["domain"],
        link_contains=source["link_contains"],
        max_articles=max_articles,
    )


def _scrape_source_worker(
    source: dict,
    dt_start: Optional[datetime],
    dt_end: Optional[datetime],
    scraper_kwargs: dict,
    max_articles: int,
    db_config: ScraperDBConfig,
    company: Optional[str] = None,
) -> dict:
    """
    Runs in its own process. Scrapes one source fully, keeping the articles in
    memory (no DB writes here) and returns them so the main process can
    combine every source's results and store them in batches once all
    scrapers finish.
    """
    _ensure_worker_logging()
    source_name = source["name"]
    process = multiprocessing.current_process().name
    scope = f" (company='{company}')" if company else ""
    logger.info(f"{_tag(SCRAPER_LABEL, process)} Starting scrape for [{source_name}]{scope}")

    try:
        scraper, listing_url = _build_scraper(source, company, dt_start, dt_end, scraper_kwargs)
        scraper.source_config = source
        if isinstance(scraper, RSSScraper):
            logger.info(f"  {_tag(SCRAPER_LABEL, source_name)} Using RSS feed: {listing_url}")
        repo = NewsRepository(
            uri=db_config.neo4j_uri,
            user=db_config.neo4j_user,
            password=db_config.neo4j_password,
            database=db_config.neo4j_database,
            pool_size=db_config.db_pool_size,
            ensure_schema=False,
        )

        links = _scrape_links(
            scraper, source, max_articles, dt_start, dt_end, company, listing_url
        )
        logger.info(f"  {_tag(SCRAPER_LABEL, source_name)} Found {len(links)} links")

        articles: list[dict] = []
        for url in links:
            if repo.url_exists(url):
                logger.info(f"  {_tag(SCRAPER_LABEL, source_name)} Skip (already in DB): {url[-60:]}")
                continue

            title, content, published_date = scraper.extract_article(url)
            if not content:
                logger.warning(f"  {_tag(SCRAPER_LABEL, source_name)} Skip (no content extracted): {url}")
                continue

            if dt_start and dt_end and published_date:
                if published_date < dt_start or published_date > dt_end:
                    logger.info(
                        f"  {_tag(SCRAPER_LABEL, source_name)} REJECTED"
                        f" (date {published_date.strftime('%Y-%m-%d')} outside range): {url[-60:]}"
                    )
                    continue

            date_label = published_date.strftime("%Y-%m-%d") if published_date else "date unknown"
            logger.info(
                f"  {_tag(SCRAPER_LABEL, source_name)} SCRAPED [{date_label}]:"
                f" {title or url[-60:]}"
            )
            articles.append({
                "url": url,
                "title": title,
                "content": content,
                "published_date": published_date,
                "source_name": source_name,
            })

        repo.close()
        logger.info(
            f"{_tag(SCRAPER_LABEL, process)} Completed scrape for [{source_name}]"
            f" — {len(articles)} article(s) ready for storage"
        )
        return {
            "source_name": source_name,
            "link_count": len(links),
            "articles": articles,
            "error": None,
        }
    except Exception as exc:
        logger.exception(f"{_tag(SCRAPER_LABEL, source_name, process)} Scrape failed")
        return {
            "source_name": source_name,
            "link_count": 0,
            "articles": [],
            "error": repr(exc),
        }


def _date_label(value) -> str:
    """Format a published-date value for logging; accepts a datetime or an ISO string."""
    if not value:
        return "date unknown"
    if isinstance(value, str):
        return value[:10]
    return value.strftime("%Y-%m-%d")


def _store_batch(batch: list[dict], repo: NewsRepository) -> list[dict]:
    """Persist one batch of scraped articles (no filtering/extraction). Runs in the main process."""
    return repo.save_articles_batch(batch)


DEDUP_SIMILARITY_THRESHOLD = 0.45
# Same deal is often re-reported by other outlets days after the first story,
# so the comparison pool spans two weeks rather than one.
DEDUP_WINDOW_DAYS = 14


def _find_duplicate_article(article: dict, candidates: list[dict]) -> Optional[dict]:
    """Return the first already-extracted deal-article that `article` re-reports, if any.

    Each candidate carries its deal's parties and amount token so the match
    stays reliable even when one side's body is thin/paywalled — the case that
    otherwise lets a second outlet's copy slip through into a redundant LLM
    extraction.
    """
    for candidate in candidates:
        if is_duplicate_of_deal(
            article,
            candidate,
            candidate.get("parties") or [],
            candidate.get("amount_token"),
            DEDUP_SIMILARITY_THRESHOLD,
        ):
            return candidate
    return None


def _filter_and_extract_articles(
    articles: list[dict],
    repo: NewsRepository,
    news_filter: NewsFilter,
    extractor: DealExtractor,
) -> tuple[int, int]:
    """
    Run filter/extraction over a list of already-stored articles.

    Each article is handled independently — one article's failure is logged
    and skipped rather than aborting the rest of the list, so a single bad
    article (LLM error, malformed content) can't leave every article behind
    it permanently stuck at is_ma_funding_relevant: null.

    Before running LLM extraction, each relevant article is checked against
    recently-extracted articles (e.g. the same deal reported by CNBC and
    another outlet) — a near-duplicate is linked to the existing Deal instead
    of paying for a second LLM extraction.
    """
    processed = deals = 0
    duplicate_pool = repo.get_recent_deal_articles(days=DEDUP_WINDOW_DAYS)
    for candidate in duplicate_pool:
        candidate["amount_token"] = deal_amount_token(candidate.get("deal_value"))

    for article in articles:
        source_name = article["source_name"]
        title = article["title"]
        content = article["content"]
        article_id = article["id"]
        date_label = _date_label(article.get("published_date") or article.get("published_at"))

        try:
            logger.info(
                f"  {_tag(STORAGE_LABEL, source_name)}"
                f" Filtering/extracting [{date_label}]: {title or article['url'][-60:]}"
            )

            # Duplicate detection runs before the relevance filter: a
            # re-report of an already-extracted deal is M&A-relevant by
            # definition, so catching it here skips BOTH the filter and the
            # extraction LLM calls rather than just the extraction one.
            duplicate = _find_duplicate_article(article, duplicate_pool)
            if duplicate:
                repo.mark_duplicate_article(article_id, duplicate["id"], is_relevant=True)
                processed += 1
                logger.info(
                    f"  {_tag(STORAGE_LABEL, source_name)}"
                    f" Duplicate of already-processed article {duplicate['id']}"
                    f" (deal {duplicate['deal_id']}) — skipping filter + LLM extraction"
                )
                continue

            relevant = news_filter.is_ma_funding_relevant(title, content)
            repo.mark_ma_funding_relevant(article_id, relevant)
            processed += 1

            if not relevant:
                logger.info(
                    f"  {_tag(STORAGE_LABEL, source_name)}"
                    " Not M&A or funding relevant — skipping extraction"
                )
                continue

            deal = extractor.extract(title, content)
            # extractor.extract() returns a DealData with all-null fields (rather
            # than None) when the LLM decides the article isn't about a single
            # concrete deal (e.g. weekly funding roundups/trackers that merely
            # mention deal keywords) — skip saving in that case so we don't
            # create empty Deal nodes.
            if deal and deal.summary:
                deal_id = repo.save_deal(
                    article_id=article_id,
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
                # Extend the in-batch pool so a duplicate of this same article
                # scraped from another source later in this batch is caught too
                # — carrying the deal's parties/amount so the thin-body fallback
                # works within the batch as well as across batches.
                duplicate_pool.append(
                    {
                        "id": article_id,
                        "title": title,
                        "content": content,
                        "deal_id": deal_id,
                        "parties": [p for p in (deal.buyer, deal.seller) if p],
                        "amount_token": deal_amount_token(deal.deal_value),
                    }
                )
                logger.info(
                    f"  {_tag(STORAGE_LABEL, source_name)} Deal: [{deal.deal_type}]"
                    f" {deal.buyer} / {deal.seller}"
                    f" — {deal.deal_value or 'value undisclosed'}"
                )
        except Exception:
            logger.exception(
                f"  {_tag(STORAGE_LABEL, source_name)}"
                f" Filter/extraction failed for article {article_id} — will retry next cycle"
            )

    return processed, deals


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
        scraping = settings["scraping"]
        db_cfg = settings.get("database", {})

        self.db_config = ScraperDBConfig(
            neo4j_uri=neo4j_uri,
            neo4j_user=neo4j_user,
            neo4j_password=neo4j_password,
            neo4j_database=neo4j_database,
            db_pool_size=db_cfg.get("pool_size", 5),
        )
        self._scraper_kwargs = {
            "request_timeout": scraping["request_timeout"],
            "delay": scraping["delay_between_requests"],
        }
        self.max_articles = scraping["max_articles_per_source"]
        self.batch_size = scraping.get("batch_size", 10)

        self.repo = NewsRepository(
            uri=neo4j_uri,
            user=neo4j_user,
            password=neo4j_password,
            database=neo4j_database,
            pool_size=self.db_config.db_pool_size,
        )
        self.news_filter = NewsFilter()
        self.extractor = DealExtractor(Groq(api_key=groq_api_key), settings["groq"]["model"])

    def _resolve_date_range(
        self,
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> tuple[Optional[datetime], Optional[datetime]]:
        """Parse the optional start/end date strings into IST datetimes."""
        if not (start_date and end_date):
            return None, None
        dt_start = _to_ist_datetime(start_date, end_of_day=False)
        dt_end = _to_ist_datetime(end_date, end_of_day=True)
        logger.info(f"Date range filter: {start_date} → {end_date} (IST)")
        return dt_start, dt_end

    def _scrape_all_sources(
        self,
        sources: list[dict],
        dt_start: Optional[datetime],
        dt_end: Optional[datetime],
        counters: dict,
        company: Optional[str] = None,
    ) -> tuple[int, list[dict]]:
        """
        Run one scrape worker process per source concurrently and collect
        their results once every one of them has finished (join).
        """
        jobs = [(source, company) for source in sources]
        return self._run_scrape_jobs(jobs, dt_start, dt_end, counters)

    def _run_scrape_jobs(
        self,
        jobs: list[tuple[dict, Optional[str]]],
        dt_start: Optional[datetime],
        dt_end: Optional[datetime],
        counters: dict,
    ) -> tuple[int, list[dict]]:
        """
        Run every `(source, company)` job in one process pool and join.

        A job with `company=None` scrapes that source's section listing; with a
        company it runs the source's on-site search for that name. Keeping all
        jobs in a single pool is what makes a watchlist run affordable — a pool
        per company would spawn one per entity.

        Each returned article carries `searched_company`, so the caller can tell
        a targeted hit from a listing article that still needs gating.
        """
        total_scraped = 0
        all_articles: list[dict] = []

        ctx = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=MAX_THREADS, mp_context=ctx) as executor:
            futures = {
                executor.submit(
                    _scrape_source_worker,
                    source, dt_start, dt_end, self._scraper_kwargs,
                    self.max_articles, self.db_config, company,
                ): (source["name"], company)
                for source, company in jobs
            }
            for future in as_completed(futures):
                source_name, company = futures[future]
                label = f"[{source_name}]" + (f" (company='{company}')" if company else "")
                try:
                    result = future.result()
                except Exception as exc:
                    logger.exception(f"{_tag(SCRAPER_LABEL)} Worker crashed for {label}")
                    counters["errors"].append(f"{source_name}: {exc!r}")
                    continue

                if result["error"]:
                    counters["errors"].append(f"{source_name}: {result['error']}")
                    logger.error(
                        f"{_tag(SCRAPER_LABEL)} Error scraping {label}: {result['error']}"
                    )
                    continue

                total_scraped += result["link_count"]
                all_articles.extend(
                    {**article, "searched_company": company} for article in result["articles"]
                )
                logger.info(
                    f"{_tag(SCRAPER_LABEL)} {label} joined"
                    f" — {len(result['articles'])} article(s)"
                )

        return total_scraped, all_articles

    def scrape_and_store(
        self,
        sources: list[dict],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> dict:
        """
        Scrape all sources in parallel (one process per source) and store the
        results in fixed-size batches once every source has finished (join).
        No filtering/extraction here — that's extract_pending()'s job, so this
        can run on its own schedule (ScrapperScheduler).
        """
        dt_start, dt_end = self._resolve_date_range(start_date, end_date)
        counters = {"scraped": 0, "new": 0, "errors": []}

        logger.info(f"Scrape cycle started — {len(sources)} source(s) scraping in parallel")

        total_scraped, all_articles = self._scrape_all_sources(
            sources, dt_start, dt_end, counters
        )
        counters["scraped"] = total_scraped

        logger.info(
            f"{_tag(SCRAPER_LABEL)} All sources scraped and joined."
            f" {len(all_articles)} article(s) to store in batches of {self.batch_size}"
        )

        for i in range(0, len(all_articles), self.batch_size):
            batch = all_articles[i:i + self.batch_size]
            batch_num = i // self.batch_size
            try:
                inserted = _store_batch(batch, self.repo)
                counters["new"] += len(inserted)
            except Exception as exc:
                logger.exception(f"{_tag(STORAGE_LABEL)} Batch {batch_num} store failed")
                counters["errors"].append(f"batch {batch_num}: {exc!r}")

        logger.info(
            f"Scrape cycle complete — scraped: {counters['scraped']}, new: {counters['new']}"
        )
        if counters["errors"]:
            logger.error(f"Scrape cycle completed with errors: {counters['errors']}")
        return counters

    def scrape_company(
        self,
        company: str,
        sources: list[dict],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> dict:
        """
        Scrape a single company's news from every source that supports on-site
        search (`search_url`), store the results, then filter/extract deals over
        everything currently pending — end-to-end, mirroring `run` but scoped to
        one company. Sources without a `search_url` are skipped (logged).
        """
        searchable = [s for s in sources if s.get("search_url")]
        skipped = [s["name"] for s in sources if not s.get("search_url")]
        if skipped:
            logger.info(
                f"Company scrape '{company}': skipping {len(skipped)} source(s)"
                f" without search_url: {', '.join(skipped)}"
            )

        dt_start, dt_end = self._resolve_date_range(start_date, end_date)
        counters = {"company": company, "scraped": 0, "new": 0, "deals": 0, "errors": []}

        if not searchable:
            logger.warning(f"Company scrape '{company}': no searchable sources configured")
            counters["errors"].append("no sources with search_url configured")
            return counters

        logger.info(
            f"Company scrape '{company}' started — {len(searchable)} searchable source(s)"
        )

        total_scraped, all_articles = self._scrape_all_sources(
            searchable, dt_start, dt_end, counters, company=company
        )
        counters["scraped"] = total_scraped

        for i in range(0, len(all_articles), self.batch_size):
            batch = all_articles[i:i + self.batch_size]
            batch_num = i // self.batch_size
            try:
                inserted = _store_batch(batch, self.repo)
                counters["new"] += len(inserted)
            except Exception as exc:
                logger.exception(f"{_tag(STORAGE_LABEL)} Batch {batch_num} store failed")
                counters["errors"].append(f"batch {batch_num}: {exc!r}")

        extract_counters = self.extract_pending(limit=None)
        counters["deals"] = extract_counters["deals"]
        counters["errors"].extend(extract_counters["errors"])

        logger.info(
            f"Company scrape '{company}' complete — scraped: {counters['scraped']},"
            f" new: {counters['new']}, deals: {counters['deals']}"
        )
        if counters["errors"]:
            logger.error(f"Company scrape '{company}' completed with errors: {counters['errors']}")
        return counters

    def scrape_watchlist(
        self,
        entries: list,
        sources: list[dict],
        matcher=None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        max_search_entities: Optional[int] = None,
    ) -> dict:
        """
        Scrape news restricted to the companies tracked in the company DB.

        Two paths, because only some sources expose an on-site search:

        - sources with `search_url` run one targeted search per watchlist entry
          (capped by `max_search_entities`);
        - sources without one scrape their listing as usual, and `matcher` then
          drops every article that mentions no tracked company.

        All jobs share one process pool, and filter/extraction runs **once** at
        the end over everything pending — unlike `scrape_company()`, which is
        scoped to a single company and extracts on every call.
        """
        searchable = [s for s in sources if s.get("search_url")]
        listing = [s for s in sources if not s.get("search_url")]

        search_entries = entries[:max_search_entities] if max_search_entities else entries
        dt_start, dt_end = self._resolve_date_range(start_date, end_date)

        counters = {
            "entities": len(search_entries),
            "search_jobs": 0,
            "scraped": 0,
            "gated_out": 0,
            "new": 0,
            "deals": 0,
            "errors": [],
        }

        jobs: list[tuple[dict, Optional[str]]] = [
            (source, entry.search_term) for source in searchable for entry in search_entries
        ]
        counters["search_jobs"] = len(jobs)
        if matcher is not None:
            jobs.extend((source, None) for source in listing)
        elif listing:
            logger.info(
                f"Watchlist run: no matcher supplied, skipping {len(listing)} listing source(s)"
            )

        if not jobs:
            logger.warning("Watchlist run: nothing to do — no entities and no gated sources")
            counters["errors"].append("no scrape jobs to run")
            return counters

        logger.info(
            f"Watchlist run started — {len(search_entries)} entity/entities across"
            f" {len(searchable)} searchable source(s),"
            f" {len(listing) if matcher is not None else 0} gated listing source(s)"
        )

        total_scraped, all_articles = self._run_scrape_jobs(jobs, dt_start, dt_end, counters)
        counters["scraped"] = total_scraped

        # Articles from a targeted search are already entity-scoped. Listing
        # articles have to earn their place by naming a tracked company.
        targeted = [a for a in all_articles if a.get("searched_company")]
        untargeted = [a for a in all_articles if not a.get("searched_company")]
        if matcher is not None and untargeted:
            kept, dropped = gate_articles(untargeted, matcher)
            counters["gated_out"] = dropped
            logger.info(
                f"{_tag(SCRAPER_LABEL)} Entity gate: kept {len(kept)} of"
                f" {len(untargeted)} listing article(s), dropped {dropped}"
            )
        else:
            kept = untargeted

        to_store = targeted + kept
        for i in range(0, len(to_store), self.batch_size):
            batch = to_store[i:i + self.batch_size]
            batch_num = i // self.batch_size
            try:
                inserted = _store_batch(batch, self.repo)
                counters["new"] += len(inserted)
            except Exception as exc:
                logger.exception(f"{_tag(STORAGE_LABEL)} Batch {batch_num} store failed")
                counters["errors"].append(f"batch {batch_num}: {exc!r}")

        extract_counters = self.extract_pending(limit=None)
        counters["deals"] = extract_counters["deals"]
        counters["errors"].extend(extract_counters["errors"])

        logger.info(
            f"Watchlist run complete — scraped: {counters['scraped']},"
            f" gated out: {counters['gated_out']}, new: {counters['new']},"
            f" deals: {counters['deals']}"
        )
        if counters["errors"]:
            logger.error(f"Watchlist run completed with errors: {counters['errors']}")
        return counters

    def extract_pending(self, limit: Optional[int] = None) -> dict:
        """
        Filter/extract over articles that are already stored but haven't been
        filtered yet (is_ma_funding_relevant IS NULL) — independent of when or
        by whom they were scraped, so this self-heals any article left behind
        by a previous failed cycle. Runs on its own schedule (ExtractionScheduler).
        """
        counters = {"processed": 0, "deals": 0, "errors": []}

        articles = self.repo.get_unprocessed_articles(limit)
        logger.info(
            f"{_tag(STORAGE_LABEL)} Extraction cycle started — {len(articles)} pending article(s)"
        )
        if not articles:
            return counters

        try:
            processed, deals = _filter_and_extract_articles(
                articles, self.repo, self.news_filter, self.extractor
            )
            counters["processed"] = processed
            counters["deals"] = deals
        except Exception as exc:
            logger.exception(f"{_tag(STORAGE_LABEL)} Extraction cycle failed")
            counters["errors"].append(repr(exc))

        logger.info(
            f"Extraction cycle complete — processed: {counters['processed']}, deals: {counters['deals']}"
        )
        if counters["errors"]:
            logger.error(f"Extraction cycle completed with errors: {counters['errors']}")
        return counters

    def run(
        self,
        sources: list[dict],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> None:
        """
        One-shot end-to-end run (used by the CLI): scrape and store everything,
        then process everything currently pending — including any backlog left
        over from earlier runs.
        """
        scrape_counters = self.scrape_and_store(sources, start_date, end_date)
        extract_counters = self.extract_pending(limit=None)

        logger.info(
            f"Run complete — scraped: {scrape_counters['scraped']},"
            f" new: {scrape_counters['new']}, deals: {extract_counters['deals']}"
        )
        errors = scrape_counters["errors"] + extract_counters["errors"]
        if errors:
            logger.error(f"Run completed with errors: {errors}")
