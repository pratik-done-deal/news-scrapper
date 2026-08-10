# API Module Cache

Last refreshed: 2026-08-07

- Owners: `src/api/**`, `src/db/queries.py`, `api_server.py`.
- Runtime doc: `agents/api-agent.md`.
- Product playbook: `skills/add-api-route.md`.
- Source anchors: `src/api/routes/*.py` for endpoints; `src/api/schemas.py` for response/request contracts; `src/db/queries.py` for read Cypher.
- Route pattern: route module -> Pydantic schema -> `src/db/queries.py` function -> `Neo4jConnection` from dependency.
- Scrape trigger: `src/api/routes/scrape.py` runs `NewsAgent` in a background thread and records status in `JobManager`.
- Auth: `src/api/auth.py`; enforced app-wide via `dependencies=[Depends(require_session)]` on the `FastAPI(...)` call, so new routers are protected without opting in. Sessions are validated against company-service's `token/validate`, sending the **route template** as `apiEndPoint`. Public routes live in `auth.EXEMPT_ROUTES` (`GET /health`, `POST /api/news-scrapper/tracked-companies`). Handlers read the caller via `Depends(get_user_session)`.
- Test apps that build their own bare `FastAPI()` and include a router directly are unauthenticated — auth lives at app composition, so existing route tests need no token.
- Verification: schema/unit tests offline; FastAPI `TestClient` tests with mocked query layer where possible; live Swagger checks only after starting `python api_server.py`.
