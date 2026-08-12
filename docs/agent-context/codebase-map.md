# Codebase Map

Last refreshed: 2026-08-04

Use this as the broad orientation cache before source search. Trust source code over this file when they disagree.

## Repo Snapshot

- Project: Deal and funding intelligence platform.
- Runtime: Python data pipeline plus FastAPI read API.
- Core pipeline: scrape article links and content, filter for M&A/funding relevance, extract structured deal data with Gemini, write Neo4j graph data.
- Stack: FastAPI, Neo4j driver, PyMySQL, Pydantic v2, OpenAI SDK (pointed at Gemini's compatible endpoint), requests, BeautifulSoup, trafilatura, PyYAML.
- Configuration: `src/config.py` dataclass defaults, overridden by CLI flags on each entry point. No `.env`.
- Offline development verification: `python -m pytest`.
- Live smoke checks: `python validate_filter.py --groq-api-key <key>`, `python test_date_range.py`.

## Key Directories

- `src/agent.py`: `NewsAgent`, multiprocessing queues, producer/consumer orchestration.
- `src/scraper/`: `WebScraper` base class and source-specific scraper implementations.
- `src/processor/`: `NewsFilter`, `DealExtractor`, and `DealData`.
- `src/db/`: Neo4j writes, schema setup, read query functions, and the read-only company MySQL DAO.
- `src/api/`: FastAPI app, routes, schemas, dependencies, and job manager.
- `config/`: YAML settings and news source definitions.
- `agents/`: runtime/domain agent docs.
- `skills/`: task playbooks for common product changes.
- `.agents/skills/`: development workflow skills for Codex-style task execution.
- `docs/agent-context/`: routing, maps, high-risk files, and module cache.
- `docs/reference/`: deep architecture references for cross-module questions.
- `tests/`: offline pytest tests.

## Runtime Modules

- `pipeline`: `src/agent.py`, `main.py`, `reprocess_article.py`, `reprocess_unprocessed.py`.
- `scraper`: `src/scraper/web_scraper.py`, `config/sources.yaml`.
- `filter`: `src/processor/filter.py`, `validate_filter.py`.
- `extractor`: `src/processor/extractor.py`, `config/settings.yaml`.
- `storage`: `src/db/repository.py`, `src/db/models.py`.
- `company-mysql`: `src/db/mysql_dao.py`, `src/db/mysql_queries.py`, `scripts/inspect_company_db.py`.
- `watchlist`: `src/processor/watchlist.py`, `NewsAgent.scrape_watchlist`, watchlist routes in `src/api/routes/company_scrape.py`.
- `api`: `api_server.py`, `src/api/**`, `src/db/queries.py`.

## Default Trace Order

1. Entry point: CLI script, API route, or `NewsAgent.run`.
2. Module owner: scraper, filter, extractor, storage, or API.
3. Data contract: Pydantic schema, config YAML, Cypher params, or queue message shape.
4. Shared runtime: process lifecycle, environment variables, logging, and settings.
5. Verification: offline pytest first; live smoke only when env/network dependencies are needed.
