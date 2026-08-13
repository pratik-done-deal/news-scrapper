from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import BookmarkUser, current_user_id, require_bookmark_user
from ..dependencies import get_connection
from ..schemas import (
    BookmarkDealRequest,
    DealResponse,
    DealWithArticleResponse,
    PaginatedResponse,
)
from ...db import queries
from ...db.queries import Neo4jConnection

router = APIRouter(prefix="/deals", tags=["deals"])


@router.get("", response_model=PaginatedResponse[DealWithArticleResponse], response_model_exclude_none=True)
def list_deals(
    sector: Optional[str] = Query(None, description="Filter by sector (partial match)"),
    deal_type: Optional[str] = Query(None, description="Filter by deal type (partial match)"),
    days: Optional[int] = Query(None, ge=1, description="Only deals from articles published in the last N days"),
    bookmarked: Optional[bool] = Query(None, description="Only bookmarked deals when true"),
    q: Optional[str] = Query(
        None,
        description=(
            "Free-text search over the headline, source, deal summary and party "
            "names. Case-insensitive substring match; blank is treated as absent."
        ),
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    conn: Neo4jConnection = Depends(get_connection),
    user_id: Optional[int] = Depends(current_user_id),
):
    offset = (page - 1) * page_size
    total, items = queries.list_deals(
        conn,
        sector=sector,
        deal_type=deal_type,
        days=days,
        bookmarked=bookmarked,
        user_id=user_id,
        q=q,
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


@router.post(
    "/bookmark",
    response_model=DealWithArticleResponse,
    response_model_exclude_none=True,
)
def bookmark_deal(
    payload: BookmarkDealRequest,
    conn: Neo4jConnection = Depends(get_connection),
    user: BookmarkUser = Depends(require_bookmark_user),
):
    """Set or clear the calling user's bookmark on a deal (idempotent).

    Both keys are required in the body: `{"deal_id": "...", "bookmark": true}`.
    Send `bookmark: true` to bookmark the news, `false` to remove it.

    The bookmark belongs to whoever's session made the call — it is stored
    against their user id, and nobody else's listing changes. 401 when the
    session carries no user id, since there would be no owner to store it
    against.
    """
    deal = queries.set_deal_bookmark(
        conn,
        payload.deal_id,
        payload.bookmark,
        user_id=user.user_id,
        profile_id=user.profile_id,
        user_type=user.user_type,
    )
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal
