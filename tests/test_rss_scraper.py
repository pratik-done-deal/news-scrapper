from datetime import datetime, timedelta, timezone

from src.scraper.rss_scraper import RSSScraper, _parse_feed_date

IST = timezone(timedelta(hours=5, minutes=30))

LONG_BODY = "River Mobility has raised $120 million in a Series C round. " * 20  # >600 chars
SHORT_BODY = "Markets closed higher on Tuesday."


def _feed(items_xml: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">'
        f"<channel><title>Entrackr</title>{items_xml}</channel></rss>"
    ).encode()


def _item(url, title="Some deal", body=LONG_BODY, date="Wed, 05 Aug 2026 17:12:25 +0530",
          tag="description"):
    return (
        f"<item><title>{title}</title><link>{url}</link>"
        f"<pubDate>{date}</pubDate><{tag}>{body}</{tag}></item>"
    )


def _scraper(xml: bytes, source_config=None) -> RSSScraper:
    scraper = RSSScraper(request_timeout=5, delay=0)
    scraper._fetch_bytes = lambda url: xml
    # Never touch the network: tests that exercise the fallback stub this themselves.
    scraper._fetch_html = lambda url: None
    scraper.source_config = source_config or {}
    return scraper


def _recent(hours_ago=1):
    return (datetime.now(IST) - timedelta(hours=hours_ago)).strftime("%a, %d %b %Y %H:%M:%S %z")


# --------------------------------------------------------------------------
# date parsing
# --------------------------------------------------------------------------

def test_parses_rfc822_pubdate_to_ist():
    parsed = _parse_feed_date("Wed, 05 Aug 2026 17:12:25 +0530")
    assert parsed == datetime(2026, 8, 5, 17, 12, 25, tzinfo=IST)


def test_converts_other_offsets_into_ist():
    # 12:00 UTC is 17:30 IST — the pipeline compares against IST-aware bounds.
    parsed = _parse_feed_date("Wed, 05 Aug 2026 12:00:00 +0000")
    assert parsed.utcoffset() == timedelta(hours=5, minutes=30)
    assert (parsed.hour, parsed.minute) == (17, 30)


def test_parses_iso_dates_from_atom_feeds():
    assert _parse_feed_date("2026-08-05T17:12:25+05:30") == datetime(
        2026, 8, 5, 17, 12, 25, tzinfo=IST
    )


def test_missing_or_unparseable_date_is_none():
    assert _parse_feed_date(None) is None
    assert _parse_feed_date("   ") is None
    assert _parse_feed_date("last tuesday") is None


# --------------------------------------------------------------------------
# link discovery
# --------------------------------------------------------------------------

def test_returns_feed_links_and_caches_bodies():
    xml = _feed(_item("https://entrackr.com/news/a") + _item("https://entrackr.com/news/b"))
    scraper = _scraper(xml)

    links = scraper.get_article_links("https://entrackr.com/rss", "entrackr.com", "/news/", 20)

    assert links == ["https://entrackr.com/news/a", "https://entrackr.com/news/b"]
    assert len(scraper._cache) == 2


def test_ignores_link_contains_by_default():
    """ISN lists /funding/ but its feed serves /news/ — applying the section
    filter would drop every item."""
    xml = _feed(_item("https://indianstartupnews.com/news/nykaa-q1"))
    scraper = _scraper(xml)

    links = scraper.get_article_links(
        "https://indianstartupnews.com/rss", "indianstartupnews.com", "/funding/", 20
    )

    assert links == ["https://indianstartupnews.com/news/nykaa-q1"]


def test_rss_link_contains_opts_the_path_filter_back_in():
    xml = _feed(
        _item("https://entrackr.com/news/keep") + _item("https://entrackr.com/videos/drop")
    )
    scraper = _scraper(xml, {"rss_link_contains": "/news/"})

    links = scraper.get_article_links("https://entrackr.com/rss", "entrackr.com", "", 20)

    assert links == ["https://entrackr.com/news/keep"]


def test_drops_offdomain_items():
    xml = _feed(
        _item("https://entrackr.com/news/keep") + _item("https://sponsored.example.com/promo")
    )
    scraper = _scraper(xml)

    links = scraper.get_article_links("https://entrackr.com/rss", "entrackr.com", "", 20)

    assert links == ["https://entrackr.com/news/keep"]


def test_honours_max_articles():
    xml = _feed("".join(_item(f"https://entrackr.com/news/{i}") for i in range(10)))
    scraper = _scraper(xml)

    assert len(scraper.get_article_links("https://entrackr.com/rss", "entrackr.com", "", 3)) == 3


def test_returns_empty_when_feed_fetch_fails():
    scraper = RSSScraper(request_timeout=5, delay=0)
    scraper._fetch_bytes = lambda url: None

    assert scraper.get_article_links("https://entrackr.com/rss", "entrackr.com", "", 20) == []


def test_returns_empty_on_feed_with_no_items():
    scraper = _scraper(_feed(""))

    assert scraper.get_article_links("https://entrackr.com/rss", "entrackr.com", "", 20) == []


def test_recovers_from_malformed_xml():
    """Publisher feeds routinely carry unescaped entities; a strict parse would
    lose the whole source over one bad item."""
    broken = _feed(_item("https://entrackr.com/news/a")).replace(b"</channel>", b"")
    scraper = _scraper(broken)

    assert scraper.get_article_links("https://entrackr.com/rss", "entrackr.com", "", 20) == [
        "https://entrackr.com/news/a"
    ]


