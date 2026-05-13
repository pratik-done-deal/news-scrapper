import logging
import re
import time
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


class WebScraper:
    def __init__(self, request_timeout: int = 30, delay: float = 2.0):
        self.timeout = request_timeout
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def _fetch_html(self, url: str) -> Optional[str]:
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch {url}: {e}")
            return None

    def _extract_date_from_html(self, html: str) -> Optional[datetime]:
        """Extract publication date from an ET article page."""
        soup = BeautifulSoup(html, "lxml")

        # 1. Try <time datetime="..."> — most reliable when present
        for time_tag in soup.find_all("time"):
            dt_attr = time_tag.get("datetime", "")
            if dt_attr:
                try:
                    return datetime.fromisoformat(dt_attr.replace("Z", "+00:00"))
                except ValueError:
                    pass
            date = _parse_et_article_date(time_tag.get_text())
            if date:
                return date

        # 2. Look inside elements whose class/itemprop hints at a date
        for attrs in (
            {"itemprop": "datePublished"},
            {"itemprop": "dateModified"},
            {"class": re.compile(r'publish|date|time|updated', re.I)},
        ):
            for tag in soup.find_all(True, **attrs):
                date = _parse_et_article_date(tag.get_text())
                if date:
                    return date

        # 3. Full-page text scan as last resort
        return _parse_et_article_date(soup.get_text(" "))

    def _get_next_page_url(self, html: str, current_url: str) -> Optional[str]:
        """Find the next listing-page URL using ET's articlelist pagination pattern."""
        # If we're already on a paginated URL (.../articlelist/msid-NNN,page-N.cms), increment N
        page_match = re.search(r'(articlelist/msid-(\d+),page-)(\d+)(\.cms)', current_url)
        if page_match:
            next_page = int(page_match.group(3)) + 1
            return re.sub(
                r'(articlelist/msid-\d+,page-)\d+(\.cms)',
                rf'\g<1>{next_page}\g<2>',
                current_url,
            )

        # First page — find the embedded page-2 href in the HTML (ET puts it in a script-wrapped <a>)
        m = re.search(r'href="(https?://[^"]+articlelist/msid-(\d+),page-2\.cms)"', html)
        if m:
            return m.group(1)

        return None

    def _listing_links_with_dates(
        self,
        html: str,
        source_url: str,
        domain: str,
        link_contains: str,
    ) -> list[tuple[str, Optional[datetime]]]:
        """
        Return (url, date) pairs from an ET listing page.
        Uses <div class="eachStory"> containers which each hold exactly one
        article link and one <time class="date-format" data-time="..."> tag.
        """
        soup = BeautifulSoup(html, "lxml")
        seen: set[str] = set()
        results: list[tuple[str, Optional[datetime]]] = []

        for story in soup.find_all("div", class_="eachStory"):
            # Article URL — first matching <a href> inside this story card
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

            # Date — ET puts it in <time class="date-format" data-time="May 12, 2026, 12:19 PM IST">
            date: Optional[datetime] = None
            time_tag = story.find("time", class_="date-format")
            if time_tag and time_tag.get("data-time"):
                date = _parse_et_listing_date(time_tag["data-time"])

            results.append((url, date))

        return results

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
        """Single-page link collection (original behaviour)."""
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

        Stops pagination early once every article on a page is older than start_date.
        For links where no listing date is found, they are included and their date
        is verified later when the article is fetched.
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

            dated_count = sum(1 for _, d in items if d is not None)
            too_old_count = sum(1 for _, d in items if d is not None and d < start_date)
            too_new_count = sum(1 for _, d in items if d is not None and d > end_date)
            in_range_count = 0

            # Log the date span of this page so you can see where in time we are
            dates_on_page = [d for _, d in items if d is not None]
            if dates_on_page:
                logger.info(
                    f"  [Page {page_num}] Date span: {min(dates_on_page).strftime('%Y-%m-%d')} "
                    f"→ {max(dates_on_page).strftime('%Y-%m-%d')} | "
                    f"too_new={too_new_count} in_range=? too_old={too_old_count}"
                )

            for url, listing_date in items:
                if listing_date is not None:
                    if listing_date > end_date:
                        logger.info(f"    SKIP (too new  {listing_date.strftime('%Y-%m-%d')}): ...{url[-60:]}")
                        continue
                    if listing_date < start_date:
                        logger.info(f"    SKIP (too old  {listing_date.strftime('%Y-%m-%d')}): ...{url[-60:]}")
                        continue
                    logger.info(f"    QUEUE ({listing_date.strftime('%Y-%m-%d')}): ...{url[-60:]}")
                else:
                    logger.info(f"    QUEUE (no listing date): ...{url[-60:]}")

                if url not in collected:
                    collected.append(url)
                    if listing_date is not None:
                        in_range_count += 1

            logger.info(
                f"  [Page {page_num}] Queued {in_range_count} new articles | "
                f"total collected so far: {len(collected)}"
            )

            # Stop once all dated articles on a page are older than start_date
            if dated_count > 0 and too_old_count == dated_count:
                logger.info("  All articles on this page are older than start_date — stopping pagination")
                break

            next_url = self._get_next_page_url(html, current_url)
            if not next_url or next_url == current_url:
                logger.info(f"  [Page {page_num}] No next page found — stopping pagination")
                break
            logger.info(f"  [Page {page_num}] Next page → {next_url}")
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
