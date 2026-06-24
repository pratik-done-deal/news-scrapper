import logging
import json
import re
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
import trafilatura
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# IST = UTC+5:30
IST = timezone(timedelta(hours=5, minutes=30))

# Matches ET article date: "Last Updated: Feb 28, 2025, 04:40:00 PM IST"
# Also handles "Updated:", "Published:" and spaces around colons in time ("04 : 40 : 00")
_ET_ARTICLE_DATE_RE = re.compile(
    r'(?:(?:Last\s+)?[Uu]pdated|[Pp]ublished)\s*[:\-]?\s*'
    r'(\w{3}\s+\d{1,2},\s*\d{4},\s*\d{1,2}\s*[:\s]\s*\d{2}\s*[:\s]\s*\d{2}\s*[AP]M\s*IST)',
    re.IGNORECASE,
)

# Matches ET listing page date: "May 12, 2026, 12:19 PM IST"
_ET_LISTING_DATE_RE = re.compile(
    r'(\w{3}\s+\d{1,2},\s*\d{4},\s*\d{1,2}:\d{2}\s*[AP]M\s*IST)',
    re.IGNORECASE,
)

# Matches IIFL listing page date: "23 Oct 2024" + "10:11 AM" (two separate spans in div.xnG0xq)
_IIFL_LISTING_DATE_RE = re.compile(
    r'(\d{1,2}\s+\w{3}\s+\d{4})\s*\|?\s*(\d{1,2}:\d{2}\s*[AP]M)',
    re.IGNORECASE,
)

_ISN_LISTING_DATE_RE = re.compile(
    r'(\w{3}\s+\d{1,2},\s*\d{4})(?:\s+(\d{1,2}:\d{2}))?\s*IST',
    re.IGNORECASE,
)

_INC42_LONG_DATE_RE = re.compile(
    r'(\d{1,2})(?:st|nd|rd|th)\s+(\w+),\s*(\d{4})',
    re.IGNORECASE,
)
_INC42_SHORT_DATE_RE = re.compile(r"(\d{1,2})\s+(\w{3})'(\d{2})", re.IGNORECASE)


def _parse_iso_datetime(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _find_jsonld_date(node) -> Optional[datetime]:
    if isinstance(node, list):
        for item in node:
            date = _find_jsonld_date(item)
            if date:
                return date
        return None

    if not isinstance(node, dict):
        return None

    raw_date = node.get("datePublished") or node.get("dateModified")
    if isinstance(raw_date, str):
        date = _parse_iso_datetime(raw_date)
        if date:
            return date

    for value in node.values():
        date = _find_jsonld_date(value)
        if date:
            return date

    return None


def _parse_et_article_date(text: str) -> Optional[datetime]:
    """Parse 'Last Updated: Feb 28, 2025, 04:40:00 PM IST' from ET article text."""
    m = _ET_ARTICLE_DATE_RE.search(text)
    if not m:
        return None
    raw = m.group(1).strip()
    raw = re.sub(r'\s*:\s*', ':', raw)          # "04 : 40 : 00" -> "04:40:00"
    raw = re.sub(r'\s+IST\s*$', '', raw).strip()
    for fmt in ('%b %d, %Y, %I:%M:%S %p', '%b %d, %Y, %I:%M %p'):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=IST)
        except ValueError:
            continue
    return None


def _parse_et_listing_date(text: str) -> Optional[datetime]:
    """Parse 'May 12, 2026, 12:19 PM IST' from ET listing data-time attribute."""
    m = _ET_LISTING_DATE_RE.search(text)
    if not m:
        return None
    raw = re.sub(r'\s+IST\s*$', '', m.group(1).strip()).strip()
    try:
        return datetime.strptime(raw, '%b %d, %Y, %I:%M %p').replace(tzinfo=IST)
    except ValueError:
        return None


# Livemint listing date formats:
#   Today's articles:   "4 min read 03:04 PM IST"  → time only, combine with today's date
#   Older articles:     "1 min read 12 May 2026"   → full date, no time
_LM_TIME_RE = re.compile(r'(\d{1,2}:\d{2}\s*[AP]M)\s*IST', re.IGNORECASE)
_LM_DATE_RE = re.compile(r'(\d{1,2}\s+\w{3,9}\s+\d{4})', re.IGNORECASE)


