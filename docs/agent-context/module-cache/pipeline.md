# Pipeline Module Cache

Last refreshed: 2026-06-23

- Owner: `src/agent.py`.
- Runtime doc: `agents/pipeline-agent.md`.
- Entry points: `main.py`, `/scrape` route, reprocess scripts.
- Source anchors: `NewsAgent.run()`; `_scrape_links()`; `_scrape_articles()`; `_processing_worker()`; `_wait_for_processor()`; `SCRAPER_REGISTRY`.
- Process model: main process scrapes source batches; one spawned consumer process saves, filters, extracts, and stores.
- Queue messages: producer sends `{source_name, articles}` jobs; consumer sends `source_done`, `source_error`, `worker_error`, and `worker_done`.
- Shutdown: producer sends `STOP_PROCESSING` in normal path and in `finally`.
- Verification: offline tests for date conversion and message handling when possible; live pipeline run only with Neo4j, the LLM API, and network configured.
