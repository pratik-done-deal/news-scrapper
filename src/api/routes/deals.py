from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Engine

from ..dependencies import get_engine
from ..schemas import DealResponse, PaginatedResponse
from ...db import queries

router = APIRouter(prefix="/deals", tags=["deals"])


@router.get("", response_model=PaginatedResponse[DealResponse])
def list_deals(
    sector: Optional[str] = Query(None, description="Filter by sector (partial match)"),
    deal_type: Optional[str] = Query(None, description="Filter by deal type (partial match)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    engine: Engine = Depends(get_engine),
):
    offset = (page - 1) * page_size
    total, items = queries.list_deals(
        engine,
        sector=sector,
        deal_type=deal_type,
        offset=offset,
        limit=page_size,
    )
    return PaginatedResponse(total=total, page=page, page_size=page_size, items=items)


@router.get("/{deal_id}", response_model=DealResponse)
def get_deal(deal_id: UUID, engine: Engine = Depends(get_engine)):
    deal = queries.get_deal(engine, deal_id)
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal
