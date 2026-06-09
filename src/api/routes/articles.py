from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from ..dependencies import get_connection
from ..schemas import ArticleDetailResponse, ArticleResponse, PaginatedResponse
from ...db import queries
from ...db.queries import Neo4jConnection

router = APIRouter(prefix="/articles", tags=["articles"])


@router.get("", response_model=PaginatedResponse[ArticleResponse])
def list_articles(
    source: Optional[str] = Query(None, description="Filter by source name"),
    date_from: Optional[date] = Query(None, description="Published on or after (YYYY-MM-DD)"),
    date_to: Optional[date] = Query(None, description="Published on or before (YYYY-MM-DD)"),
    is_ma_relevant: Optional[bool] = Query(None, description="Filter by M&A relevance"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    conn: Neo4jConnection = Depends(get_connection),
):
    offset = (page - 1) * page_size
    total, items = queries.list_articles(
        conn,
        source=source,
        date_from=date_from,
        date_to=date_to,
        is_ma_relevant=is_ma_relevant,
        offset=offset,
        limit=page_size,
    )
    return PaginatedResponse(total=total, page=page, page_size=page_size, items=items)


@router.get("/{article_id}", response_model=ArticleDetailResponse)
def get_article(article_id: UUID, conn: Neo4jConnection = Depends(get_connection)):
    article = queries.get_article(conn, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return article
