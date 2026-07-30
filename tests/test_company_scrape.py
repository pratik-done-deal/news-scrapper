from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from src.api.schemas import CompanyScrapeRequest
from src.scraper.web_scraper import EntrackrScraper, IndianStartupNewsScraper


IST = timezone(timedelta(hours=5, minutes=30))


# Mirrors the Quintype JEG-theme /search?title= results template shared by
# Entrackr and Indian Startup News: div.search_post_div cards, article links
# under /news/<slug>-<id>, trailing "DD Mon YYYY" date text, ?page=N pagination.
# Note the first card is the search-header card (search box, no article link).
SEARCH_RESULTS_HTML = """
<html>
  <body>
    <div class="bigTileArticles">
      <div class="abc search_post_div">
        <div id="search_page_input">
          <form action="/search"><input name="title" value="Whatsapp"/></form>
        </div>
        <h1 class="search_result_title">Search Results for 'Whatsapp'</h1>
      </div>
      <div class="abc search_post_div">
        <a href="/news/whatsapp-overtakes-cred-in-upi-volume-12194247">
          WhatsApp overtakes CRED in UPI volume
        </a>
        <span class="author">Harsh Upadhyay</span>
        <span class="date">24 Jul 2026</span>
      </div>
      <div class="abc search_post_div">
        <a href="/news/whatsapp-pay-crosses-100m-users-12064400">
          WhatsApp Pay crosses 100M users
        </a>
        <span class="author">Some Author</span>
        <span class="date">20 Jul 2026</span>
      </div>
      <a class="paginate" href="?page=2&title=Whatsapp" aria-label="page 2">2</a>
    </div>
  </body>
</html>
"""


def test_build_search_url_encodes_company():
    scraper = EntrackrScraper(delay=0)
    url = scraper._build_search_url("https://entrackr.com/search?title={query}", "Reliance Retail")
    assert url == "https://entrackr.com/search?title=Reliance+Retail"


def test_search_links_with_dates_parses_quintype_cards():
    scraper = EntrackrScraper(delay=0)
    items = scraper._search_links_with_dates(
        SEARCH_RESULTS_HTML,
        "https://entrackr.com/search?title=Whatsapp",
        "entrackr.com",
        "/news/",
    )
    assert items == [
        (
            "https://entrackr.com/news/whatsapp-overtakes-cred-in-upi-volume-12194247",
            datetime(2026, 7, 24, tzinfo=IST),
        ),
        (
            "https://entrackr.com/news/whatsapp-pay-crosses-100m-users-12064400",
            datetime(2026, 7, 20, tzinfo=IST),
        ),
    ]


def test_get_company_article_links_first_page():
    scraper = EntrackrScraper(delay=0)
    captured = {}

    def fake_fetch(url):
        captured["url"] = url
        return SEARCH_RESULTS_HTML

    scraper._fetch_html = fake_fetch

    links = scraper.get_company_article_links(
        search_url="https://entrackr.com/search?title={query}",
        domain="entrackr.com",
        link_contains="/news/",
        company="Whatsapp",
        max_articles=10,
    )

    assert captured["url"] == "https://entrackr.com/search?title=Whatsapp"
    assert links == [
        "https://entrackr.com/news/whatsapp-overtakes-cred-in-upi-volume-12194247",
        "https://entrackr.com/news/whatsapp-pay-crosses-100m-users-12064400",
    ]


def test_get_company_article_links_date_range_filters():
    scraper = EntrackrScraper(delay=0)
    scraper._fetch_html = lambda url: SEARCH_RESULTS_HTML

    links = scraper.get_company_article_links(
        search_url="https://entrackr.com/search?title={query}",
        domain="entrackr.com",
        link_contains="/news/",
        company="Whatsapp",
        start_date=datetime(2026, 7, 24, 0, 0, tzinfo=IST),
        end_date=datetime(2026, 7, 24, 23, 59, 59, tzinfo=IST),
        max_pages=1,
    )

    # Only the Jul 24 article is in range; the Jul 20 one is excluded.
    assert links == [
        "https://entrackr.com/news/whatsapp-overtakes-cred-in-upi-volume-12194247"
    ]


def test_isn_search_matches_news_paths_not_funding():
    # Indian Startup News search results link to /news/, not the /funding/ its
    # section listing uses — the shared mixin must still find them.
    scraper = IndianStartupNewsScraper(delay=0)
    items = scraper._search_links_with_dates(
        SEARCH_RESULTS_HTML.replace("entrackr.com", "indianstartupnews.com"),
        "https://indianstartupnews.com/search?title=Whatsapp",
        "indianstartupnews.com",
        "/funding/",  # source's listing link_contains — ignored by search parser
    )
    assert [u for u, _ in items] == [
        "https://indianstartupnews.com/news/whatsapp-overtakes-cred-in-upi-volume-12194247",
        "https://indianstartupnews.com/news/whatsapp-pay-crosses-100m-users-12064400",
    ]


def test_company_scrape_request_requires_company():
    with pytest.raises(ValidationError):
        CompanyScrapeRequest(company="")


def test_company_scrape_request_rejects_bad_date():
    with pytest.raises(ValidationError):
        CompanyScrapeRequest(company="Zomato", start_date="2026/01/01", end_date="2026-02-01")


def test_company_scrape_request_requires_date_pair():
    with pytest.raises(ValidationError):
        CompanyScrapeRequest(company="Zomato", start_date="2026-01-01")


def test_company_scrape_request_valid():
    req = CompanyScrapeRequest(
        company="Zomato", start_date="2026-01-01", end_date="2026-02-01", sources=["Entrackr News"]
    )
    assert req.company == "Zomato"
    assert req.sources == ["Entrackr News"]
