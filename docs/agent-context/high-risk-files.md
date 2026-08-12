# High Risk Files

Last refreshed: 2026-06-20

Read this before editing related behavior. Changes here tend to cross module boundaries.

## Pipeline Runtime

- `src/agent.py`: process lifecycle, queues, source dispatch, date range conversion, scraper registry, dedup handoff, worker shutdown.
- `main.py`: CLI entry point, settings/source loading, env requirements.
- `reprocess_article.py` and `reprocess_unprocessed.py`: one-off reprocessing paths that may bypass normal scraping.

## Scraping

- `src/scraper/web_scraper.py`: abstract scraper contract, HTTP session, shared date parsing, pagination, source-specific implementations.
- `config/sources.yaml`: source URLs, domains, link filters, scraper keys, pagination flags.

## Extraction and Filtering

- `src/processor/filter.py`: keyword precision/recall behavior.
- `src/processor/extractor.py`: LLM prompt, schema validators, controlled vocabularies, content truncation.
- `config/settings.yaml`: model, timeouts, rate limits, pool size.

## Storage

- `src/db/repository.py`: Neo4j writes, company normalization, URL hash dedupe, relationship roles.
- `src/db/models.py`: constraints and indexes applied on repository init.
- `src/db/queries.py`: read-only API Cypher. Keep user input parameterized.

## API

- `src/api/dependencies.py`: Neo4j connection lifecycle and app dependencies.
- `src/api/schemas.py`: external response contracts and request validation.
- `src/api/routes/scrape.py`: background job trigger and env var usage.
- `src/api/app.py`: router registration and app state.

## Gotchas

- Live scripts may need `--gemini-api-key`, Neo4j, and network access.
- Scraper site structure can change without code changes.
- The API job manager is in-memory; jobs are not durable across process restarts.
- Prompt/schema changes can alter stored graph relationship meaning, not only output text.