def test_parses_atom_entries():
    atom = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom">'
        "<entry><title>Deal</title>"
        '<link href="https://entrackr.com/news/atom-item"/>'
        "<updated>2026-08-05T17:12:25+05:30</updated>"
        f"<content>{LONG_BODY}</content></entry></feed>"
    ).encode()
    scraper = _scraper(atom)

    links = scraper.get_article_links("https://entrackr.com/rss", "entrackr.com", "", 20)

    assert links == ["https://entrackr.com/news/atom-item"]
    title, content, published = scraper.extract_article(links[0])
    assert title == "Deal"
    assert published == datetime(2026, 8, 5, 17, 12, 25, tzinfo=IST)


# --------------------------------------------------------------------------
# extract_article — cache vs fallback
# --------------------------------------------------------------------------

def test_full_body_is_served_from_feed_without_fetching():
    xml = _feed(_item("https://entrackr.com/news/a", title="River Mobility raises $120 Mn"))
    scraper = _scraper(xml)
    scraper.get_article_links("https://entrackr.com/rss", "entrackr.com", "", 20)
    scraper._fetch_html = lambda url: (_ for _ in ()).throw(
        AssertionError("must not fetch when the feed carried the body")
    )

    title, content, published = scraper.extract_article("https://entrackr.com/news/a")

    assert title == "River Mobility raises $120 Mn"
    assert content.startswith("River Mobility has raised $120 million")
    assert published == datetime(2026, 8, 5, 17, 12, 25, tzinfo=IST)


def test_content_encoded_is_preferred_over_description():
    xml = _feed(
        "<item><title>T</title><link>https://inc42.com/buzz/a</link>"
        "<pubDate>Wed, 05 Aug 2026 17:12:25 +0530</pubDate>"
        "<description>teaser only</description>"
        f"<content:encoded>{LONG_BODY}</content:encoded></item>"
    )
    scraper = _scraper(xml)
    scraper.get_article_links("https://inc42.com/feed/", "inc42.com", "", 20)

    _, content, _ = scraper.extract_article("https://inc42.com/buzz/a")

    assert content.startswith("River Mobility has raised")


def test_html_is_stripped_from_feed_body():
    xml = _feed(_item("https://entrackr.com/news/a", body=f"<p>{LONG_BODY}</p><a href='#'>x</a>"))
    scraper = _scraper(xml)
    scraper.get_article_links("https://entrackr.com/rss", "entrackr.com", "", 20)

    _, content, _ = scraper.extract_article("https://entrackr.com/news/a")

    assert "<p>" not in content and "href" not in content


def test_teaser_body_falls_back_to_fetching_the_article():
    """CNBC/ET ship ~100-char blurbs — too thin to filter or extract on."""
    xml = _feed(_item("https://www.cnbc.com/2026/08/05/deal", title="Feed title", body=SHORT_BODY))
    scraper = _scraper(xml)
    scraper.get_article_links("https://feed", "cnbc.com", "", 20)
    scraper._fetch_html = lambda url: "<html><h1>Full title</h1><p>Full article body.</p></html>"

    title, content, published = scraper.extract_article("https://www.cnbc.com/2026/08/05/deal")

    assert title == "Full title"
    assert content and "Full article body" in content
    # page had no parseable date, so the feed's publisher-supplied one is kept
    assert published == datetime(2026, 8, 5, 17, 12, 25, tzinfo=IST)


def test_uncached_url_falls_through_to_normal_fetch():
    scraper = _scraper(_feed(""))
    scraper._fetch_html = lambda url: "<html><h1>Other</h1><p>Body text here.</p></html>"

    title, _, _ = scraper.extract_article("https://entrackr.com/news/never-seen")

    assert title == "Other"


# --------------------------------------------------------------------------
# staleness guard
# --------------------------------------------------------------------------

def test_warns_when_feed_is_stale(caplog):
    """A dead feed (Moneycontrol's stopped in 2024) otherwise looks like a quiet day."""
    xml = _feed(_item("https://entrackr.com/news/a", date="Tue, 23 Apr 2024 13:38:59 +0530"))
    scraper = _scraper(xml)

    with caplog.at_level("WARNING"):
        scraper.get_article_links("https://entrackr.com/rss", "entrackr.com", "", 20)

    assert "STALE" in caplog.text


def test_no_stale_warning_for_a_fresh_feed(caplog):
    xml = _feed(_item("https://entrackr.com/news/a", date=_recent(hours_ago=2)))
    scraper = _scraper(xml)

    with caplog.at_level("WARNING"):
        scraper.get_article_links("https://entrackr.com/rss", "entrackr.com", "", 20)

    assert "STALE" not in caplog.text


def test_stale_threshold_is_configurable_per_source(caplog):
    xml = _feed(_item("https://entrackr.com/news/a", date=_recent(hours_ago=5)))
    scraper = _scraper(xml, {"rss_max_age_hours": 2})

    with caplog.at_level("WARNING"):
        scraper.get_article_links("https://entrackr.com/rss", "entrackr.com", "", 20)

    assert "STALE" in caplog.text


def test_warns_when_no_item_has_a_date(caplog):
    xml = _feed("<item><title>T</title><link>https://entrackr.com/news/a</link></item>")
    scraper = _scraper(xml)

    with caplog.at_level("WARNING"):
        scraper.get_article_links("https://entrackr.com/rss", "entrackr.com", "", 20)

    assert "no usable dates" in caplog.text