def _parse_lm_listing_date(text: str) -> Optional[datetime]:
    """
    Parse a date from Livemint's dateNew span.
    Handles two formats:
      - 'HH:MM AM/PM IST'  (today's articles) → combines with today's date in IST
      - 'DD Mon YYYY'      (older articles)    → parses directly, midnight IST
    """
    m = _LM_TIME_RE.search(text)
    if m:
        try:
            t = datetime.strptime(m.group(1).strip(), '%I:%M %p')
            today = datetime.now(tz=IST).date()
            return datetime(today.year, today.month, today.day, t.hour, t.minute, tzinfo=IST)
        except ValueError:
            pass

    m = _LM_DATE_RE.search(text)
    if m:
        raw = re.sub(r'\s+', ' ', m.group(1).strip())
        for fmt in ('%d %B %Y', '%d %b %Y'):
            try:
                return datetime.strptime(raw, fmt).replace(tzinfo=IST)
            except ValueError:
                continue

    return None


def _parse_iifl_listing_date(text: str) -> Optional[datetime]:
    """Parse '23 Oct 2024 | 10:11 AM' from IIFL card div.xnG0xq."""
    m = _IIFL_LISTING_DATE_RE.search(text)
    if not m:
        return None
    raw = f"{m.group(1).strip()} {m.group(2).strip()}"
    try:
        return datetime.strptime(raw, '%d %b %Y %I:%M %p').replace(tzinfo=IST)
    except ValueError:
        return None


def _parse_isn_listing_date(text: str) -> Optional[datetime]:
    """Parse 'Jun 23, 2026 15:47 IST' from Indian Startup News cards."""
    m = _ISN_LISTING_DATE_RE.search(text)
    if not m:
        return None
    date_part = re.sub(r'\s+', ' ', m.group(1).strip())
    time_part = m.group(2)
    raw = f"{date_part} {time_part}" if time_part else date_part
    fmt = '%b %d, %Y %H:%M' if time_part else '%b %d, %Y'
    try:
        return datetime.strptime(raw, fmt).replace(tzinfo=IST)
    except ValueError:
        return None


def _parse_inc42_listing_date(text: str) -> Optional[datetime]:
    """Parse Inc42 card dates like '23rd June, 2026' and \"23 Jun'26\"."""
    text = re.sub(r'\s+', ' ', text.strip())

    m = _INC42_LONG_DATE_RE.search(text)
    if m:
        raw = f"{m.group(1)} {m.group(2)} {m.group(3)}"
        try:
            return datetime.strptime(raw, '%d %B %Y').replace(tzinfo=IST)
        except ValueError:
            return None

    m = _INC42_SHORT_DATE_RE.search(text)
    if m:
        raw = f"{m.group(1)} {m.group(2)} 20{m.group(3)}"
        try:
            return datetime.strptime(raw, '%d %b %Y').replace(tzinfo=IST)
        except ValueError:
            return None

    return None


