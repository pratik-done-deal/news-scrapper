import logging
import os
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException, Request

from ..dependencies import get_job_manager
from ..job_manager import JobManager
from ..schemas import CompanyScrapeRequest, ScrapeJobResponse
from ...agent import NewsAgent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/companies", tags=["company-scrape"])


def _select_sources(all_sources: list[dict], names: list[str] | None) -> list[dict]:
    """Return the configured sources matching `names` (or all when names is None)."""
    if not names:
        return all_sources
    wanted = {n.strip() for n in names}
    return [s for s in all_sources if s["name"] in wanted]


@router.post("/scrape", response_model=ScrapeJobResponse, status_code=202)
def trigger_company_scrape(
    body: CompanyScrapeRequest,
    request: Request,
    job_manager: JobManager = Depends(get_job_manager),
):
    executor: ThreadPoolExecutor = request.app.state.executor
    settings = request.app.state.settings
    sources_config = request.app.state.sources_config

    sources = _select_sources(sources_config["sources"], body.sources)
    if not sources:
        raise HTTPException(status_code=400, detail="No matching sources for the given names")

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


@router.get("/scrape/{job_id}", response_model=ScrapeJobResponse)
def get_company_scrape_status(job_id: str, job_manager: JobManager = Depends(get_job_manager)):
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return ScrapeJobResponse(**job)
