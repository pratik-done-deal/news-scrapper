# Scraper Agent

## Role
Fetches article links and full article text from Indian financial news websites. Runs in the main (P1 producer) process. Never writes to the database.

## Context
- Lives in `src/scraper/web_scraper.py`.
- All scrapers inherit the abstract `WebScraper` base class.
- Uses `trafilatura` for article content extraction and `BeautifulSoup` for link parsing.
- Shares a `HEADERS` dict (Chrome UA) for all HTTP requests.
- Rate limiting is enforced by the caller — scrapers do not sleep internally.
- All returned datetimes are timezone-aware IST (`UTC+5:30`).

## Registered Scrapers

| Class | Config Key | Date-Range Pagination |
|-------|-----------|----------------------|
| `ETScraper` | `et` | Yes |
| `FEScraper` | `fe` | No |
| `CNBCScraper` | `cnbc` | No |
| `IndiaInfolineScraper` | `iifl` | No |

## Skills

### `get_article_links(source_url, domain, link_contains, max_articles) → list[str]`
Returns absolute article URLs from a news source listing page. Filters by `link_contains` substring.

### `extract_article(url) → (title, content, published_date)`
Fetches a single article. Returns `(None, None, None)` on any failure — callers must handle this.

### `get_article_links_in_date_range(source_url, domain, link_contains, start_date, end_date, max_pages) → list[str]`
Paginates through listing pages and collects all links within the IST date range. Only available on scrapers that support pagination.

## How to Add a New Scraper
1. Subclass `WebScraper` in `web_scraper.py`.
2. Implement `get_article_links()` using BeautifulSoup to find article `<a>` tags.
3. Implement `extract_article()` using trafilatura for content; add a site-specific date regex helper if needed.
4. Wrap all network/parsing code in `try/except`; return `(None, None, None)` on failure.
5. Register: `SCRAPER_REGISTRY["mykey"] = MyScraperClass` in `src/agent.py`.
6. Add source entry in `config/sources.yaml` with `scraper: mykey`.

## Date Parsing Helpers (existing)
- `_ET_ARTICLE_DATE_RE` — matches `"Last Updated: Feb 28, 2025, 04:40:00 PM IST"` in ET article body
- `_ET_LISTING_DATE_RE` — matches `"May 12, 2026, 12:19 PM IST"` from ET listing data attributes
- `_IIFL_LISTING_DATE_RE` — matches `"23 Oct 2024 | 10:11 AM"` from IIFL listing HTML