class WebScraper(ABC):
    def __init__(self, request_timeout: int = 30, delay: float = 2.0):
        self.timeout = request_timeout
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    # ------------------------------------------------------------------
    # Abstract methods — each subclass implements these for its site
    # ------------------------------------------------------------------

    @abstractmethod
    def _listing_links_with_dates(
        self,
        html: str,
        source_url: str,
        domain: str,
        link_contains: str,
    ) -> list[tuple[str, Optional[datetime]]]:
        """Parse a listing page and return (url, date) pairs for each article card."""

    @abstractmethod
    def _get_next_page_url(self, html: str, current_url: str) -> Optional[str]:
        """Return the URL of the next listing page, or None if there isn't one."""

    # ------------------------------------------------------------------
    # Generic internals
    # ------------------------------------------------------------------

    def _fetch_html(self, url: str) -> Optional[str]:
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch {url}: {e}")
            return None

    def _extract_date_from_html(self, html: str) -> Optional[datetime]:
        """Extract publication date from an article page."""
        soup = BeautifulSoup(html, "lxml")

        # 1. Open Graph / article meta tags (used by Livemint and many modern sites)
        for prop in ("article:published_time", "article:modified_time"):
            tag = soup.find("meta", property=prop)
            if tag and tag.get("content"):
                date = _parse_iso_datetime(tag["content"])
                if date:
                    return date

        # 2. JSON-LD NewsArticle metadata (used by Indian Startup News)
        for script in soup.find_all("script", type="application/ld+json"):
            text = script.string or script.get_text()
            if not text:
                continue
            try:
                data = json.loads(text.strip())
            except ValueError:
                continue
            date = _find_jsonld_date(data)
            if date:
                return date

        # 3. Try <time datetime="..."> — most reliable when present
        for time_tag in soup.find_all("time"):
            dt_attr = time_tag.get("datetime", "")
            if dt_attr:
                date = _parse_iso_datetime(dt_attr)
                if date:
                    return date
            date = _parse_et_article_date(time_tag.get_text())
            if date:
                return date

        # 4. Look inside elements whose class/itemprop hints at a date
        for attrs in (
            {"itemprop": "datePublished"},
            {"itemprop": "dateModified"},
            {"class": re.compile(r'publish|date|time|updated', re.I)},
        ):
            for tag in soup.find_all(True, **attrs):
                date = _parse_et_article_date(tag.get_text())
                if date:
                    return date

        # 5. Full-page text scan as last resort
        return _parse_et_article_date(soup.get_text(" "))

    def _bs_left(self, items: list[tuple[str, Optional[datetime]]], end_date: datetime) -> int:
        """First index in descending-date list where date <= end_date."""
        lo, hi, left = 0, len(items) - 1, len(items)
        while lo <= hi:
            mid = (lo + hi) // 2
            if items[mid][1] <= end_date:
                left = mid
                hi = mid - 1
            else:
                lo = mid + 1
        return left

    def _bs_right(self, items: list[tuple[str, Optional[datetime]]], start_date: datetime) -> int:
        """Last index in descending-date list where date >= start_date."""
        lo, hi, right = 0, len(items) - 1, -1
        while lo <= hi:
            mid = (lo + hi) // 2
            if items[mid][1] >= start_date:
                right = mid
                lo = mid + 1
            else:
                hi = mid - 1
        return right

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_article_links(
        self,
        source_url: str,
        domain: str,
        link_contains: str,
        max_articles: int = 20,
    ) -> list[str]:
        """Single-page link collection."""
        html = self._fetch_html(source_url)
        if not html:
            return []

        soup = BeautifulSoup(html, "lxml")
        links: set[str] = set()

        for tag in soup.find_all("a", href=True):
            href = tag["href"].strip()
            full_url = urljoin(source_url, href)
            parsed = urlparse(full_url)

            if domain not in parsed.netloc:
                continue
            if link_contains not in parsed.path:
                continue
            if parsed.path in ("", "/", link_contains) or parsed.fragment:
                continue

            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            links.add(clean_url)
            if len(links) >= max_articles:
                break

        return list(links)

    def get_article_links_in_date_range(
        self,
        source_url: str,
        domain: str,
        link_contains: str,
        start_date: datetime,
        end_date: datetime,
        max_pages: int = 10,
    ) -> list[str]:
        """
        Paginate through listing pages and collect article URLs whose listing-page
        date falls within [start_date, end_date].

        Uses binary search within each page to find the in-range window without
        iterating every card. Stops pagination once all remaining pages are too old.
        """
        collected: list[str] = []
        current_url = source_url

        for page_num in range(1, max_pages + 1):
            logger.info(f"  [Page {page_num}] Fetching: {current_url}")
            html = self._fetch_html(current_url)
            if not html:
                logger.warning(f"  [Page {page_num}] Failed to fetch, stopping")
                break

            items = self._listing_links_with_dates(html, source_url, domain, link_contains)
            if not items:
                logger.info(f"  [Page {page_num}] No article cards found, stopping")
                break

            first_date = items[0][1]
            last_date = items[-1][1]
            logger.info(
                f"  [Page {page_num}] Date span: {last_date.strftime('%Y-%m-%d')} "
                f"→ {first_date.strftime('%Y-%m-%d')}"
            )

            # Entire page too old — no subsequent page can be in range
            if first_date < start_date:
                logger.info(f"  [Page {page_num}] Entire page too old — stopping pagination")
                break

            # Entire page too new — range might start on a later page
            if last_date > end_date:
                logger.info(f"  [Page {page_num}] Entire page too new — skipping to next page")
                next_url = self._get_next_page_url(html, current_url)
                if not next_url or next_url == current_url:
                    logger.info(f"  [Page {page_num}] No next page — stopping")
                    break
                current_url = next_url
                time.sleep(self.delay)
                continue

            left = self._bs_left(items, end_date)
            right = self._bs_right(items, start_date)
            logger.info(f"  [Page {page_num}] Binary search bounds: [{left}, {right}] of {len(items)} cards")

            # Page spans our range but no card lands exactly in it — move to next page
            if left > right:
                logger.info(f"  [Page {page_num}] No cards in range on this page — continuing")
                next_url = self._get_next_page_url(html, current_url)
                if not next_url or next_url == current_url:
                    break
                current_url = next_url
                time.sleep(self.delay)
                continue

            new_count = 0
            for url, date in items[left:right + 1]:
                if url not in collected:
                    collected.append(url)
                    new_count += 1
                    logger.info(f"    QUEUE ({date.strftime('%Y-%m-%d')}): ...{url[-60:]}")

            logger.info(
                f"  [Page {page_num}] Queued {new_count} new articles | "
                f"total collected so far: {len(collected)}"
            )

            # Right boundary is mid-page — all subsequent pages are older than start_date
            if right < len(items) - 1:
                logger.info(f"  [Page {page_num}] Right boundary mid-page — stopping pagination")
                break

            next_url = self._get_next_page_url(html, current_url)
            if not next_url or next_url == current_url:
                logger.info(f"  [Page {page_num}] No next page — stopping")
                break
            logger.info(f"  [Page {page_num}] Range may continue on next page → {next_url}")
            current_url = next_url
            time.sleep(self.delay)

        return collected

    def extract_article(
        self, url: str
    ) -> tuple[Optional[str], Optional[str], Optional[datetime]]:
        """Fetch and return (title, content, published_date) for an article URL."""
        time.sleep(self.delay)
        html = self._fetch_html(url)
        if not html:
            return None, None, None

        content = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
        )

        soup = BeautifulSoup(html, "lxml")
        title_tag = soup.find("h1") or soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else None

        published_date = self._extract_date_from_html(html)

        if published_date:
            logger.info(f"  Extracted date: {published_date.strftime('%Y-%m-%d %I:%M %p IST')} | {url[-70:]}")
        else:
            logger.warning(f"  Could not extract date from article: {url[-70:]}")

        return title, content, published_date


