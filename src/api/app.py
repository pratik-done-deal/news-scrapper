import logging
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from neo4j import GraphDatabase

from .auth import AuthClient, AuthConfig, auth_enabled, require_session
from .job_manager import JobManager
from .routes import (
    analytics,
    articles,
    companies,
    company_scrape,
    deals,
    entities,
    extract,
    scrape,
    tracked_companies,
)
from ..agent import NewsAgent
from ..db.mysql_dao import MySQLConfig, MySQLDAO, MySQLNotConfigured
from ..db.queries import Neo4jConnection
from ..db.repository import NewsRepository
from ..logging_config import setup_logging
from ..paths import ENV_PATH, load_settings, load_sources_config
from ..scheduler.service import SchedulerService

load_dotenv(ENV_PATH)

logger = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "on"}


def _scheduler_enabled() -> bool:
    """Whether this process owns the scrape/extraction timers.

    The scheduler is in-process and holds no cross-process lock, so exactly one
    instance may run it. Extra API replicas must set SCHEDULER_ENABLED=false or
    every tick is duplicated — duplicate fetches, duplicate Groq spend, and
    concurrent writes to the same Neo4j nodes.
    """
    return os.environ.get("SCHEDULER_ENABLED", "true").strip().lower() in _TRUTHY


def _build_mysql_dao(settings: dict) -> Optional[MySQLDAO]:
    """Company MySQL is optional: without env vars the API starts without it."""
    if not MySQLConfig.is_configured():
        logger.info("Company MySQL not configured (MYSQL_HOST/MYSQL_DATABASE unset); skipping")
        return None
    try:
        dao = MySQLDAO(MySQLConfig.from_env(settings))
    except MySQLNotConfigured as exc:
        logger.warning("Company MySQL partially configured, skipping: %s", exc)
        return None
    if not dao.health_check():
        # Keep the DAO: the pool reconnects once the server is reachable again.
        logger.warning("Company MySQL configured but unreachable at startup; queries will fail until it recovers")
    return dao


def _build_auth_client() -> Optional[AuthClient]:
    """The client every route validates against, or None when auth is off.

    Unlike MySQL, a missing configuration is fatal: starting without it would
    serve every endpoint unauthenticated. Turning auth off has to be a
    deliberate `AUTH_ENABLED=false`, and it is loud when it happens.
    """
    if not auth_enabled():
        logger.warning(
            "AUTH_ENABLED=false — every endpoint is being served without session "
            "validation. This is for local development only."
        )
        return None
    return AuthClient(AuthConfig.from_env())


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Uvicorn only configures its own loggers, so without this every src.*
    # record — scheduler ticks included — is discarded.
    setup_logging()

    neo4j_uri = os.environ.get("NEO4J_URI", "neo4j://127.0.0.1:7687")
    neo4j_user = os.environ.get("NEO4J_USER", "neo4j")
    neo4j_password = os.environ.get("NEO4J_PASSWORD")
    neo4j_database = os.environ.get("NEO4J_DATABASE", "neo4j")
    groq_api_key = os.environ.get("GROQ_API_KEY")

    if not neo4j_password:
        raise EnvironmentError("NEO4J_PASSWORD is not set")
    if not groq_api_key:
        raise EnvironmentError("GROQ_API_KEY is not set")

    settings = load_settings()
    sources_config = load_sources_config()

    db_cfg = settings.get("database", {})
    driver = GraphDatabase.driver(
        neo4j_uri,
        auth=(neo4j_user, neo4j_password),
        max_connection_pool_size=db_cfg.get("pool_size", 5),
    )
    app.state.conn = Neo4jConnection(driver, neo4j_database)
    # Write path for the API. Routes read through `conn` (queries.py); the only
    # thing they write is the Done Deal → Company link, which belongs to the
    # repository. Schema init already ran above, so it is skipped here.
    app.state.repo = NewsRepository(
        uri=neo4j_uri,
        user=neo4j_user,
        password=neo4j_password,
        database=neo4j_database,
        pool_size=db_cfg.get("pool_size", 5),
    )
    app.state.auth_client = _build_auth_client()
    app.state.mysql_dao = _build_mysql_dao(settings)
    app.state.settings = settings
    app.state.sources_config = sources_config
    app.state.job_manager = JobManager()
    app.state.executor = ThreadPoolExecutor(max_workers=2)

    app.state.scheduler_service = None
    if _scheduler_enabled():
        scheduler_agent = NewsAgent(
            settings,
            neo4j_uri=neo4j_uri,
            neo4j_user=neo4j_user,
            neo4j_password=neo4j_password,
            neo4j_database=neo4j_database,
            groq_api_key=groq_api_key,
        )
        app.state.scheduler_service = SchedulerService(
            agent=scheduler_agent,
            sources=sources_config["sources"],
            scheduler_cfg=settings.get("scheduler", {}),
        )
        app.state.scheduler_service.start()
    else:
        logger.warning(
            "SCHEDULER_ENABLED=false — this instance serves API traffic only; "
            "scrape and extraction timers must run on exactly one other instance"
        )

    yield

    if app.state.scheduler_service is not None:
        app.state.scheduler_service.shutdown()
    app.state.executor.shutdown(wait=False)
    app.state.repo.close()
    app.state.conn.driver.close()
    if app.state.mysql_dao is not None:
        app.state.mysql_dao.close()
    if app.state.auth_client is not None:
        app.state.auth_client.close()


app = FastAPI(
    title="News Scraping API",
    description="Trigger scraping jobs and query articles and M&A deals.",
    version="1.0.0",
    lifespan=lifespan,
    # Applied to every route on the app, so a router added later is protected
    # without anyone remembering to opt in. Public endpoints are named in
    # `auth.EXEMPT_ROUTES` — the only way out is explicit.
    dependencies=[Depends(require_session)],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(articles.router, prefix="/api/v1")
app.include_router(companies.router, prefix="/api/v1")
app.include_router(company_scrape.router, prefix="/api/v1")
app.include_router(deals.router, prefix="/api/v1")
app.include_router(entities.router, prefix="/api/v1")
app.include_router(tracked_companies.router, prefix="/api/v1")
app.include_router(scrape.router, prefix="/api/v1")
app.include_router(extract.router, prefix="/api/v1")
app.include_router(analytics.router, prefix="/api/v1")


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
