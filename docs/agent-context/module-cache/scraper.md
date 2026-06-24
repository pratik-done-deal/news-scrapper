# Scraper Module Cache

Last refreshed: 2026-06-23

- Owner: `src/scraper/web_scraper.py`.
- Runtime doc: `agents/scraper-agent.md`.
- Product playbook: `skills/add-scraper.md`.
- Source anchors: `WebScraper`; source-specific scraper class; shared date parsing; pagination helpers; `SCRAPER_REGISTRY` in `src/agent.py`.
- Config coupling: add scraper class in `web_scraper.py`, registry key in `src/agent.py`, source entry in `config/sources.yaml`.
- Contract: `extract_article(url)` returns `(title, content, published_date)` and must return `(None, None, None)` on failure.
- Verification: offline date parser tests when possible; live `python test_date_range.py ...` only when checking real site behavior.