class ETScraper(WebScraper):
    """WebScraper implementation for Economic Times listing pages."""

    def _listing_links_with_dates(
        self,
        html: str,
        source_url: str,
        domain: str,
        link_contains: str,
    ) -> list[tuple[str, Optional[datetime]]]:
        """
        Parse ET listing page cards (<div class="eachStory">) and return
        (url, date) pairs. Date comes from <time class="date-format" data-time="...">.
        """
        soup = BeautifulSoup(html, "lxml")
        seen: set[str] = set()
        results: list[tuple[str, Optional[datetime]]] = []

        for story in soup.find_all("div", class_="eachStory"):
            url: Optional[str] = None
            for a in story.find_all("a", href=True):
                href = a["href"].strip()
                full_url = urljoin(source_url, href)
                parsed = urlparse(full_url)
                if (
                    domain in parsed.netloc
                    and link_contains in parsed.path
                    and parsed.path not in ("", "/", link_contains)
                    and not parsed.fragment
                ):
                    url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                    break

            if not url or url in seen:
                continue
            seen.add(url)

            date: Optional[datetime] = None
            time_tag = story.find("time", class_="date-format")
            if time_tag and time_tag.get("data-time"):
                date = _parse_et_listing_date(time_tag["data-time"])

            results.append((url, date))

        return results

    def _get_next_page_url(self, html: str, current_url: str) -> Optional[str]:
        """
        ET pagination pattern: .../articlelist/msid-NNN,page-N.cms
        Increments the page number, or finds the page-2 link on the first page.
        """
        page_match = re.search(r'(articlelist/msid-(\d+),page-)(\d+)(\.cms)', current_url)
        if page_match:
            next_page = int(page_match.group(3)) + 1
            return re.sub(
                r'(articlelist/msid-\d+,page-)\d+(\.cms)',
                rf'\g<1>{next_page}\g<2>',
                current_url,
            )

        m = re.search(r'href="(https?://[^"]+articlelist/msid-(\d+),page-2\.cms)"', html)
        if m:
            return m.group(1)

        return None


