import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..dependencies import get_job_manager, get_mysql_dao
from ..job_manager import JobManager
from ..schemas import (
    CompanyScrapeRequest,
    ScrapeJobResponse,
    WatchlistEntryResponse,
    WatchlistPreviewResponse,
    WatchlistScrapeRequest,
)
from ...agent import NewsAgent
from ...db import mysql_queries as mq
from ...db.mysql_dao import MySQLDAO
from ...processor.watchlist import WatchlistMatcher, build_entries, build_gate_terms

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/companies", tags=["company-scrape"])


def _select_sources(all_sources: list[dict], names: list[str] | None) -> list[dict]:
    """Return the configured sources matching `names` (or all when names is None)."""
    if not names:
        return all_sources
    wanted = {n.strip() for n in names}
    return [s for s in all_sources if s["name"] in wanted]


def _watchlist_cfg(settings: dict) -> dict:
    return settings.get("watchlist", {}) or {}


def _resolve_since(since: str | None, cfg: dict) -> datetime | None:
    """Turn the `since` date into a cutoff, defaulting to the configured window.

    A configured window of 0 means "no cutoff" — the full tracked universe.
    """
    if since:
        return datetime.strptime(since, "%Y-%m-%d")
    hours = cfg.get("default_since_hours", 24)
    if not hours:
        return None
    return datetime.now() - timedelta(hours=hours)


@router.post("/scrape", response_model=ScrapeJobResponse, status_code=202)
def trigger_company_scrape(
    body: CompanyScrapeRequest,
    request: Request,
    job_manager: JobManager = Depends(get_job_manager),
):
    executor: ThreadPoolExecutor = request.app.state.executor
    settings = request.app.state.settings
    sources_config = request.app.state.sources_config
    config = request.app.state.config

    sources = _select_sources(sources_config["sources"], body.sources)
    if not sources:
        raise HTTPException(status_code=400, detail="No matching sources for the given names")

    job_id = job_manager.create_job()

    def _run() -> None:
        try:
            agent = NewsAgent(
                settings,
                neo4j_uri=config.neo4j.uri,
                neo4j_user=config.neo4j.user,
                neo4j_password=config.neo4j.password,
                neo4j_database=config.neo4j.database,
                groq_api_key=config.groq.api_key,
            )
            result = agent.scrape_company(
                company=body.company,
                sources=sources,
                start_date=body.start_date,
                end_date=body.end_date,
            )
            job_manager.complete_job(job_id, result)
        except Exception as exc:
            logger.exception(f"Company scrape job {job_id} failed")
            job_manager.fail_job(job_id, str(exc))

    executor.submit(_run)
    return ScrapeJobResponse(**job_manager.get_job(job_id))


@router.get("/watchlist", response_model=WatchlistPreviewResponse)
def preview_watchlist(
    request: Request,
    since: str | None = Query(
        None, description="Companies added on or after this date (YYYY-MM-DD)"
    ),
    entity_type: list[str] | None = Query(None, description="seller / buyer / lead"),
    limit: int = Query(50, ge=1, le=500, description="How many entries to return"),
    dao: MySQLDAO = Depends(get_mysql_dao),
):
    """What a watchlist run would search for, without running it.

    Cheap enough to call before spending a run — it checks that the derived
    search terms look like names news outlets actually use.
    """
    cfg = _watchlist_cfg(request.app.state.settings)
    try:
        created_since = _resolve_since(since, cfg)
    except ValueError:
        raise HTTPException(status_code=400, detail="since must be YYYY-MM-DD")

    try:
        rows = mq.fetch_watchlist(dao, created_since=created_since, entity_types=entity_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    entries = build_entries(rows, cfg.get("min_term_length", 3))
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["entity_type"]] = counts.get(row["entity_type"], 0) + 1

    return WatchlistPreviewResponse(
        since=created_since.isoformat() if created_since else None,
        total_entities=len(rows),
        total_terms=len(entries),
        counts_by_type=counts,
        entries=[WatchlistEntryResponse(**vars(entry)) for entry in entries[:limit]],
    )


@router.post("/scrape/watchlist", response_model=ScrapeJobResponse, status_code=202)
def trigger_watchlist_scrape(
    body: WatchlistScrapeRequest,
    request: Request,
    job_manager: JobManager = Depends(get_job_manager),
    dao: MySQLDAO = Depends(get_mysql_dao),
):
    """Scrape news for the companies tracked in the company DB.

    Sources with an on-site search get one targeted search per newly added
    company; the rest scrape their listing and are gated down to articles that
    mention a tracked company.
    """
    executor: ThreadPoolExecutor = request.app.state.executor
    settings = request.app.state.settings
    sources_config = request.app.state.sources_config
    config = request.app.state.config
    cfg = _watchlist_cfg(settings)

    sources = _select_sources(sources_config["sources"], body.sources)
    if not sources:
        raise HTTPException(status_code=400, detail="No matching sources for the given names")

    created_since = _resolve_since(body.since, cfg)
    max_entities = body.limit or cfg.get("max_entities_per_run", 200)
    min_term_length = cfg.get("min_term_length", 3)
    gate_listing = cfg.get("gate_listing_sources", True)

    try:
        rows = mq.fetch_watchlist(
            dao, created_since=created_since, entity_types=body.entity_types
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    entries = build_entries(rows, min_term_length)
    if not entries and not gate_listing:
        raise HTTPException(
            status_code=400,
            detail="No companies matched the watchlist filters and listing gating is disabled",
        )

    # The gate matches against every tracked company, not just the new ones:
    # a listing scrape already fetched the article, and news about the other
    # 5,000 companies we track is exactly what we want to keep.
    matcher = None
    if gate_listing:
        all_rows = mq.fetch_watchlist(dao, entity_types=body.entity_types)
        matcher = WatchlistMatcher(build_gate_terms(all_rows, min_term_length))
        logger.info(f"Watchlist gate built from {len(matcher)} tracked company name(s)")

    job_id = job_manager.create_job()

    def _run() -> None:
        try:
            agent = NewsAgent(
                settings,
                neo4j_uri=config.neo4j.uri,
                neo4j_user=config.neo4j.user,
                neo4j_password=config.neo4j.password,
                neo4j_database=config.neo4j.database,
                groq_api_key=config.groq.api_key,
            )
            result = agent.scrape_watchlist(
                entries=entries,
                sources=sources,
                matcher=matcher,
                start_date=body.start_date,
                end_date=body.end_date,
                max_search_entities=max_entities,
            )
            job_manager.complete_job(job_id, result)
        except Exception as exc:
            logger.exception(f"Watchlist scrape job {job_id} failed")
            job_manager.fail_job(job_id, str(exc))

    executor.submit(_run)
    return ScrapeJobResponse(**job_manager.get_job(job_id))


@router.get("/scrape/{job_id}", response_model=ScrapeJobResponse)
def get_company_scrape_status(job_id: str, job_manager: JobManager = Depends(get_job_manager)):
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return ScrapeJobResponse(**job)
