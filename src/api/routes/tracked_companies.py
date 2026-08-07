"""Companies pushed to us by the Done Deal backend, and their news.

Two calls, with different callers and very different costs:

- `POST /tracked-companies` — Done Deal's backend, once per company when it is
  added or renamed. Stamps its reference onto the Company node and kicks off a
  backfill scrape. Minutes of work, so it answers 202 and runs in background.
- `GET /tracked-companies/{company_id}/news` — the frontend, on every page view.
  A single indexed lookup against deals already in the graph. No scraping.

Keeping them apart is the point: a page view must never trigger a scrape.

Storing the reference on the node is what lets the read path skip the company
MySQL DB entirely — the frontend sends "S5122" and we match it directly,
instead of resolving a name through another system on every request.
"""

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request

from .. import API_PREFIX
from ..dependencies import get_connection, get_job_manager
from ..job_manager import JobManager
from ..schemas import (
    CompanyNewsResponse,
    RegisterCompanyRequest,
    RegisteredCompanyResponse,
)
from ...agent import NewsAgent
from ...db import queries
from ...db.names import strip_legal_suffix
from ...db.queries import Neo4jConnection
from ...db.repository import NewsRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tracked-companies", tags=["tracked-companies"])


def _response(row: dict, job_id: Optional[str] = None) -> RegisteredCompanyResponse:
    return RegisteredCompanyResponse(
        company_id=row["external_id"],
        company_name=row.get("external_name") or row["name"],
        graph_name=row["name"],
        node_id=row["id"],
        linked_at=row.get("linked_at"),
        created=row.get("created"),
        deal_count=row.get("deal_count"),
        job_id=job_id,
    )


@router.post("", response_model=RegisteredCompanyResponse, status_code=202)
def register_company(
    body: RegisterCompanyRequest,
    request: Request,
    job_manager: JobManager = Depends(get_job_manager),
):
    """Track a company and go find its news.

    Idempotent — re-sending the same company restamps the same node, and the
    scrape skips articles already stored, so a daily replay costs time rather
    than duplicates. Renaming a company in Done Deal moves the reference to the
    new node.

    The backfill matters because the routine scrape only ever walks today's
    listings: a company added now has months of coverage that only an on-site
    search will surface. Ongoing news needs no per-company work — the scheduler
    picks it up and the extractor links it to this node by name.
    """
    settings = request.app.state.settings
    sources_config = request.app.state.sources_config
    executor: ThreadPoolExecutor = request.app.state.executor

    repo: NewsRepository = request.app.state.repo
    try:
        row = repo.register_company(body.company_id, body.company_name, body.brand_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not body.scrape:
        return _response(row)

    # Search under the brand where there is one, else the registered name minus
    # its legal suffixes. Casing is left alone — this is typed into a site
    # search, not stored.
    raw = body.brand_name or body.company_name
    search_term = strip_legal_suffix(raw) or raw
    job_id = job_manager.create_job()

    def _run() -> None:
        try:
            agent = NewsAgent(
                settings,
                neo4j_uri=os.environ["NEO4J_URI"],
                neo4j_user=os.environ["NEO4J_USER"],
                neo4j_password=os.environ["NEO4J_PASSWORD"],
                neo4j_database=os.environ.get("NEO4J_DATABASE", "neo4j"),
                groq_api_key=os.environ["GROQ_API_KEY"],
            )
            result = agent.scrape_company(
                company=search_term,
                sources=sources_config["sources"],
            )
            result["company_id"] = body.company_id
            job_manager.complete_job(job_id, result)
        except Exception as exc:
            logger.exception(f"Backfill scrape for {body.company_id} failed")
            job_manager.fail_job(job_id, str(exc))

    executor.submit(_run)
    return _response(row, job_id=job_id)


@router.get(
    "/{company_id}/news",
    response_model=CompanyNewsResponse,
    response_model_exclude_none=True,
)
def get_company_news(
    company_id: str = Path(..., description="Done Deal reference, e.g. 'S5122'"),
    date_from: Optional[date] = Query(None, description="Published on or after (YYYY-MM-DD)"),
    date_to: Optional[date] = Query(None, description="Published on or before (YYYY-MM-DD)"),
    bookmarked: Optional[bool] = Query(None, description="Only bookmarked deals when true"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    conn: Neo4jConnection = Depends(get_connection),
):
    """A registered company's news, by its Done Deal reference.

    Only articles that produced a Deal are returned, so a company with press
    coverage but no extracted deal yields an empty feed — that is a valid state,
    not an error. A reference that was never registered is a 404, which is how
    the caller tells the two apart.

    Date filters apply to the article's publish date. Articles whose publish
    date could not be parsed are excluded by any date filter, so an unfiltered
    call can return more rows than a wide-ranged one.
    """
    company_id = company_id.strip().upper()
    company = queries.get_registered_company(conn, company_id)
    if company is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"'{company_id}' is not registered — "
                f"POST {API_PREFIX}/tracked-companies first"
            ),
        )

    offset = (page - 1) * page_size
    total, items = queries.get_news_by_external_id(
        conn,
        company_id,
        date_from=date_from,
        date_to=date_to,
        bookmarked=bookmarked,
        offset=offset,
        limit=page_size,
    )

    return CompanyNewsResponse(
        company=_response(company),
        total=total,
        page=page,
        page_size=page_size,
        items=items,
    )


@router.get(
    "/{company_id}",
    response_model=RegisteredCompanyResponse,
    response_model_exclude_none=True,
)
def get_tracked_company(
    company_id: str = Path(..., description="Done Deal reference, e.g. 'S5122'"),
    conn: Neo4jConnection = Depends(get_connection),
):
    """Check a reference is registered and see the name its news is filed under."""
    company = queries.get_registered_company(conn, company_id.strip().upper())
    if company is None:
        raise HTTPException(status_code=404, detail=f"'{company_id}' is not registered")
    return _response(company)
