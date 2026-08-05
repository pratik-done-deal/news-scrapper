# AGENTS.md - Deal & Funding Intelligence Platform

Scrapes Indian financial news (ET, FE, CNBC TV18, IIFL), filters M&A/funding articles, extracts structured deal data via Groq LLM, stores in Neo4j. Exposed via FastAPI.
**Deep reference:** [docs/reference/project-context.md](docs/reference/project-context.md)

## Agentic Development Workflow

Use the smallest read path that can answer the task.

1. Read `docs/agent-context/task-routing.md`.
2. Follow that routing file to one context file, module cache, existing agent doc, or deep reference only when needed.
3. Move to exact source files once the owner is known.
4. Verify with the command named by `docs/agent-context/development-guidelines.md`.

Do not read every agent, skill, or cache file by default. If a module cache identifies the owner files and verification path, skip the matching runtime agent doc unless the task needs deeper behavior context. Source code wins when docs disagree.

## Codex-Compatible Structure

- `.agents/skills/`: development workflow skills. Each skill is a directory with `SKILL.md`.
- `.codex/agents/workflow-router.toml`: custom router alias for task sequencing.
- `docs/agent-context/`: first-hop routing, codebase maps, high-risk files, development rules, and mutable module cache.
- `docs/reference/`: deep architecture references; pull these only for cross-module or architecture-level questions.
- `agents/`: runtime/domain agent docs for the actual scrape-filter-extract-store product pipeline.
- `skills/`: product playbooks for common code changes. Prefer `.agents/skills/*` for development workflow sequencing.

## Naming Glossary

- `pipeline agent`: runtime documentation for `NewsAgent` and producer/consumer IPC.
- `workflow-router`: Codex alias for routing and sequencing agentic development work.
- `task-orchestrator`: development skill for decomposition, worker briefs, and optional subagent fan-out.

## Runtime Agents

| Agent | File | Responsibility |
|-------|------|---------------|
| Pipeline | [agents/pipeline-agent.md](agents/pipeline-agent.md) | Pipeline entry point; producer/consumer IPC |
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
python -m pytest              # offline development verification
python validate_filter.py     # live Groq/news smoke check for M&A keyword matching
python test_date_range.py     # live ET date range smoke check
```

## Cache Maintenance

- Update `docs/agent-context/module-cache/*.md` only for reusable, source-backed findings.
- Do not cache one-off debugging notes or speculation.
- Refresh `Last refreshed: YYYY-MM-DD` when a cache file is materially updated.
- Run `python scripts/check_agent_workflow.py` after workflow-doc or agent-context changes.
