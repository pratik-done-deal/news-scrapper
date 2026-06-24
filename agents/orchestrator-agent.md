# Orchestrator Agent

## Role
Coordinates the full scrape-filter-extract-store pipeline. Manages the producer/consumer multiprocessing pattern. Entry point for all pipeline runs.

## Context
- Lives in `src/agent.py`.
- Class: `NewsAgent`. Instantiated in `main.py`.
- Spawns exactly one consumer subprocess (`_processing_worker`) regardless of the number of sources.
- Uses `multiprocessing.Queue` for IPC: `job_queue` (scraper → processor) and `result_queue` (processor → main).

## Pipeline Flow

```
NewsAgent.run(sources, start_date, end_date)
│
├── Spawn Process 2 (_processing_worker)
│
├── For each source (serial in main process):
│   ├── _scrape_articles()
│   │   ├── _scrape_links()         ← ScraperAgent: links only
│   │   └── scraper.extract_article() ← ScraperAgent: full content
│   └── job_queue.put({source_name, articles})
│
├── job_queue.put(STOP_PROCESSING)
└── _wait_for_processor()           ← blocks until Process 2 is done

Process 2 (_processing_worker):
└── While True:
    ├── job = job_queue.get()
    └── _process_source_articles()
        ├── repo.save_article()     ← StorageAgent
        ├── filter.is_ma_funding_relevant() ← FilterAgent
        ├── extractor.extract()     ← ExtractorAgent
        └── repo.save_deal()        ← StorageAgent
```

## Skills

### `run(sources, start_date, end_date)`
Full pipeline execution. Accepts a list of source dicts (from `config/sources.yaml`) and optional IST date range strings (`YYYY-MM-DD`).

### `_scrape_links(source, dt_start, dt_end) → list[str]`
Delegates to the appropriate `WebScraper` based on `source["scraper"]` key. Uses date-range pagination if `paginate: true` and dates are provided.

### `_scrape_articles(source, dt_start, dt_end) → (link_count, articles)`
Calls `_scrape_links()` then fetches content for each new URL. Skips already-known URLs via `repo.url_exists()`. Filters by date if range is provided.

## Source Configuration
Each source dict from `config/sources.yaml` requires:
- `name` — display name (also used as log label)
- `url` — listing page URL
- `domain` — base domain for building absolute URLs
- `link_contains` — substring that article URLs must contain
- `scraper` — key into `SCRAPER_REGISTRY`
- `paginate` (optional, bool) — enables date-range pagination
- `max_pages` (optional, int) — page limit for pagination

## Scraper Registry
`SCRAPER_REGISTRY` in `agent.py` maps config key strings to `WebScraper` subclasses. Add a new entry here when adding a new scraper.

## Error Handling
- Per-source processing errors are logged and recorded; the pipeline continues with remaining sources.
- Worker process crash (`exitcode != 0`) raises `RuntimeError` in the main process.
- `STOP_PROCESSING` sentinel is always sent even if an exception occurs (via `finally` block).