class IndiaInfolineScraper(WebScraper):
    """WebScraper implementation for India Infoline topic listing pages."""

    def _listing_links_with_dates(
        self,
        html: str,
        source_url: str,
        domain: str,
        link_contains: str,
    ) -> list[tuple[str, Optional[datetime]]]:
        """
        Parse IIFL listing cards (div.Snwhy8) and return (url, date) pairs.
        Date comes from div.xnG0xq: two spans holding "23 Oct 2024" and "10:11 AM".
        """
        soup = BeautifulSoup(html, "lxml")
        seen: set[str] = set()
        results: list[tuple[str, Optional[datetime]]] = []

        for card in soup.find_all("div", class_="Snwhy8"):
            url: Optional[str] = None
            for a in card.find_all("a", href=True):
                href = a["href"].strip()
                full_url = urljoin(source_url, href)
                parsed = urlparse(full_url)
                if (
                    domain in parsed.netloc
                    and link_contains in parsed.path
                    and parsed.path not in ("", "/", link_contains)
                    and not parsed.fragment
                ):
                    url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                    break

            if not url or url in seen:
                continue
            seen.add(url)

            date: Optional[datetime] = None
            date_div = card.find("div", class_="xnG0xq")
            if date_div:
                date = _parse_iifl_listing_date(date_div.get_text(" "))

            results.append((url, date))

        return results

    def _get_next_page_url(self, html: str, current_url: str) -> Optional[str]:
        """IIFL pagination pattern: ?page=N"""
        page_match = re.search(r'([?&]page=)(\d+)', current_url)
        if page_match:
            next_page = int(page_match.group(2)) + 1
            return re.sub(r'([?&]page=)\d+', rf'\g<1>{next_page}', current_url)

        separator = "&" if "?" in current_url else "?"
        return f"{current_url}{separator}page=2"


class LivemintScraper(WebScraper):
    """
    WebScraper for Livemint using the internal CMS JSON API.

    Source URL must be the API listing endpoint:
      https://www.livemint.com/api/cms/page/v2/listing?url=/companies&page=1

    The API returns 20 articles per page with clean ISO 8601 dates, enabling
    full date-range pagination without needing a headless browser.
    """

    _LM_API_PAGE_RE = re.compile(r'([&?]page=)(\d+)', re.IGNORECASE)

    def _parse_api_response(
        self,
        text: str,
        domain: str,
        link_contains: str,
    ) -> list[tuple[str, Optional[datetime]]]:
        """Parse the CMS JSON response and return (url, date) pairs."""
        try:
            data = __import__("json").loads(text)
        except Exception:
            return []

        results: list[tuple[str, Optional[datetime]]] = []
        seen: set[str] = set()

        for article in data.get("content", []):
            rel_url = article.get("url", "")
            if not rel_url or link_contains not in rel_url:
                continue
            full_url = f"https://{domain}{rel_url}"
            if full_url in seen:
                continue
            seen.add(full_url)

            date: Optional[datetime] = None
            raw_date = article.get("firstPublishedDate") or article.get("lastPublishedDate")
            if raw_date:
                try:
                    date = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                except ValueError:
                    pass

            results.append((full_url, date))

        return results

    def _listing_links_with_dates(
        self,
        html: str,
        source_url: str,
        domain: str,
        link_contains: str,
    ) -> list[tuple[str, Optional[datetime]]]:
        return self._parse_api_response(html, domain, link_contains)

    def _get_next_page_url(self, html: str, current_url: str) -> Optional[str]:
        """Increment the page=N parameter in the API URL.
        Livemint's listing only exposes ~10 pages of content; page 11+
        loops back to the same recent articles, so we stop there.
        """
        m = self._LM_API_PAGE_RE.search(current_url)
        if m:
            next_page = int(m.group(2)) + 1
            if next_page > 10:
                return None
            return self._LM_API_PAGE_RE.sub(rf"\g<1>{next_page}", current_url)
        return None

    def get_article_links(
        self,
        source_url: str,
        domain: str,
        link_contains: str,
        max_articles: int = 20,
    ) -> list[str]:
        """Fetch first page from the JSON API and return article URLs."""
        text = self._fetch_html(source_url)
        if not text:
            return []
        items = self._parse_api_response(text, domain, link_contains)
        return [url for url, _ in items[:max_articles]]


