import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException, Request

from ..dependencies import get_job_manager
from ..job_manager import JobManager
from ..schemas import ExtractRequest, ScrapeJobResponse
from ...agent import NewsAgent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/extract", tags=["extract"])


@router.post("", response_model=ScrapeJobResponse, status_code=202)
def trigger_extract(body: ExtractRequest, request: Request, job_manager: JobManager = Depends(get_job_manager)):
    executor: ThreadPoolExecutor = request.app.state.executor
    settings = request.app.state.settings
    config = request.app.state.config

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
            result = agent.extract_pending(limit=body.limit)
            job_manager.complete_job(job_id, result)
        except Exception as exc:
            logger.exception(f"Extraction job {job_id} failed")
            job_manager.fail_job(job_id, str(exc))

    executor.submit(_run)
    return ScrapeJobResponse(**job_manager.get_job(job_id))


@router.get("/{job_id}", response_model=ScrapeJobResponse)
def get_job_status(job_id: str, job_manager: JobManager = Depends(get_job_manager)):
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return ScrapeJobResponse(**job)
