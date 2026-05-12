import logging
import time
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

    def get_article_links(
        self,
        source_url: str,
        domain: str,
        link_contains: str,
        max_articles: int = 20,
    ) -> list[str]:
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
            # skip pagination, category root, and anchor-only links
            if parsed.path in ("", "/", link_contains) or parsed.fragment:
                continue

            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            links.add(clean_url)

            if len(links) >= max_articles:
                break

        return list(links)

    def extract_article(self, url: str) -> tuple[Optional[str], Optional[str]]:
        """Fetch and extract (title, content) from an article URL."""
        time.sleep(self.delay)
        html = self._fetch_html(url)
        if not html:
            return None, None

        content = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
        )

        soup = BeautifulSoup(html, "lxml")
        title_tag = soup.find("h1") or soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else None

        return title, content
