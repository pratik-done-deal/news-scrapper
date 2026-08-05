# Scraper Module Cache

Last refreshed: 2026-08-05

- Owner: `src/scraper/web_scraper.py`.
- Runtime doc: `agents/scraper-agent.md`.
- Product playbook: `skills/add-scraper.md`.
- Source anchors: `WebScraper`; source-specific scraper class; shared date parsing; pagination helpers; `SCRAPER_REGISTRY` in `src/agent.py`.
- Config coupling: add scraper class in `web_scraper.py`, registry key in `src/agent.py`, source entry in `config/sources.yaml`.
- Contract: `extract_article(url)` returns `(title, content, published_date)` and must return `(None, None, None)` on failure.
- Two independent collection paths, dispatched by `_scrape_links` in `src/agent.py`: listing (`get_article_links` / `get_article_links_in_date_range`) and company search (`get_company_article_links`). Changing one never affects the other.
- `search_url` is not always a `{query}` GET template. Entrackr and Indian Startup News use the template plus `QuintypeSearchMixin`; Inc42's is a POST JSON API (`search.thed2csummit.co/query`, form field `query`) returning permalinks and ISO dates, so `Inc42Scraper.get_company_article_links` bypasses the HTML parsers and `_build_search_url` entirely. Check the source entry's comment before assuming the template.
- Inc42's `?s=` HTML search is client-side only — the server HTML serves a generic article rail identical for every query, so it parses "successfully" while returning junk. Do not use it.
- Verification: offline date parser tests when possible; live `python test_date_range.py ...` only when checking real site behavior.
