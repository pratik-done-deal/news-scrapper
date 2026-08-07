"""News for a company-DB entity — the seller/buyer card's news tab.

The UI knows a company as "S5123", not as the string an article called it. These
routes resolve that reference through the company DB and serve the deals the
resolved company takes part in, so the news feed is keyed by the same identity
the rest of the business uses.
"""

import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from ..dependencies import get_connection, get_mysql_dao
from ..schemas import EntityNewsResponse, EntitySummary
from ...db import queries
from ...db.mysql_dao import MySQLDAO
from ...db.queries import Neo4jConnection
from ...processor.entity_link import InvalidEntityRef, ResolvedEntity, resolve_ref

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/entities", tags=["entities"])


def _resolve_or_404(dao: MySQLDAO, entity_ref: str) -> ResolvedEntity:
    try:
        entity = resolve_ref(dao, entity_ref)
    except InvalidEntityRef as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if entity is None:
        raise HTTPException(
            status_code=404,
            detail=f"No active company DB entity for '{entity_ref}'",
        )
    return entity


@router.get(
    "/{entity_ref}/news",
    response_model=EntityNewsResponse,
    response_model_exclude_none=True,
)
def get_entity_news(
    entity_ref: str = Path(..., description="Company DB reference, e.g. 'S5123'"),
    date_from: Optional[date] = Query(None, description="Published on or after (YYYY-MM-DD)"),
    date_to: Optional[date] = Query(None, description="Published on or before (YYYY-MM-DD)"),
    bookmarked: Optional[bool] = Query(None, description="Only bookmarked deals when true"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    dao: MySQLDAO = Depends(get_mysql_dao),
    conn: Neo4jConnection = Depends(get_connection),
):
    """A tracked company's news, keyed by its company DB reference.

    Only articles that produced a Deal are returned — the same graph traversal
    as `GET /companies/search/news`, which means a company with coverage but no
    extracted deal yields an empty feed. That is deliberate: the feed carries
    structured deal data, not every mention.

    The company DB is the source of truth for the name. Resolution prefers the
    brand over the registered entity ("Ola", not "ANI Technologies Private
    Limited") because that is what press coverage uses, and it is the same rule
    the scrape searched under.
    """
    entity = _resolve_or_404(dao, entity_ref)

    offset = (page - 1) * page_size
    total, items = queries.search_articles_by_company_name(
        conn,
        entity.search_term,
        date_from=date_from,
        date_to=date_to,
        bookmarked=bookmarked,
        offset=offset,
        limit=page_size,
    )

    return EntityNewsResponse(
        entity=EntitySummary(
            ref=entity.ref,
            entity_type=entity.entity_type,
            entity_id=entity.entity_id,
            company_name=entity.company_name,
            brand_name=entity.brand_name,
            website=entity.website,
            search_term=entity.search_term,
        ),
        total=total,
        page=page,
        page_size=page_size,
        items=items,
    )


@router.get(
    "/{entity_ref}",
    response_model=EntitySummary,
    response_model_exclude_none=True,
)
def get_entity(
    entity_ref: str = Path(..., description="Company DB reference, e.g. 'S5123'"),
    dao: MySQLDAO = Depends(get_mysql_dao),
):
    """Resolve a reference to the company DB row and the term its news is filed
    under — the cheap call for checking a link before fetching a feed."""
    entity = _resolve_or_404(dao, entity_ref)
    return EntitySummary(
        ref=entity.ref,
        entity_type=entity.entity_type,
        entity_id=entity.entity_id,
        company_name=entity.company_name,
        brand_name=entity.brand_name,
        website=entity.website,
        search_term=entity.search_term,
    )
