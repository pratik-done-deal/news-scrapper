# AGENTS.md — Deal & Funding Intelligence Platform

Scrapes Indian financial news (ET, FE, CNBC TV18, IIFL), filters M&A/funding articles, extracts structured deal data via Groq LLM, stores in Neo4j. Exposed via FastAPI.
**Deep reference:** [contexts/project-context.md](contexts/project-context.md)

## Subagents

| Agent | File | Responsibility |
|-------|------|---------------|
| Orchestrator | [agents/orchestrator-agent.md](agents/orchestrator-agent.md) | Pipeline entry point; producer/consumer IPC |
| Scraper | [agents/scraper-agent.md](agents/scraper-agent.md) | Fetches links + article content from news sites |
| Filter | [agents/filter-agent.md](agents/filter-agent.md) | Keyword-based M&A/funding relevance gate |
| Extractor | [agents/extractor-agent.md](agents/extractor-agent.md) | Groq LLM → structured `DealData` |
| Storage | [agents/storage-agent.md](agents/storage-agent.md) | Neo4j CRUD — articles, deals, companies |
| API | [agents/api-agent.md](agents/api-agent.md) | FastAPI REST layer |

## Skills

| Task | Playbook |
|------|---------|
| Add a news source scraper | [skills/add-scraper.md](skills/add-scraper.md) |
| Update M&A filter keywords | [skills/update-filter.md](skills/update-filter.md) |
| Modify deal extraction / add deal type | [skills/update-extractor.md](skills/update-extractor.md) |
| Add an API endpoint | [skills/add-api-route.md](skills/add-api-route.md) |

## Component Map

| File | Role |
|------|------|
| `src/agent.py` | `NewsAgent` — orchestrates the full pipeline |
| `src/scraper/web_scraper.py` | `ETScraper`, `FEScraper`, `CNBCScraper`, `IndiaInfolineScraper` |
| `src/processor/filter.py` | `NewsFilter` — keyword matching |
| `src/processor/extractor.py` | `DealExtractor` + `DealData` Pydantic schema |
| `src/db/repository.py` | `NewsRepository` — all Neo4j writes |
| `src/db/queries.py` | Read-only Cypher queries (API layer) |
| `src/api/` | FastAPI app, routes, schemas, DI |
| `config/settings.yaml` | Timeouts, delays, Groq model, pool size |
| `config/sources.yaml` | News source list with scraper keys |

## Run Commands

```bash
# Pipeline
python main.py
python main.py --start-date 2025-01-01 --end-date 2025-01-31

# API server  (Swagger: http://localhost:8000/docs)
python api_server.py

# Reprocess
python reprocess_article.py <article_id>
python reprocess_unprocessed.py
```

## Environment Variables

```
NEO4J_URI=neo4j://127.0.0.1:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=<required>
NEO4J_DATABASE=newsscrapedatabase
GROQ_API_KEY=<required>
```

## Tests

```bash
python validate_filter.py    # M&A keyword matching
python test_date_range.py    # date range filtering
```
