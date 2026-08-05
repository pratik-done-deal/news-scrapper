# API Agent

## Role
FastAPI REST layer that serves structured deal intelligence data from Neo4j. Stateless — reads from the database, never writes (except via the `/scrape` trigger route).

## Context
- Entry point: `api_server.py` → `src/api/app.py`.
- All Pydantic schemas in `src/api/schemas.py`.
- Dependency injection in `src/api/dependencies.py` — `get_connection()` yields a `Neo4jConnection`.
- Read queries in `src/db/queries.py`.

## Routes

| Module | Prefix | Key Endpoints |
|--------|--------|--------------|
| `routes/articles.py` | `/articles` | `GET /articles` (paginated, filterable), `GET /articles/{id}` |
| `routes/deals.py` | `/deals` | `GET /deals` (filterable by sector/type), `GET /deals/{id}` |
| `routes/companies.py` | `/companies` | `GET /companies` (search), `GET /companies/{name}/deals` |
| `routes/analytics.py` | `/analytics` | Deal stats, top buyers, sector trends |
| `routes/scrape.py` | `/scrape` | `POST /scrape` — triggers an on-demand pipeline run |

## Skills

### `list_articles(source, date_from, date_to, is_ma_funding_relevant, page, page_size)`
Returns a `PaginatedResponse[ArticleResponse]`. All filters are optional query params.

### `get_article(article_id)`
Returns `ArticleDetailResponse` including linked deals. 404 if not found.

### `list_deals(sector, deal_type, company, page, page_size)`
Returns paginated deals with optional filtering.

### `get_company_deals(company_name)`
Returns all deals a company is involved in (any relationship type).

## How to Add a New Endpoint
1. Add a Cypher query function to `src/db/queries.py`. Accept a `Neo4jConnection`, use parameterized Cypher.
2. Add request/response Pydantic models to `src/api/schemas.py`.
3. Add the route to the appropriate `src/api/routes/*.py` file.
4. If creating a new router file: register it in `src/api/app.py` via `app.include_router(router, prefix=..., tags=[...])`.
5. Use `conn: Neo4jConnection = Depends(get_connection)` in the route signature.

## Running
```bash
python api_server.py
# Swagger UI: http://localhost:8000/docs
# ReDoc:      http://localhost:8000/redoc
```
