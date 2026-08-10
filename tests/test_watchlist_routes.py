"""Offline tests for the watchlist API routes.

The app is assembled without the real lifespan (no Neo4j, no Groq) and the DAO
is the fake pooled connection from conftest, so the routes exercise the real
SQL builder and the real term derivation.
"""
import pytest
from conftest import FakeConnection, make_dao
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.api.dependencies import get_mysql_dao
from src.api.job_manager import JobManager
from src.api.routes import company_scrape
from src.api.schemas import WatchlistScrapeRequest
from src.config import AppConfig

SOURCES = [
    {"name": "Entrackr News", "search_url": "https://entrackr.com/search?title={query}"},
    {"name": "Economic Times Corporate", "url": "https://et.com/corporate"},
]

SETTINGS = {
    "watchlist": {
        "default_since_hours": 24,
        "max_entities_per_run": 200,
        "min_term_length": 3,
        "gate_listing_sources": True,
    }
}

ROWS = [
    {
        "entity_type": "seller",
        "entity_id": 1,
        "company_name": "Bundl Technologies Private Limited",
        "brand_name": "Swiggy",
        "website": "swiggy.com",
    },
    {
        "entity_type": "buyer",
        "entity_id": 2,
        "company_name": "Nestle India Limited",
        "brand_name": None,
        "website": "nestle.in",
    },
]


class RecordingExecutor:
    """Captures the background callable instead of running it."""

    def __init__(self):
        self.submitted = []

    def submit(self, fn, *args, **kwargs):
        self.submitted.append(fn)
        return None


def make_client(rows=ROWS, settings=SETTINGS, with_dao=True):
    app = FastAPI()
    app.include_router(company_scrape.router, prefix="/api/news-scrapper")
    app.state.settings = settings
    app.state.config = AppConfig()
    app.state.sources_config = {"sources": SOURCES}
    app.state.job_manager = JobManager()
    app.state.executor = RecordingExecutor()
    app.state.mysql_dao = None

    if with_dao:
        # A fresh connection per checkout so repeated queries all see `rows`.
        dao, _ = make_dao(connections=[FakeConnection(rows=rows) for _ in range(8)])
        app.dependency_overrides[get_mysql_dao] = lambda: dao

    return TestClient(app), app


# --------------------------------------------------------------------------
# GET /companies/watchlist
# --------------------------------------------------------------------------

def test_preview_returns_derived_search_terms():
    client, _ = make_client()
    response = client.get("/api/news-scrapper/companies/watchlist")
    assert response.status_code == 200

    body = response.json()
    assert body["total_entities"] == 2
    assert body["total_terms"] == 2
    assert [e["search_term"] for e in body["entries"]] == ["Swiggy", "Nestle India"]
    assert body["counts_by_type"] == {"seller": 1, "buyer": 1}


def test_preview_defaults_to_the_configured_since_window():
    client, _ = make_client()
    body = client.get("/api/news-scrapper/companies/watchlist").json()
    assert body["since"] is not None


def test_preview_without_a_since_window_when_configured_to_zero():
    client, _ = make_client(settings={"watchlist": {"default_since_hours": 0}})
    assert client.get("/api/news-scrapper/companies/watchlist").json()["since"] is None


def test_preview_honours_an_explicit_since():
    client, _ = make_client()
    body = client.get("/api/news-scrapper/companies/watchlist?since=2026-08-01").json()
    assert body["since"].startswith("2026-08-01")


def test_preview_rejects_a_malformed_since():
    client, _ = make_client()
    assert client.get("/api/news-scrapper/companies/watchlist?since=01-08-2026").status_code == 400


def test_preview_rejects_an_unknown_entity_type():
    client, _ = make_client()
    response = client.get("/api/news-scrapper/companies/watchlist?entity_type=vendor")
    assert response.status_code == 400
    assert "vendor" in response.json()["detail"]


def test_preview_limit_caps_the_entries_but_not_the_totals():
    client, _ = make_client()
    body = client.get("/api/news-scrapper/companies/watchlist?limit=1").json()
    assert len(body["entries"]) == 1
    assert body["total_terms"] == 2


def test_preview_returns_503_without_mysql():
    client, _ = make_client(with_dao=False)
    response = client.get("/api/news-scrapper/companies/watchlist")
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


# --------------------------------------------------------------------------
# POST /companies/scrape/watchlist
# --------------------------------------------------------------------------

def test_trigger_accepts_and_returns_a_running_job():
    client, app = make_client()
    response = client.post("/api/news-scrapper/companies/scrape/watchlist", json={})
    assert response.status_code == 202

    body = response.json()
    assert body["status"] == "running"
    assert app.state.job_manager.get_job(body["job_id"]) is not None
    assert len(app.state.executor.submitted) == 1


def test_trigger_rejects_unknown_sources():
    client, _ = make_client()
    response = client.post(
        "/api/news-scrapper/companies/scrape/watchlist", json={"sources": ["Nonexistent Source"]}
    )
    assert response.status_code == 400
    assert "No matching sources" in response.json()["detail"]


def test_trigger_rejects_a_bad_date_pair():
    client, _ = make_client()
    response = client.post(
        "/api/news-scrapper/companies/scrape/watchlist", json={"start_date": "2026-01-01"}
    )
    assert response.status_code == 422


def test_trigger_rejects_an_unknown_entity_type():
    client, _ = make_client()
    response = client.post(
        "/api/news-scrapper/companies/scrape/watchlist", json={"entity_types": ["vendor"]}
    )
    assert response.status_code == 422


def test_trigger_errors_when_nothing_matches_and_gating_is_off():
    client, _ = make_client(
        rows=[],
        settings={"watchlist": {"default_since_hours": 24, "gate_listing_sources": False}},
    )
    response = client.post("/api/news-scrapper/companies/scrape/watchlist", json={})
    assert response.status_code == 400
    assert "No companies matched" in response.json()["detail"]


def test_trigger_still_runs_with_no_new_entities_when_gating_is_on():
    client, _ = make_client(rows=[])
    assert client.post("/api/news-scrapper/companies/scrape/watchlist", json={}).status_code == 202


def test_trigger_returns_503_without_mysql():
    client, _ = make_client(with_dao=False)
    assert client.post("/api/news-scrapper/companies/scrape/watchlist", json={}).status_code == 503


# --------------------------------------------------------------------------
# Request schema
# --------------------------------------------------------------------------

def test_request_defaults_are_all_optional():
    request = WatchlistScrapeRequest()
    assert request.since is None and request.limit is None


def test_request_rejects_a_zero_limit():
    with pytest.raises(ValidationError):
        WatchlistScrapeRequest(limit=0)


def test_request_requires_both_dates():
    with pytest.raises(ValidationError):
        WatchlistScrapeRequest(start_date="2026-01-01")


def test_request_rejects_a_bad_since_format():
    with pytest.raises(ValidationError):
        WatchlistScrapeRequest(since="2026/01/01")
