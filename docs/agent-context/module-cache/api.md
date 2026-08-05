# API Module Cache

Last refreshed: 2026-06-23

- Owners: `src/api/**`, `src/db/queries.py`, `api_server.py`.
- Runtime doc: `agents/api-agent.md`.
- Product playbook: `skills/add-api-route.md`.
- Source anchors: `src/api/routes/*.py` for endpoints; `src/api/schemas.py` for response/request contracts; `src/db/queries.py` for read Cypher.
- Route pattern: route module -> Pydantic schema -> `src/db/queries.py` function -> `Neo4jConnection` from dependency.
- Scrape trigger: `src/api/routes/scrape.py` runs `NewsAgent` in a background thread and records status in `JobManager`.
- Verification: schema/unit tests offline; FastAPI `TestClient` tests with mocked query layer where possible; live Swagger checks only after starting `python api_server.py`.
