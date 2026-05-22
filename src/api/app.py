import os
import yaml
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from sqlalchemy import create_engine

from .job_manager import JobManager
from .routes import analytics, articles, companies, deals, scrape

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise EnvironmentError("DATABASE_URL is not set")

    with open("config/settings.yaml") as f:
        settings = yaml.safe_load(f)
    with open("config/sources.yaml") as f:
        sources_config = yaml.safe_load(f)

    db_cfg = settings.get("database", {})
    app.state.engine = create_engine(
        database_url,
        pool_size=db_cfg.get("pool_size", 5),
        max_overflow=db_cfg.get("max_overflow", 10),
    )
    app.state.settings = settings
    app.state.sources_config = sources_config
    app.state.job_manager = JobManager()
    app.state.executor = ThreadPoolExecutor(max_workers=2)

    yield

    app.state.executor.shutdown(wait=False)
    app.state.engine.dispose()


app = FastAPI(
    title="News Scraping API",
    description="Trigger scraping jobs and query articles and M&A deals.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(articles.router, prefix="/api/v1")
app.include_router(companies.router, prefix="/api/v1")
app.include_router(deals.router, prefix="/api/v1")
app.include_router(scrape.router, prefix="/api/v1")
app.include_router(analytics.router, prefix="/api/v1")


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
