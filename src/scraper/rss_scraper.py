import logging
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from lxml import etree

from .web_scraper import IST, WebScraper, _parse_iso_datetime

logger = logging.getLogger(__name__)

CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"
ATOM_NS = "http://www.w3.org/2005/Atom"


def _parse_feed_date(raw: Optional[str]) -> Optional[datetime]:
    """Parse an RFC-822 (RSS) or ISO-8601 (Atom) timestamp into an IST-aware datetime.

    Feed dates carry their own offset, unlike the scraped page dates the rest of
    the pipeline works with — normalising to IST here keeps the date-range
    comparisons in `_scrape_source_worker` comparing like with like.
    """
    if not raw or not raw.strip():
        return None
    raw = raw.strip()
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        parsed = _parse_iso_datetime(raw)
    if not parsed:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=IST)
    return parsed.astimezone(IST)


def _text_of(html: Optional[str]) -> str:
    """Strip the HTML markup feeds wrap their body text in."""
    if not html:
        return ""
    return " ".join(BeautifulSoup(html, "lxml").get_text(" ").split())


def _node_text(node, *tags: str) -> Optional[str]:
    """Return the first non-empty element's full text, trying each tag in order.

    Feeds carry article HTML three ways — escaped entities, CDATA, or (invalidly
    but commonly) live child elements — and `findtext` silently returns nothing
    for the third. Walking `itertext` is the only read that survives all three.
    Tags are tried in order, which is how content:encoded wins over description.
    """
    for tag in tags:
        element = node.find(tag)
        if element is not None:
            text = "".join(element.itertext())
            if text.strip():
                return text
    return None


class RSSScraper(WebScraper):
    """Reads a publisher's own RSS/Atom feed instead of parsing its listing pages.

    A feed hands over what the listing scrapers have to infer — article URL,
    headline, publish timestamp — and on several sources (Entrackr, Indian
    Startup News, Inc42) the full article body as well. Items whose body is
    substantial are cached during link discovery and served straight back from
    `extract_article`, so a scrape cycle costs one HTTP request for the whole
    source instead of one per article, and skips the inter-article delay.

    Feeds carry no archive — typically 1-7 days, with no pagination — and no
    search, so date-range backfill and company-scoped runs still go through the
    site scrapers. `_build_scraper` in the agent owns that routing.
    """

    #: Bodies shorter than this are teasers (ET/CNBC/Livemint ship ~100-250 chars),
    #: so the article itself is fetched instead.
    MIN_BODY_CHARS = 600
    #: A feed that has silently died looks exactly like a quiet news day, so warn
    #: when nothing is recent. Moneycontrol's business feed stopped in April 2024.
    MAX_AGE_HOURS = 48

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cache: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Listing-page contract — unused: feeds are parsed in get_article_links
    # ------------------------------------------------------------------

    def _listing_links_with_dates(self, html, source_url, domain, link_contains):
        return []

    def _get_next_page_url(self, html, current_url):
        return None  # feeds expose no pagination

    # ------------------------------------------------------------------

    def _fetch_bytes(self, url: str) -> Optional[bytes]:
        """Fetch raw bytes — XML must be decoded per its own encoding declaration."""
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            return response.content
        except Exception as exc:
            logger.warning(f"  Failed to fetch feed {url}: {exc}")
            return None

    def _parse_items(self, xml: bytes) -> list[dict]:
        """Parse feed bytes into {url, title, body, published_date} dicts.

        Uses a recovering parser because publisher feeds are routinely served
        with unescaped entities or stray markup that strict parsing rejects.
        """
        try:
            root = etree.fromstring(xml, parser=etree.XMLParser(recover=True))
        except etree.XMLSyntaxError as exc:
            logger.warning(f"  Feed XML could not be parsed: {exc}")
            return []
        if root is None:
            return []

        nodes = root.findall(".//item") or root.findall(f".//{{{ATOM_NS}}}entry")
        items: list[dict] = []
        for node in nodes:
            url = (_node_text(node, "link") or "").strip()
            if not url:  # Atom puts the URL in an attribute
                link_el = node.find(f"{{{ATOM_NS}}}link")
                url = (link_el.get("href") or "").strip() if link_el is not None else ""
            if not url:
                continue

            raw_body = _node_text(
                node,
                f"{{{CONTENT_NS}}}encoded",   # full article when the publisher ships it
                "description",
                f"{{{ATOM_NS}}}content",
                f"{{{ATOM_NS}}}summary",
            )
            raw_date = _node_text(
                node,
                "pubDate",
                "{http://purl.org/dc/elements/1.1/}date",
                f"{{{ATOM_NS}}}updated",
                f"{{{ATOM_NS}}}published",
            )
            title = _node_text(node, "title", f"{{{ATOM_NS}}}title")

            items.append({
                "url": url,
                "title": " ".join(title.split()) if title else None,
                "body": _text_of(raw_body),
                "published_date": _parse_feed_date(raw_date),
            })
        return items

    def _warn_if_stale(self, items: list[dict], feed_url: str) -> None:
        max_age = self.source_config.get("rss_max_age_hours", self.MAX_AGE_HOURS)
        dates = [i["published_date"] for i in items if i["published_date"]]
        if not dates:
            logger.warning(f"  Feed has no usable dates — check the feed format: {feed_url}")
            return
        age_hours = (datetime.now(IST) - max(dates)).total_seconds() / 3600
        if age_hours > max_age:
            logger.warning(
                f"  Feed looks STALE — newest item is {age_hours / 24:.1f} day(s) old"
                f" (limit {max_age}h): {feed_url}"
            )

    def get_article_links(
        self,
        source_url: str,
        domain: str,
        link_contains: str,
        max_articles: int = 20,
    ) -> list[str]:
        """Read the feed, cache each item's body, and return its article URLs.

        `link_contains` is deliberately ignored: it describes the section-listing
        markup, and feed paths often differ from it (Indian Startup News lists
        /funding/ but its feed serves /news/), which would filter out every item.
        Set `rss_link_contains` on the source to opt back in.
        """
        xml = self._fetch_bytes(source_url)
        if not xml:
            return []

        items = self._parse_items(xml)
        if not items:
            logger.warning(f"  Feed returned no items: {source_url}")
            return []
        self._warn_if_stale(items, source_url)

        path_filter = self.source_config.get("rss_link_contains") or ""
        links: list[str] = []
        for item in items:
            parsed = urlparse(item["url"])
            if domain and domain not in parsed.netloc:
                continue
            if path_filter and path_filter not in parsed.path:
                continue
            self._cache[item["url"]] = item
            links.append(item["url"])
            if len(links) >= max_articles:
                break

        full_bodied = sum(1 for u in links if len(self._cache[u]["body"]) >= self.MIN_BODY_CHARS)
        logger.info(
            f"  Feed {source_url} — {len(items)} item(s), {len(links)} usable,"
            f" {full_bodied} with full body (no article fetch needed)"
        )
        return links

    def extract_article(self, url: str):
        """Serve the article from the feed when it carried enough body text.

        Falls back to the normal fetch for teaser-only feeds, keeping the feed's
        title and publisher-supplied date, which are more reliable than anything
        recovered from the article page.
        """
        item = self._cache.get(url)
        if item and len(item["body"]) >= self.MIN_BODY_CHARS:
            return item["title"], item["body"], item["published_date"]

        title, content, published_date = super().extract_article(url)
        if not item:
            return title, content, published_date
        return (
            title or item["title"],
            content or (item["body"] or None),
            published_date or item["published_date"],
        )
