from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from ..dependencies import get_connection
from ..schemas import DealWithArticleResponse, PaginatedResponse
from ...db import queries
from ...db.queries import Neo4jConnection

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("/search/deals", response_model=PaginatedResponse[DealWithArticleResponse])
def search_deals_by_company_name(
    name: str = Query(..., min_length=1, description="Partial company name to search for"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    conn: Neo4jConnection = Depends(get_connection),
):
    offset = (page - 1) * page_size
    total, items = queries.get_deals_by_company_name(conn, name, offset=offset, limit=page_size)
    return PaginatedResponse(total=total, page=page, page_size=page_size, items=items)


@router.get("/{company_id}/deals", response_model=PaginatedResponse[DealWithArticleResponse])
def get_company_deals(
    company_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    conn: Neo4jConnection = Depends(get_connection),
):
    if not queries.get_company(conn, company_id):
        raise HTTPException(status_code=404, detail="Company not found")
    offset = (page - 1) * page_size
    total, items = queries.get_deals_by_company(conn, company_id, offset=offset, limit=page_size)
    return PaginatedResponse(total=total, page=page, page_size=page_size, items=items)
