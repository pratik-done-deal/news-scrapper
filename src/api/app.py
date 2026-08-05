import os
import yaml
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from neo4j import GraphDatabase

from .job_manager import JobManager
from .routes import analytics, articles, companies, company_scrape, deals, extract, scrape
from ..agent import NewsAgent
from ..db.queries import Neo4jConnection
from ..scheduler.service import SchedulerService

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    neo4j_uri = os.environ.get("NEO4J_URI", "neo4j://127.0.0.1:7687")
    neo4j_user = os.environ.get("NEO4J_USER", "neo4j")
    neo4j_password = os.environ.get("NEO4J_PASSWORD")
    neo4j_database = os.environ.get("NEO4J_DATABASE", "neo4j")
    groq_api_key = os.environ.get("GROQ_API_KEY")

    if not neo4j_password:
        raise EnvironmentError("NEO4J_PASSWORD is not set")
    if not groq_api_key:
        raise EnvironmentError("GROQ_API_KEY is not set")

    with open("config/settings.yaml") as f:
        settings = yaml.safe_load(f)
    with open("config/sources.yaml") as f:
        sources_config = yaml.safe_load(f)

    db_cfg = settings.get("database", {})
    driver = GraphDatabase.driver(
        neo4j_uri,
        auth=(neo4j_user, neo4j_password),
        max_connection_pool_size=db_cfg.get("pool_size", 5),
    )
    app.state.conn = Neo4jConnection(driver, neo4j_database)
    app.state.settings = settings
    app.state.sources_config = sources_config
    app.state.job_manager = JobManager()
    app.state.executor = ThreadPoolExecutor(max_workers=2)

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

    yield

    app.state.scheduler_service.shutdown()
    app.state.executor.shutdown(wait=False)
    app.state.conn.driver.close()


app = FastAPI(
    title="News Scraping API",
    description="Trigger scraping jobs and query articles and M&A deals.",
    version="1.0.0",
    lifespan=lifespan,
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
app.include_router(scrape.router, prefix="/api/v1")
app.include_router(extract.router, prefix="/api/v1")
app.include_router(analytics.router, prefix="/api/v1")


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
