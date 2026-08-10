# Skill: Add a New API Endpoint

## When to Use
When you need to expose new data or queries through the REST API.

## Steps

### 1. Write the Neo4j query — `src/db/queries.py`
```python
def get_my_data(conn: Neo4jConnection, param: str) -> list[dict]:
    with conn.session() as session:
        result = session.run(
            "MATCH (n:Deal {sector: $sector}) RETURN n",
            sector=param,
        )
        return [record["n"] for record in result]
```
Always use `$param` syntax — never interpolate user input into Cypher.

### 2. Add Pydantic schemas — `src/api/schemas.py`
```python
class MyResponse(BaseModel):
    id: str
    sector: Optional[str] = None
```

### 3. Add the route — `src/api/routes/<relevant_file>.py`
```python
@router.get("/my-endpoint", response_model=list[MyResponse])
def my_endpoint(
    param: str = Query(...),
    conn: Neo4jConnection = Depends(get_connection),
):
    return queries.get_my_data(conn, param)
```

### 4. Register a new router (if creating a new file)
In `src/api/app.py`:
```python
from .routes.my_module import router as my_router
app.include_router(my_router, prefix="/my-prefix", tags=["my-tag"])
```

## Authentication
A new route is authenticated automatically. `src/api/app.py` declares
`dependencies=[Depends(require_session)]` on the app itself, so every route it
serves has its session validated against company-service before the handler
runs — there is nothing to add.

Two things to know:

- The `apiEndPoint` sent for authorization is the **route template**, e.g.
  `/api/news-scrapper/deals/{deal_id}`. A new endpoint needs a matching `user_auth` row on
  the company-service side, or every call to it comes back 401/403.
- To make a route public, add `(METHOD, "/full/route/template")` to
  `EXEMPT_ROUTES` in `src/api/auth.py`. That list is the only way out, on
  purpose — forgetting to do anything leaves the route protected.

To read the caller inside a handler:
```python
from ..auth import UserSession, get_user_session

def my_endpoint(session: UserSession = Depends(get_user_session)):
    return {"profile_id": session.profile_id}
```

## Dependency Injection
Always use `conn: Neo4jConnection = Depends(get_connection)` from `src/api/dependencies.py` — never instantiate `Neo4jConnection` directly in a route.

## Pagination Pattern
Follow the existing `PaginatedResponse[T]` pattern from `schemas.py`:
```python
return PaginatedResponse(total=total, page=page, page_size=page_size, items=items)
```

## Testing
After adding the route, check Swagger UI at `http://localhost:8000/docs`.