class WSJScraper(WebScraper):
    """
    WebScraper for WSJ section listing pages (e.g. /business/deals).

    Article data (URL + timestamp) is embedded in __NEXT_DATA__ JSON on each
    listing page under pageProps.moreInArticles. Pagination uses ?page=N.
    Article pages expose article:published_time for date extraction.
    """

    _WSJ_PAGE_RE = re.compile(r'([?&]page=)(\d+)', re.IGNORECASE)

    def _parse_listing_html(
        self,
        html: str,
        domain: str,
        link_contains: str,
    ) -> list[tuple[str, Optional[datetime]]]:
        """Extract (url, date) pairs from __NEXT_DATA__ moreInArticles list."""
        import json as _json
        m = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S
        )
        if not m:
            return []
        try:
            data = _json.loads(m.group(1))
            articles = data["props"]["pageProps"]["moreInArticles"]
        except (KeyError, ValueError):
            return []

        seen: set[str] = set()
        results: list[tuple[str, Optional[datetime]]] = []

        for article in articles:
            url = article.get("articleUrl", "")
            if not url or link_contains not in url or url in seen:
                continue
            # Strip tracking query params
            parsed = urlparse(url)
            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if clean_url in seen:
                continue
            seen.add(clean_url)

            date: Optional[datetime] = None
            ts = article.get("timestamp")
            if ts:
                try:
                    date = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except ValueError:
                    pass

            results.append((clean_url, date))

        return results

    def _listing_links_with_dates(
        self,
        html: str,
        source_url: str,
        domain: str,
        link_contains: str,
    ) -> list[tuple[str, Optional[datetime]]]:
        return self._parse_listing_html(html, domain, link_contains)

    def _get_next_page_url(self, html: str, current_url: str) -> Optional[str]:
        """Increment ?page=N in the WSJ listing URL."""
        m = self._WSJ_PAGE_RE.search(current_url)
        if m:
            next_page = int(m.group(2)) + 1
            return self._WSJ_PAGE_RE.sub(rf"\g<1>{next_page}", current_url)
        # First page may have no page param — append ?page=2
        sep = "&" if "?" in current_url else "?"
        return f"{current_url}{sep}page=2"


class IndianStartupNewsScraper(WebScraper):
    """
    WebScraper for Indian Startup News Funding Fusion listing pages.

    Article cards: div.feat-a-1 and div.small-post with /funding/<slug> links.
    Date:          span.publish-date, e.g. "Jun 23, 2026 15:47 IST".
    Pages:         /funding?page=N.
    Article dates: JSON-LD NewsArticle datePublished/dateModified.
    """

    _ISN_PAGE_RE = re.compile(r'([?&]page=)(\d+)', re.IGNORECASE)

    def _listing_links_with_dates(
        self,
        html: str,
        source_url: str,
        domain: str,
        link_contains: str,
    ) -> list[tuple[str, Optional[datetime]]]:
        soup = BeautifulSoup(html, "lxml")
        seen: set[str] = set()
        results: list[tuple[str, Optional[datetime]]] = []

        for card in soup.select("div.feat-a-1, div.small-post"):
            url: Optional[str] = None
            for a in card.find_all("a", href=True):
                href = a["href"].strip()
                full_url = urljoin(source_url, href)
                parsed = urlparse(full_url)
                if (
                    domain in parsed.netloc
                    and link_contains in parsed.path
                    and parsed.path not in ("", "/", link_contains.rstrip("/"))
                    and not parsed.fragment
                ):
                    clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                    if clean_url not in seen:
                        url = clean_url
                        seen.add(clean_url)
                    break

            if not url:
                continue

            date: Optional[datetime] = None
            date_span = card.find("span", class_="publish-date")
            if date_span:
                date = _parse_isn_listing_date(date_span.get_text(" ", strip=True))

            if date is None:
                continue  # skip undated cards — binary search requires all dates present
            results.append((url, date))

        return results

    def _get_next_page_url(self, html: str, current_url: str) -> Optional[str]:
        """Increment ?page=N for Indian Startup News category pages."""
        m = self._ISN_PAGE_RE.search(current_url)
        if m:
            next_page = int(m.group(2)) + 1
            return self._ISN_PAGE_RE.sub(rf"\g<1>{next_page}", current_url)

        soup = BeautifulSoup(html, "lxml")
        for a in soup.find_all("a", class_="paginate", href=True):
            label = a.get("aria-label", "").lower()
            if "page 2" in label or a.get_text(strip=True) == "2":
                return urljoin(current_url, a["href"].strip())

        sep = "&" if "?" in current_url else "?"
        return f"{current_url}{sep}page=2"

    def get_article_links(
        self,
        source_url: str,
        domain: str,
        link_contains: str,
        max_articles: int = 20,
    ) -> list[str]:
        """Fetch first page and return dated Funding Fusion article URLs."""
        html = self._fetch_html(source_url)
        if not html:
            return []
        items = self._listing_links_with_dates(html, source_url, domain, link_contains)
        return [url for url, _ in items[:max_articles]]


