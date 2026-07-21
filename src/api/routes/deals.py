from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from ..dependencies import get_connection
from ..schemas import DealResponse, DealWithArticleResponse, PaginatedResponse
from ...db import queries
from ...db.queries import Neo4jConnection

router = APIRouter(prefix="/deals", tags=["deals"])


@router.get("", response_model=PaginatedResponse[DealWithArticleResponse])
def list_deals(
    sector: Optional[str] = Query(None, description="Filter by sector (partial match)"),
    deal_type: Optional[str] = Query(None, description="Filter by deal type (partial match)"),
    days: Optional[int] = Query(None, ge=1, description="Only deals from articles published in the last N days"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    conn: Neo4jConnection = Depends(get_connection),
):
    offset = (page - 1) * page_size
    total, items = queries.list_deals(
        conn,
        sector=sector,
        deal_type=deal_type,
        days=days,
        offset=offset,
        limit=page_size,
    )
    return PaginatedResponse(total=total, page=page, page_size=page_size, items=items)


@router.get("/{deal_id}", response_model=DealResponse)
def get_deal(deal_id: UUID, conn: Neo4jConnection = Depends(get_connection)):
    deal = queries.get_deal(conn, deal_id)
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal
