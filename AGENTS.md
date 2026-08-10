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
| `src/db/mysql_dao.py` | `MySQLDAO` — read-only pool for the company MySQL DB |
| `src/db/mysql_queries.py` | Company DB reads — sellers, buyers, leads |
| `src/db/names.py` | Company name normalisation shared by storage and watchlist |
| `src/processor/watchlist.py` | Search terms + entity gate for tracked companies |
| `src/processor/entity_link.py` | Company DB ref (`S5123`) → entity → the name its news is filed under |
| `src/api/` | FastAPI app, routes, schemas, DI |
| `src/api/auth.py` | Session validation against company-service; exempt route list |
| `src/config.py` | Deployment configuration — defaults plus the CLI flags that override them |
| `config/settings.yaml` | Timeouts, delays, Groq model, pool size |
| `config/sources.yaml` | News source list with scraper keys |

## Run Commands

Nothing is read from the environment: defaults live in `src/config.py` and
every one of them is a flag. The commands below spell out the full set each
entry point accepts, with the default shown as the value — drop any line to
keep that default. Only `--neo4j-password` and `--groq-api-key` have no usable
default and must always be passed. `--help` lists the same set.

```bash
# Pipeline — serves no HTTP and validates no sessions, so the --api-* and
# --auth-* flags do not apply; the rest do
python main.py \
    --neo4j-uri neo4j://127.0.0.1:7687 \
    --neo4j-user neo4j \
    --neo4j-password <pw> \
    --neo4j-database newsscrapedatabase \
    --groq-api-key <key> \
    --mysql-host 127.0.0.1 \
    --mysql-port 3306 \
    --mysql-user <user> \
    --mysql-password <pw> \
    --mysql-database company_db \
    --log-level INFO \
    --log-file news_agent.log \
    --log-max-bytes 52428800 \
    --log-backup-count 5

# Same, restricted to a date range (both dates required together)
python main.py --neo4j-password <pw> --groq-api-key <key> \
    --start-date 2025-01-01 --end-date 2025-01-31

# API server  (Swagger: http://localhost:8000/docs)
python api_server.py \
    --neo4j-uri neo4j://127.0.0.1:7687 \
    --neo4j-user neo4j \
    --neo4j-password <pw> \
    --neo4j-database newsscrapedatabase \
    --groq-api-key <key> \
    --auth-enabled true \
    --auth-base-url https://qa.done.deals \
    --auth-validate-path /api/company-service/v1/internal/token/validate \
    --auth-timeout-seconds 5 \
    --auth-cache-ttl-seconds 30 \
    --auth-trust-proxy-headers false \
    --api-host 0.0.0.0 \
    --api-port 8000 \
    --api-reload false \
    --cors-allowed-origins https://qa.done.deals,http://localhost:3000 \
    --scheduler-enabled true \
    --mysql-host 127.0.0.1 \
    --mysql-port 3306 \
    --mysql-user <user> \
    --mysql-password <pw> \
    --mysql-database company_db \
    --log-level INFO \
    --log-file news_agent.log \
    --log-max-bytes 52428800 \
    --log-backup-count 5

# Smallest API server that starts. Auth is on and company MySQL is skipped;
# the five --mysql-* flags are optional as a group — omit them all and the API
# runs without the company DB, or pass them all to enable it.
python api_server.py --neo4j-password <pw> --groq-api-key <key>

# Timers are off by default; opt exactly one instance in to own them.
python api_server.py --neo4j-password <pw> --groq-api-key <key> \
    --scheduler-enabled true

# Dev: autoreload, no auth, stdout logging only
python api_server.py --neo4j-password <pw> --groq-api-key <key> \
    --api-reload true --auth-enabled false --log-file none --log-level DEBUG

# Do not start the app module directly (`uvicorn src.api.app:app`): nothing has
# run the parser, so it comes up on the bare defaults with no credentials.

# Reprocess — same neo4j/groq/logging set as the pipeline
python reprocess_article.py <article_id> \
    --neo4j-uri neo4j://127.0.0.1:7687 --neo4j-user neo4j --neo4j-password <pw> \
    --neo4j-database newsscrapedatabase --groq-api-key <key>
python reprocess_unprocessed.py --neo4j-password <pw> --groq-api-key <key> \
    [--dry-run] [--limit N]

# Company MySQL schema inspection (read-only) — takes the --mysql-* set
python scripts/inspect_company_db.py \
    --mysql-host 127.0.0.1 --mysql-port 3306 \
    --mysql-user <user> --mysql-password <pw> --mysql-database company_db
python scripts/inspect_company_db.py --mysql-user <user> --mysql-password <pw> \
    --mysql-database company_db --table <table> --sample 5

# Seed a local test copy of the company DB (writes to company_db_test only).
# Includes sellers with explicit Done Deal ids (S5123 Delhivery … S5132 Zoho)
# so the entity news flow can be exercised end to end. Add --force when
# --mysql-database already names the target DB.
python scripts/seed_test_company_db.py \
    --mysql-host 127.0.0.1 --mysql-port 3306 \
    --mysql-user root --mysql-password "" \
    --database company_db_test

# One-time Postgres → Neo4j migration — --pg-url is required, no default
python migrate_pg_to_neo4j.py \
    --pg-url postgresql://user:pass@host:5432/news_db \
    --neo4j-uri neo4j://127.0.0.1:7687 --neo4j-user neo4j \
    --neo4j-password <pw> --neo4j-database newsscrapedatabase \
    [--dry-run] [--batch-size 100]
```

