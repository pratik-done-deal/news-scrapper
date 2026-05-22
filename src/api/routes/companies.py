from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Engine

from ..dependencies import get_engine
from ..schemas import DealWithArticleResponse, PaginatedResponse
from ...db import queries

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("/search/deals", response_model=PaginatedResponse[DealWithArticleResponse])
def search_deals_by_company_name(
    name: str = Query(..., min_length=1, description="Partial company name to search for"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    engine: Engine = Depends(get_engine),
):
    offset = (page - 1) * page_size
    total, items = queries.get_deals_by_company_name(engine, name, offset=offset, limit=page_size)
    return PaginatedResponse(total=total, page=page, page_size=page_size, items=items)


@router.get("/{company_id}/deals", response_model=PaginatedResponse[DealWithArticleResponse])
def get_company_deals(
    company_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    engine: Engine = Depends(get_engine),
):
    if not queries.get_company(engine, company_id):
        raise HTTPException(status_code=404, detail="Company not found")
    offset = (page - 1) * page_size
    total, items = queries.get_deals_by_company(engine, company_id, offset=offset, limit=page_size)
    return PaginatedResponse(total=total, page=page, page_size=page_size, items=items)
