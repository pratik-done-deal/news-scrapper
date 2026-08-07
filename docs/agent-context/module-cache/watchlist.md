# Watchlist Module Cache

Last refreshed: 2026-08-04

Phase 1 of restricting news runs to the companies tracked in the company MySQL DB.

- Owners: `src/processor/watchlist.py`, `NewsAgent.scrape_watchlist()` in `src/agent.py`, the two watchlist routes in `src/api/routes/company_scrape.py`.
- Upstream data: `src/db/mysql_queries.py::fetch_watchlist()`; see `module-cache/company-mysql.md`.
- Source anchors: `derive_search_term()`; `build_entries()`; `build_gate_terms()`; `WatchlistMatcher`; `gate_articles()`; `NewsAgent._run_scrape_jobs()`.

## Two paths, two entity sets

| Path | Sources | Entities |
|------|---------|----------|
| On-site search | those with `search_url` in `config/sources.yaml` (currently Entrackr, Indian Startup News) | the incremental slice — `created_at >= since` |
| Listing scrape + entity gate | every other source | the full tracked universe |

The gate is deliberately wider than the search: a listing scrape already paid for the article, so news about any tracked company should survive.

## Search terms vs gate terms

- `build_entries()` yields **one** term per company — `brand_name` if present, else `strip_legal_suffix(company_name)`. One search per company; searching "Bundl Technologies Private Limited" on Entrackr finds nothing, "Swiggy" finds everything.
- `build_gate_terms()` yields **both** the brand and the stripped registered name, because an article can say "Bundl Technologies" without ever saying "Swiggy". Never use search terms to build the gate.
- Both dedupe case-insensitively, drop terms below `min_term_length`, and drop `_STOP_TERMS` (generic words like "india", "group") that would match half the wire.
- Name normalisation lives in `src/db/names.py`: `strip_legal_suffix()` preserves casing (for search), `normalize_company_name()` adds `.title()` and **must stay byte-identical** — `repository.py::_company_id()` keys a UUID5 on it.

## Matching

`WatchlistMatcher` indexes terms by first token and only tests candidates whose first token appears in the article, because `NewsFilter`'s scan-every-pattern approach does not scale past a few hundred terms. Word-boundary anchored and case-insensitive: "Ola" does not match "Olive", "Zepto" does not match "Zeptolab". Multi-word terms tolerate punctuation between tokens ("Peak-XV" matches "Peak XV").

## Fan-out

`_run_scrape_jobs()` takes `(source, company_or_None)` pairs and runs them in **one** process pool; `_scrape_all_sources()` is now a thin wrapper over it. Articles come back tagged with `searched_company`, which is how `scrape_watchlist()` tells a targeted hit (keep) from a listing article (gate).

Do not implement a watchlist run by looping `scrape_company()`: it opens a process pool **and** calls `extract_pending(limit=None)` per call, so N companies means N pools and N full Groq extraction passes. `scrape_watchlist()` extracts exactly once, at the end.

## Config and API

- `config/settings.yaml` -> `watchlist`: `default_since_hours` (0 disables the cutoff), `max_entities_per_run`, `min_term_length`, `gate_listing_sources`.
- `GET /api/v1/news-scrapper/companies/watchlist` — preview: totals, counts by type, derived terms. Cheap; call before spending a run.
- `POST /api/v1/news-scrapper/companies/scrape/watchlist` — 202 + `ScrapeJobResponse`, polled via the existing `GET /companies/scrape/{job_id}`.
- Both require MySQL: `get_mysql_dao` returns 503 when it is not configured.

## Verification

- Offline: `python -m pytest tests/test_watchlist.py tests/test_agent_watchlist.py tests/test_watchlist_routes.py`. The agent tests stub the pool, storage and extraction, so they assert job fan-out and the single extraction without touching Neo4j.
- Integration (seeded test DB): watchlist slice counts and term derivation in `tests/test_mysql_integration.py`. The fixture backdates all rows 30 days and marks 7 active entities as added 2h ago, plus one Inactive seller and one DROPPED lead to prove `created_since` composes with the active filters.

## Known limits

- The gate runs **after** each article is fetched, so it saves storage and Groq spend, not crawl time. Gating on listing-page titles inside the worker needs titles carried out of `_listing_links_with_dates`.
- The `since` cutoff is a **naive** `datetime.now()` compared against MySQL `DATETIME` values. Correct while the API host and the MySQL server share a timezone; if they diverge, the window shifts by the offset and a nightly run silently misses or repeats companies. Pass an explicit `since` date to sidestep it.
- Search cost is linear in entities; `max_entities_per_run` is the only throttle.
- No scheduler job yet — the API endpoint is the trigger. The route body is thin enough that a nightly job can wrap the same calls.
- Backfill of the pre-existing tracked universe is not addressed.