Watchlist runs (news restricted to companies tracked in the company DB) are
triggered over the API:

Every call below needs `-H "Authorization: $SESSION"` except the
`POST /tracked-companies` push, which is exempt (see Authentication).

```bash
export SESSION=90062adc6228-f   # a live Done Deal session id

# Done Deal push flow — the backend registers a company, the frontend reads by id.
# No company MySQL needed: the reference is stored on the Company node itself.
curl -X POST localhost:8000/api/news/tracked-companies \
     -H 'Content-Type: application/json' \
     -d '{"company_id":"S5124","company_name":"Meesho"}'           # 202 + backfill job_id
curl -H "Authorization: $SESSION" \
     'localhost:8000/api/news/tracked-companies/S5124/news'          # that company's deal feed

# MySQL-read flow (superseded by the above; delete once Done Deal pushes)
curl -H "Authorization: $SESSION" 'localhost:8000/api/news/entities/S5123'
curl -H "Authorization: $SESSION" 'localhost:8000/api/news/entities/S5123/news'
curl -H "Authorization: $SESSION" 'localhost:8000/api/news/companies/watchlist?limit=20'
curl -X POST localhost:8000/api/news/companies/scrape/watchlist \
     -H "Authorization: $SESSION" \
     -H 'Content-Type: application/json' -d '{"limit": 2}'
curl -H "Authorization: $SESSION" localhost:8000/api/news/companies/scrape/<job_id>
```

## Configuration

There is no `.env`. Every deployment value is a dataclass field in
`src/config.py` with a working default, and every one of them is overridable by
a flag on the entry point's parser. Precedence is exactly two layers: the
default in `src/config.py`, and whatever the caller passed.

`config/settings.yaml` is unchanged and separate: it holds tuning that is the
same in every deployment (timeouts, Groq model, pool sizes, scheduler
intervals). Anything that identifies a deployment lives in `src/config.py`.

```
--neo4j-uri            neo4j://127.0.0.1:7687
--neo4j-user           neo4j
--neo4j-password       <required, no default>
--neo4j-database       newsscrapedatabase
--groq-api-key         <required, no default>

# Auth — validated against company-service on every request
--auth-enabled              true      # false = no auth at all; local dev only
--auth-base-url             https://qa.done.deals
--auth-validate-path        /api/company-service/v1/internal/token/validate
--auth-timeout-seconds      5
--auth-cache-ttl-seconds    30        # 0 disables the cache
--auth-trust-proxy-headers  false

# Company MySQL (read-only) — optional; unset means the API runs without it
--mysql-host / --mysql-port / --mysql-user / --mysql-password / --mysql-database

# API server
--api-host               0.0.0.0
--api-port               8000
--api-reload             false       # dev only
--cors-allowed-origins   https://app.done.deals,https://qa.done.deals,http://localhost:3000
                                     # comma-separated; credentials are allowed so "*" will not work
--scheduler-enabled      false       # true on at most one instance
--log-level              INFO
--log-file               news_agent.log   # "none" for stdout only
--log-max-bytes          52428800
--log-backup-count       5
```

