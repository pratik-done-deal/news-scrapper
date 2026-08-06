"""RSS covers the routine firehose; company scrapes and backfill keep the site scraper."""

from datetime import datetime, timedelta, timezone

from src.agent import _build_scraper, _scrape_links
from src.scraper.rss_scraper import RSSScraper
from src.scraper.web_scraper import EntrackrScraper

IST = timezone(timedelta(hours=5, minutes=30))
KWARGS = {"request_timeout": 5, "delay": 0}

FEED_SOURCE = {
    "name": "Entrackr News",
    "url": "https://entrackr.com/news",
    "rss_url": "https://entrackr.com/rss",
    "search_url": "https://entrackr.com/search?title={query}",
    "domain": "entrackr.com",
    "link_contains": "/news/",
    "scraper": "entrackr",
    "paginate": True,
}

NO_FEED_SOURCE = {
    "name": "Financial Express Market",
    "url": "https://www.financialexpress.com/market/",
    "domain": "financialexpress.com",
    "link_contains": "/market/",
    "scraper": "fe",
    "paginate": True,
}

START = datetime(2026, 8, 1, tzinfo=IST)
END = datetime(2026, 8, 5, 23, 59, 59, tzinfo=IST)


def test_routine_run_on_a_feed_source_uses_rss():
    scraper, listing_url = _build_scraper(FEED_SOURCE, None, None, None, KWARGS)

    assert isinstance(scraper, RSSScraper)
    assert listing_url == "https://entrackr.com/rss"


def test_company_scrape_uses_the_site_scraper_not_rss():
    """Feeds cannot be searched, so a company job must reach the on-site search."""
    scraper, listing_url = _build_scraper(FEED_SOURCE, "Zomato", None, None, KWARGS)

    assert isinstance(scraper, EntrackrScraper)
    assert listing_url == "https://entrackr.com/news"


def test_date_range_backfill_uses_the_site_scraper_not_rss():
    """Feeds hold only a few days and cannot paginate, so backfill needs the listing walk."""
    scraper, listing_url = _build_scraper(FEED_SOURCE, None, START, END, KWARGS)

    assert isinstance(scraper, EntrackrScraper)
    assert listing_url == "https://entrackr.com/news"


def test_source_without_a_feed_always_uses_its_scraper():
    scraper, listing_url = _build_scraper(NO_FEED_SOURCE, None, None, None, KWARGS)

    assert not isinstance(scraper, RSSScraper)
    assert listing_url == "https://www.financialexpress.com/market/"


def test_partial_date_range_still_uses_rss():
    """A lone start/end never triggers the range path, so RSS remains correct."""
    scraper, _ = _build_scraper(FEED_SOURCE, None, START, None, KWARGS)

    assert isinstance(scraper, RSSScraper)


class _RecordingScraper:
    def __init__(self):
        self.calls = []

    def get_article_links(self, source_url, domain, link_contains, max_articles):
        self.calls.append(("listing", source_url))
        return []

    def get_article_links_in_date_range(self, source_url, **kwargs):
        self.calls.append(("range", source_url))
        return []

    def get_company_article_links(self, search_url, **kwargs):
        self.calls.append(("search", search_url))
        return []


def test_scrape_links_reads_the_listing_url_it_was_given():
    scraper = _RecordingScraper()

    _scrape_links(scraper, FEED_SOURCE, 20, None, None, None, "https://entrackr.com/rss")

    assert scraper.calls == [("listing", "https://entrackr.com/rss")]


def test_scrape_links_defaults_to_the_source_url():
    scraper = _RecordingScraper()

    _scrape_links(scraper, FEED_SOURCE, 20, None, None, None, None)

    assert scraper.calls == [("listing", "https://entrackr.com/news")]


def test_scrape_links_company_path_ignores_listing_url():
    scraper = _RecordingScraper()

    _scrape_links(scraper, FEED_SOURCE, 20, None, None, "Zomato", "https://entrackr.com/rss")

    assert scraper.calls == [("search", "https://entrackr.com/search?title={query}")]


def test_scrape_links_date_range_uses_listing_url():
    scraper = _RecordingScraper()

    _scrape_links(scraper, FEED_SOURCE, 20, START, END, None, "https://entrackr.com/news")

    assert scraper.calls == [("range", "https://entrackr.com/news")]
