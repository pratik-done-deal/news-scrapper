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

## Dependency Injection
Always use `conn: Neo4jConnection = Depends(get_connection)` from `src/api/dependencies.py` — never instantiate `Neo4jConnection` directly in a route.

## Pagination Pattern
Follow the existing `PaginatedResponse[T]` pattern from `schemas.py`:
```python
return PaginatedResponse(total=total, page=page, page_size=page_size, items=items)
```

## Testing
After adding the route, check Swagger UI at `http://localhost:8000/docs`.