The three secrets default to empty because `src/config.py` is tracked by git;
a process that needs one it was not given exits with a message naming the flag.

`load_config()` also exports the resolved config to `NEWS_SCRAPPER_CONFIG` in
the environment. That is an internal transport for child processes — spawned
scrape workers, uvicorn's reloader — which start a fresh interpreter that never
ran the parser. It is not a configuration surface; do not set it by hand.

## Authentication

This service owns no users. Every request carries a Done Deal session id in
`Authorization` — the raw id, with no `Bearer ` or any other scheme prefix,
forwarded verbatim upstream — and
`src/api/auth.py` forwards it to company-service's
`POST /api/company-service/v1/internal/token/validate` along with the endpoint
being called. That endpoint answers both questions — is the session live, and
may this user's role call *this* endpoint — and its verdict is passed through
unchanged (401 stays 401, 403 stays 403).

- Enforced app-wide via `dependencies=[Depends(require_session)]` in
  `src/api/app.py`, so a new router is protected without opting in.
- The `apiEndPoint` sent is the **route template**
  (`/api/news/deals/{deal_id}`), not the literal URL, so `user_auth` needs one
  row per endpoint rather than one per company id. `auth.auth_endpoint_for`
  guarantees it carries `API_PREFIX` even if a gateway rewrite stripped the
  prefix from the path that reached uvicorn — a bare `/deals` matches no
  `user_auth` row and reads as a permission failure it is not.
- Public endpoints are listed in `auth.EXEMPT_ROUTES`: `GET /health` (probes
  carry no token) and `POST /api/news/tracked-companies` (Done Deal's backend
  pushes companies service-to-service). Swagger and `/openapi.json` are open too.
- Verdicts are cached for `--auth-cache-ttl-seconds` per (session, endpoint).
  Successes only — a revoked session keeps working for at most one TTL, while a
  newly granted permission takes effect immediately.
- An unreachable auth service is a **503**, never a 401 — a network fault must
  not tell every client their session expired.
- Handlers that need the caller take `session: UserSession = Depends(get_user_session)`.
  The caller's `profileId` also lands in every log line for that request.

`config/*.yaml` resolves against the repo root (`src/paths.py`), so the
process starts from any working directory. Logging is configured in one place
(`src/logging_config.py`) for every entry point; scrape workers log to stdout
only, since concurrent rotation of one file across processes loses records.

The scheduler is in-process with no cross-process lock, so it is **off by
default**. To run the timers at all, pass `--scheduler-enabled true` on exactly
**one** instance, and never more than one uvicorn worker on it.

## Tests

```bash
python -m pytest              # offline development verification
python -m pytest tests/test_auth.py    # session validation, fully offline
python validate_filter.py --groq-api-key <key>   # live Groq/news smoke check
python test_date_range.py     # live ET date range smoke check

# Auth against the real company-service. Verifies config, the session, and —
# with --all-routes — that user_auth has a row for every endpoint we serve.
# Exit 1 if anything is refused or unreachable.
python scripts/check_auth.py --session <sessionId>
python scripts/check_auth.py --session <sessionId> --all-routes

# Auth end to end with no QA access: a stub company-service on :9099 that
# accepts the session id "good-session". Unlike --auth-enabled false this
# exercises the auth path rather than skipping it.
python scripts/stub_auth_service.py &
python api_server.py --auth-base-url http://localhost:9099 \
    --neo4j-password <pw> --groq-api-key <key>

# Company MySQL integration tests — skipped unless a seeded test DB is reachable.
# pytest takes no config flags, so these tests read MYSQL_* from the environment
# directly; that is a test-only knob, not something the app reads any more.
python scripts/seed_test_company_db.py --mysql-user root --mysql-password ""
MYSQL_HOST=127.0.0.1 MYSQL_USER=root MYSQL_PASSWORD= python -m pytest tests/test_mysql_integration.py
```

## Cache Maintenance

- Update `docs/agent-context/module-cache/*.md` only for reusable, source-backed findings.
- Do not cache one-off debugging notes or speculation.
- Refresh `Last refreshed: YYYY-MM-DD` when a cache file is materially updated.
- Run `python scripts/check_agent_workflow.py` after workflow-doc or agent-context changes.
