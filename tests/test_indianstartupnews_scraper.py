from datetime import datetime, timedelta, timezone

from src.scraper.web_scraper import IndianStartupNewsScraper


IST = timezone(timedelta(hours=5, minutes=30))


LISTING_HTML = """
<html>
  <body>
    <div class="feat-a-1">
      <a href="/funding/square-yards-becomes-indias-newest-unicorn-12065114"></a>
      <span class="publish-date mx-1">
        Jun 23, 2026
        <span class="published-time">15:47</span>
        <span class="timezone-name">IST</span>
      </span>
    </div>
    <div class="small-post">
      <a href="/funding"></a>
      <a href="/funding/cybersecurity-startup-mitigata-raises-15-million-12064400"></a>
      <span class="publish-date mx-1">
        Jun 23, 2026
        <span class="published-time">13:14</span>
        <span class="timezone-name">IST</span>
      </span>
    </div>
    <a class="paginate page_hov" href="?page=2" aria-label="page 2">2</a>
  </body>
</html>
"""


def test_indianstartupnews_listing_links_with_dates():
    scraper = IndianStartupNewsScraper(delay=0)

    items = scraper._listing_links_with_dates(
        LISTING_HTML,
        "https://indianstartupnews.com/funding",
        "indianstartupnews.com",
        "/funding/",
    )

    assert items == [
        (
            "https://indianstartupnews.com/funding/square-yards-becomes-indias-newest-unicorn-12065114",
            datetime(2026, 6, 23, 15, 47, tzinfo=IST),
        ),
        (
            "https://indianstartupnews.com/funding/cybersecurity-startup-mitigata-raises-15-million-12064400",
            datetime(2026, 6, 23, 13, 14, tzinfo=IST),
        ),
    ]


def test_indianstartupnews_next_page_url():
    scraper = IndianStartupNewsScraper(delay=0)

    assert (
        scraper._get_next_page_url(LISTING_HTML, "https://indianstartupnews.com/funding")
        == "https://indianstartupnews.com/funding?page=2"
    )
    assert (
        scraper._get_next_page_url("", "https://indianstartupnews.com/funding?page=2")
        == "https://indianstartupnews.com/funding?page=3"
    )


def test_indianstartupnews_get_article_links_uses_listing_parser():
    scraper = IndianStartupNewsScraper(delay=0)
    scraper._fetch_html = lambda url: LISTING_HTML

    links = scraper.get_article_links(
        "https://indianstartupnews.com/funding",
        "indianstartupnews.com",
        "/funding/",
        max_articles=1,
    )

    assert links == [
        "https://indianstartupnews.com/funding/square-yards-becomes-indias-newest-unicorn-12065114"
    ]


def test_extract_date_from_jsonld_news_article():
    scraper = IndianStartupNewsScraper(delay=0)
    html = """
    <html>
      <head>
        <script type="application/ld+json">
          {
            "@context": "https://schema.org",
            "@type": "NewsArticle",
            "datePublished": "2026-06-23T13:14:19.419+05:30"
          }
        </script>
      </head>
    </html>
    """

    assert scraper._extract_date_from_html(html) == datetime(
        2026, 6, 23, 13, 14, 19, 419000, tzinfo=IST
    )
