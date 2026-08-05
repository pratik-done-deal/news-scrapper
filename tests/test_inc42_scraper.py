from datetime import datetime, timedelta, timezone

import requests

from src.scraper.web_scraper import Inc42Scraper


IST = timezone(timedelta(hours=5, minutes=30))
SEARCH_API = "https://search.thed2csummit.co/query"


LISTING_HTML = """
<html>
  <body>
    <div class="card-wrapper">
      <a href="https://inc42.com/industry/fintech/">Fintech</a>
      <h2>
        <a href="https://inc42.com/buzz/cyber-risk-and-insurance-startup-mitigata-raises-15-mn/">
          Cyber Risk And Insurance Startup Mitigata Raises $15 Mn
        </a>
      </h2>
      <span class="date">23rd June, 2026</span>
    </div>
    <li data-card-id="562142">
      <a href="https://inc42.com/features/the-battle-for-indias-kirana-stores-has-begun/">
        The Battle For India's Kirana Stores Has Begun
      </a>
      <span class="date">23 Jun'26</span>
    </li>
    <div class="card-wrapper">
      <a href="https://inc42.com/tag/funding/">Funding</a>
      <span class="date">23rd June, 2026</span>
    </div>
    <a href="https://inc42.com/buzz/">News</a>
  </body>
</html>
"""


def test_inc42_listing_links_with_dates():
    scraper = Inc42Scraper(delay=0)

    items = scraper._listing_links_with_dates(
        LISTING_HTML,
        "https://inc42.com/",
        "inc42.com",
        "/",
    )

    assert items == [
        (
            "https://inc42.com/buzz/cyber-risk-and-insurance-startup-mitigata-raises-15-mn/",
            datetime(2026, 6, 23, tzinfo=IST),
        ),
        (
            "https://inc42.com/features/the-battle-for-indias-kirana-stores-has-begun/",
            datetime(2026, 6, 23, tzinfo=IST),
        ),
    ]


def test_inc42_get_article_links_uses_listing_parser():
    scraper = Inc42Scraper(delay=0)
    scraper._fetch_html = lambda url: LISTING_HTML

    links = scraper.get_article_links(
        "https://inc42.com/",
        "inc42.com",
        "/",
        max_articles=1,
    )

    assert links == [
        "https://inc42.com/buzz/cyber-risk-and-insurance-startup-mitigata-raises-15-mn/"
    ]


def test_inc42_scraper_is_first_page_only():
    scraper = Inc42Scraper(delay=0)

    assert scraper._get_next_page_url(LISTING_HTML, "https://inc42.com/") is None


# ---------------------------------------------------------------------------
# Company search API
# ---------------------------------------------------------------------------

def _result(permalink: str, post_date_ts: str) -> dict:
    """One search API result, trimmed to the fields the scraper reads."""
    return {
        "id": "567101-0",
        "name": "MapmyIndia Q1: Profit Rises 6% YoY",
        "post_date_ts": post_date_ts,
        "meta_data": {"permalink": permalink, "category": "News"},
    }


SEARCH_RESULTS = [
    _result("https://inc42.com/buzz/mapmyindia-q1-profit-rises/", "2026-08-04T11:14:18.000Z"),
    _result("https://inc42.com/buzz/mapmyindia-appoints-joint-md/", "2026-07-01T09:30:00.000Z"),
    _result("https://inc42.com/buzz/mapmyindia-acquires-iwayplus/", "2026-01-12T06:00:00.000Z"),
]


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _scraper_returning(payload):
    """An Inc42Scraper whose search API POST returns `payload`."""
    scraper = Inc42Scraper(delay=0)
    calls = []

    def fake_post(url, data=None, timeout=None):
        calls.append({"url": url, "data": data})
        return _FakeResponse(payload)

    scraper.session.post = fake_post
    scraper.search_calls = calls
    return scraper


def test_company_links_posts_query_and_returns_permalinks():
    scraper = _scraper_returning(SEARCH_RESULTS)

    links = scraper.get_company_article_links(
        SEARCH_API, "inc42.com", "/", "MapmyIndia"
    )

    assert links == [
        "https://inc42.com/buzz/mapmyindia-q1-profit-rises/",
        "https://inc42.com/buzz/mapmyindia-appoints-joint-md/",
        "https://inc42.com/buzz/mapmyindia-acquires-iwayplus/",
    ]
    assert scraper.search_calls == [{"url": SEARCH_API, "data": {"query": "MapmyIndia"}}]


def test_company_links_filters_by_date_range():
    scraper = _scraper_returning(SEARCH_RESULTS)

    links = scraper.get_company_article_links(
        SEARCH_API,
        "inc42.com",
        "/",
        "MapmyIndia",
        start_date=datetime(2026, 6, 1, tzinfo=IST),
        end_date=datetime(2026, 8, 31, 23, 59, 59, tzinfo=IST),
    )

    assert links == [
        "https://inc42.com/buzz/mapmyindia-q1-profit-rises/",
        "https://inc42.com/buzz/mapmyindia-appoints-joint-md/",
    ]


def test_company_links_honours_max_articles():
    scraper = _scraper_returning(SEARCH_RESULTS)

    links = scraper.get_company_article_links(
        SEARCH_API, "inc42.com", "/", "MapmyIndia", max_articles=1
    )

    assert links == ["https://inc42.com/buzz/mapmyindia-q1-profit-rises/"]


def test_company_links_skips_unusable_results():
    scraper = _scraper_returning(
        [
            "not-a-dict",
            {"meta_data": {}},                                    # no permalink
            {"meta_data": {"permalink": "https://example.com/x/"}},  # wrong domain
            {"meta_data": {"permalink": "https://inc42.com/"}},      # bare homepage
            _result("https://inc42.com/buzz/real-story/?utm=x", "2026-08-04T11:14:18.000Z"),
            _result("https://inc42.com/buzz/real-story/", "2026-08-04T11:14:18.000Z"),
        ]
    )

    links = scraper.get_company_article_links(
        SEARCH_API, "inc42.com", "/", "MapmyIndia"
    )

    # Query string stripped, so both rows normalise to the same URL and dedupe —
    # matching how the listing parser builds URLs.
    assert links == ["https://inc42.com/buzz/real-story/"]


def test_company_links_drops_undated_results_when_filtering():
    scraper = _scraper_returning([_result("https://inc42.com/buzz/undated/", "")])

    links = scraper.get_company_article_links(
        SEARCH_API,
        "inc42.com",
        "/",
        "MapmyIndia",
        start_date=datetime(2026, 1, 1, tzinfo=IST),
        end_date=datetime(2026, 12, 31, tzinfo=IST),
    )

    assert links == []


def test_company_links_returns_empty_when_api_fails():
    scraper = Inc42Scraper(delay=0)

    def boom(url, data=None, timeout=None):
        raise requests.RequestException("connection reset")

    scraper.session.post = boom

    assert scraper.get_company_article_links(SEARCH_API, "inc42.com", "/", "Zepto") == []


def test_company_links_returns_empty_on_unexpected_payload():
    scraper = _scraper_returning({"error": "bad request"})

    assert scraper.get_company_article_links(SEARCH_API, "inc42.com", "/", "Zepto") == []
