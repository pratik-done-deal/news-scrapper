# Development Guidelines

Last refreshed: 2026-06-20

Use this file before implementation work when code style, testing, architecture, or safety matters.

## Testing Expectations

Default verification for development changes:

```bash
python -m pytest
python scripts/check_agent_workflow.py
```

Run targeted live smoke checks only when the change needs real network, LLM, or Neo4j behavior:

```bash
python validate_filter.py
python test_date_range.py --start-date 2025-02-01 --end-date 2025-02-28 --max-pages 3
python main.py --start-date 2025-01-01 --end-date 2025-01-02
python api_server.py
```

Do not claim live verification unless it was actually run and the required env vars were present.

## Code Style

- Prefer existing module boundaries over new abstractions.
- Keep scraper failures non-fatal: `extract_article()` returns `(None, None, None)` on failure.
- Keep datetimes timezone-aware. Pipeline date ranges use IST; DB timestamps currently use UTC ISO strings unless a nearby code path says otherwise.
- Use Pydantic v2 validators for schema normalization.
- Keep Cypher parameterized with `$param`; never interpolate user-controlled strings.
- Keep LLM extraction deterministic: low temperature and JSON response format.
- Secrets are passed as CLI flags (`--neo4j-password`, `--gemini-api-key`, `--mysql-password`); they have empty defaults in `src/config.py` and must never be hardcoded there or printed.
- Avoid editing generated files, `venv/`, `__pycache__/`, or logs.

## Architecture Notes

- The runtime pipeline intentionally uses two processes: main producer plus one processing consumer.
- URL deduplication happens before scraping work and before processing writes.
- `src/db/repository.py` owns writes. `src/db/queries.py` owns read queries for API routes.
- `src/api/routes/scrape.py` triggers background runs through a thread pool and in-memory `JobManager`.
- Source configuration lives in `config/sources.yaml`; scraper class registration lives in `src/agent.py`.

## Safety Rules

1. Read `AGENTS.md` and `docs/agent-context/task-routing.md` before non-trivial work.
2. Read exact files before editing.
3. Check `git status --short` before edits and do not revert unrelated user changes.
4. Use offline tests before live smoke checks.
5. Ask before destructive operations or schema/data migrations.
