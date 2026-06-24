# Skill: Add a New News Source Scraper

## When to Use
When you need to ingest articles from a news website not currently supported.

## Steps

1. **Inspect the target site**
   - Find the listing page URL that shows recent articles.
   - Identify the HTML pattern for article `<a>` tags (use browser DevTools).
   - Find where the article date is rendered (listing page and/or article page).

2. **Create the scraper class** in `src/scraper/web_scraper.py`:
   ```python
   class MyScraper(WebScraper):
       def get_article_links(self, source_url, domain, link_contains, max_articles):
           ...  # BeautifulSoup link extraction
       
       def extract_article(self, url):
           ...  # trafilatura content + date parsing
           # Always return (None, None, None) on any failure
   ```

3. **Write a date parser** (if needed):
   ```python
   _MY_DATE_RE = re.compile(r'...', re.IGNORECASE)
   
   def _parse_my_date(text: str) -> Optional[datetime]:
       m = _MY_DATE_RE.search(text)
       if not m:
           return None
       try:
           return datetime.strptime(...).replace(tzinfo=IST)
       except ValueError:
           return None
   ```

4. **Register the scraper** in `src/agent.py`:
   ```python
   SCRAPER_REGISTRY: dict[str, type[WebScraper]] = {
       ...
       "mykey": MyScraper,
   }
   ```

5. **Add the source** to `config/sources.yaml`:
   ```yaml
   - name: My Source
     url: https://example.com/markets/ma
     domain: https://example.com
     link_contains: /markets/
     scraper: mykey
     paginate: false          # set true if date-range pagination is supported
   ```

6. **Test** — run `python main.py` and verify articles are scraped and dates are parsed correctly in `news_agent.log`.

## Key Files
- `src/scraper/web_scraper.py` — add scraper class here
- `src/agent.py` — register in `SCRAPER_REGISTRY`
- `config/sources.yaml` — add source entry
