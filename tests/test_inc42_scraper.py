from datetime import datetime, timedelta, timezone

from src.scraper.web_scraper import Inc42Scraper


IST = timezone(timedelta(hours=5, minutes=30))


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