class Inc42Scraper(WebScraper):
    """
    WebScraper for Inc42 homepage article cards.

    Article cards: div.card-wrapper and li[data-card-id].
    Date:          span.date, e.g. "23rd June, 2026" or "23 Jun'26".
    Pages:         homepage load-more is Ajax-backed, so this scraper is first-page only.
    Article dates: article:published_time OG meta tag.
    """

    _ARTICLE_PREFIXES = ("/buzz/", "/features/", "/startups/", "/resources/")

    def _is_article_url(self, url: str, domain: str) -> bool:
        parsed = urlparse(url)
        if domain not in parsed.netloc or parsed.fragment:
            return False
        return any(parsed.path.startswith(prefix) and parsed.path != prefix for prefix in self._ARTICLE_PREFIXES)

    def _listing_links_with_dates(
        self,
        html: str,
        source_url: str,
        domain: str,
        link_contains: str,
    ) -> list[tuple[str, Optional[datetime]]]:
        soup = BeautifulSoup(html, "lxml")
        seen: set[str] = set()
        results: list[tuple[str, Optional[datetime]]] = []

        for card in soup.select("div.card-wrapper, li[data-card-id]"):
            url: Optional[str] = None
            for a in card.find_all("a", href=True):
                full_url = urljoin(source_url, a["href"].strip())
                if not self._is_article_url(full_url, domain):
                    continue
                parsed = urlparse(full_url)
                clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                if clean_url not in seen:
                    url = clean_url
                    seen.add(clean_url)
                break

            if not url:
                continue

            date: Optional[datetime] = None
            date_span = card.find("span", class_="date")
            if date_span:
                date = _parse_inc42_listing_date(date_span.get_text(" ", strip=True))

            if date is None:
                continue  # skip undated cards — binary search requires all dates present
            results.append((url, date))

        return results

    def _get_next_page_url(self, html: str, current_url: str) -> Optional[str]:
        return None

    def get_article_links(
        self,
        source_url: str,
        domain: str,
        link_contains: str,
        max_articles: int = 20,
    ) -> list[str]:
        """Fetch the homepage and return dated Inc42 article URLs."""
        html = self._fetch_html(source_url)
        if not html:
            return []
        items = self._listing_links_with_dates(html, source_url, domain, link_contains)
        return [url for url, _ in items[:max_articles]]


