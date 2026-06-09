from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query

from ..dependencies import get_connection
from ..schemas import DealsBySectorItem, DealVolumeItem, TopBuyerItem
from ...db import queries
from ...db.queries import Neo4jConnection

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/deals/by-sector", response_model=list[DealsBySectorItem])
def deals_by_sector(conn: Neo4jConnection = Depends(get_connection)):
    """Deal count grouped by sector, sorted by most active sector first."""
    return queries.analytics_deals_by_sector(conn)


@router.get("/companies/top-buyers", response_model=list[TopBuyerItem])
def top_buyers(
    limit: int = Query(10, ge=1, le=100, description="Number of companies to return"),
    conn: Neo4jConnection = Depends(get_connection),
):
    """Companies that appear most frequently as the buyer/acquirer in deals."""
    return queries.analytics_top_buyers(conn, role="buyer", limit=limit)


@router.get("/companies/top-investors", response_model=list[TopBuyerItem])
def top_investors(
    limit: int = Query(10, ge=1, le=100, description="Number of companies to return"),
    conn: Neo4jConnection = Depends(get_connection),
):
    """Companies that appear most frequently as the investor in funding rounds."""
    return queries.analytics_top_buyers(conn, role="investor", limit=limit)


@router.get("/deals/volume", response_model=list[DealVolumeItem])
def deal_volume(
    group_by: Literal["day", "month", "year"] = Query("month", description="Time bucket size"),
    date_from: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    conn: Neo4jConnection = Depends(get_connection),
):
    """Deal count per time period. Useful for charting deal flow over time."""
    return queries.analytics_deal_volume(conn, group_by=group_by, date_from=date_from, date_to=date_to)