class CNBCScraper(WebScraper):
    """
    WebScraper for CNBC section listing pages (e.g. /deals-and-ipos/).

    Article cards: <div class="Card-card ..."> with <a href="/YYYY/MM/DD/slug.html">
    Date:          <span class="Card-time">Fri, May 8th 2026</span> (ordinal suffix stripped)
    Pages:         ?page=N (1-indexed)
    Article dates: article:published_time OG meta tag (UTC ISO 8601)
    """

    _CNBC_PAGE_RE = re.compile(r'([?&]page=)(\d+)', re.IGNORECASE)
    _CNBC_ART_RE = re.compile(r'^/\d{4}/\d{2}/\d{2}/')
    _CNBC_ORD_RE = re.compile(r'(\d+)(st|nd|rd|th)\b', re.IGNORECASE)

    def _parse_cnbc_listing_date(self, text: str) -> Optional[datetime]:
        """Parse 'Fri, May 8th 2026' from Card-time span into midnight IST."""
        text = self._CNBC_ORD_RE.sub(r'\1', text).strip()
        try:
            return datetime.strptime(text, '%a, %b %d %Y').replace(tzinfo=IST)
        except ValueError:
            return None

    def _listing_links_with_dates(
        self,
        html: str,
        source_url: str,
        domain: str,
        link_contains: str,
    ) -> list[tuple[str, Optional[datetime]]]:
        soup = BeautifulSoup(html, "lxml")
        seen: set[str] = set()
        results: list[tuple[str, Optional[datetime]]] = []

        for card in soup.find_all("div", class_=lambda c: c and "Card-card" in c):
            url: Optional[str] = None
            for a in card.find_all("a", href=True):
                href = a["href"].strip()
                parsed = urlparse(href)
                if domain not in parsed.netloc:
                    continue
                if "/video/" in parsed.path:
                    continue
                if not self._CNBC_ART_RE.match(parsed.path):
                    continue
                clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                if clean_url not in seen:
                    url = clean_url
                    seen.add(clean_url)
                    break

            if not url:
                continue

            date: Optional[datetime] = None
            time_span = card.find("span", class_="Card-time")
            if time_span:
                date = self._parse_cnbc_listing_date(time_span.get_text(strip=True))

            if date is None:
                continue  # skip undated cards — binary search requires all dates present

            results.append((url, date))

        return results

    def _get_next_page_url(self, html: str, current_url: str) -> Optional[str]:
        """Increment ?page=N in the CNBC listing URL."""
        m = self._CNBC_PAGE_RE.search(current_url)
        if m:
            next_page = int(m.group(2)) + 1
            return self._CNBC_PAGE_RE.sub(rf"\g<1>{next_page}", current_url)
        sep = "&" if "?" in current_url else "?"
        return f"{current_url}{sep}page=2"

    def get_article_links(
        self,
        source_url: str,
        domain: str,
        link_contains: str,
        max_articles: int = 20,
    ) -> list[str]:
        """Fetch first page and return non-video article URLs."""
        html = self._fetch_html(source_url)
        if not html:
            return []
        items = self._listing_links_with_dates(html, source_url, domain, link_contains)
        return [url for url, _ in items[:max_articles]]


class FEScraper(WebScraper):
    """
    WebScraper for Financial Express listing pages (e.g. /market/).

    WordPress site — article cards are <article> tags.
    Link:  <h2 class="entry-title"><a href="...">
    Date:  <time class="entry-date published" datetime="ISO8601">
    Pages: /market/page/2/, /market/page/3/, ...
    """

    _FE_PAGE_RE = re.compile(r'/page/(\d+)/$')

    def _listing_links_with_dates(
        self,
        html: str,
        source_url: str,
        domain: str,
        link_contains: str,
    ) -> list[tuple[str, Optional[datetime]]]:
        soup = BeautifulSoup(html, "lxml")
        seen: set[str] = set()
        results: list[tuple[str, Optional[datetime]]] = []

        for article in soup.find_all("article"):
            # Link from entry-title h2 > a
            h2 = article.find("h2", class_="entry-title")
            if not h2:
                continue
            a = h2.find("a", href=True)
            if not a:
                continue
            href = a["href"].strip()
            parsed = urlparse(href)
            if domain not in parsed.netloc or link_contains not in parsed.path:
                continue
            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if clean_url in seen:
                continue
            seen.add(clean_url)

            # Date from <time class="entry-date published" datetime="...">
            date: Optional[datetime] = None
            time_tag = article.find("time", class_="entry-date")
            if time_tag and time_tag.get("datetime"):
                try:
                    date = datetime.fromisoformat(time_tag["datetime"])
                except ValueError:
                    pass

            if date is None:
                continue  # skip undated cards — binary search requires all dates present
            results.append((clean_url, date))

        return results

    def _get_next_page_url(self, html: str, current_url: str) -> Optional[str]:
        """
        /market/       → /market/page/2/
        /market/page/N/ → /market/page/N+1/
        """
        m = self._FE_PAGE_RE.search(current_url)
        if m:
            next_page = int(m.group(1)) + 1
            return self._FE_PAGE_RE.sub(f"/page/{next_page}/", current_url)
        # First page — no /page/N/ in URL yet
        base = current_url.rstrip("/")
        return f"{base}/page/2/"
