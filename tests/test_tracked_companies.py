"""The Done Deal push flow: register a company by reference, then read its news.

Covers the two halves separately — the repository write that stamps the
reference onto a Company node, and the routes the two callers use.
"""
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import current_user_id
from src.api.dependencies import get_connection, get_job_manager
from src.api.job_manager import JobManager
from src.api.routes import tracked_companies
from src.api.schemas import RegisterCompanyRequest
from src.config import AppConfig
from src.db.repository import NewsRepository

REGISTERED = {
    "id": "3f2504e0-4f89-11d3-9a0c-0305e82c3301",
    "name": "Zoho",
    "external_id": "S5122",
    "external_name": "Zoho Corporation Private Limited",
    "linked_at": "2026-08-06T10:00:00+00:00",
    "created": False,
    "deal_count": 1,
}

DEAL_ROW = {
    "id": "3f2504e0-4f89-11d3-9a0c-0305e82c3302",
    "article_id": "3f2504e0-4f89-11d3-9a0c-0305e82c3303",
    "deal_value": "$45 million",
    "deal_type": "funding_round",
    "summary": "Ultraviolette raised $45M from Zoho.",
    "is_bookmarked": False,
    "article": None,
}


# ---------------------------------------------------------------------------
# The write: stamping a reference onto a Company node
# ---------------------------------------------------------------------------

@pytest.fixture
def repo():
    repo = NewsRepository.__new__(NewsRepository)
    session = MagicMock()
    session.run.return_value.single.return_value = REGISTERED
    repo._session = MagicMock()
    repo._session.return_value.__enter__ = MagicMock(return_value=session)
    repo._session.return_value.__exit__ = MagicMock(return_value=False)
    repo._mock_session = session
    return repo


def test_node_is_keyed_by_the_normalised_name(repo):
    """The extractor MERGEs on the normalised name; registration must land on
    that same node or the deals attach to an unstamped duplicate."""
    repo.register_company("S5122", "Zoho Corporation Private Limited")

    merge = [c for c in repo._mock_session.run.call_args_list if "MERGE (c:NewsCompany" in c.args[0]]
    assert len(merge) == 1
    assert merge[0].kwargs["name"] == "Zoho"
    assert merge[0].kwargs["external_id"] == "S5122"
    # The name Done Deal sent is kept for provenance, unnormalised.
    assert merge[0].kwargs["external_name"] == "Zoho Corporation Private Limited"


def test_reference_is_released_from_any_previous_node(repo):
    """`company_external_id` is unique — a rename would fail the write unless
    the old node gives the reference up first."""
    repo.register_company("S5122", "Zoho")

    queries = [c.args[0] for c in repo._mock_session.run.call_args_list]
    assert any("REMOVE old.external_id" in q for q in queries)
    # and it must run before the MERGE claims it
    assert next(i for i, q in enumerate(queries) if "REMOVE old.external_id" in q) < next(
        i for i, q in enumerate(queries) if "MERGE (c:NewsCompany" in q
    )


def test_brand_name_decides_the_node_when_it_differs_from_the_registered_name(repo):
    """The press writes "Meesho", never "Fashnear Technologies Private Limited".
    Keying on the registered name mints an orphan node with no deals, and the
    feed comes back empty while the real deals sit on "Meesho"."""
    repo.register_company(
        "S5124", "Fashnear Technologies Private Limited", brand_name="Meesho"
    )

    merge = [c for c in repo._mock_session.run.call_args_list if "MERGE (c:NewsCompany" in c.args[0]]
    assert merge[0].kwargs["name"] == "Meesho"
    # The registered name is still kept, for provenance.
    assert merge[0].kwargs["external_name"] == "Fashnear Technologies Private Limited"


def test_registered_name_is_used_when_no_brand_is_given(repo):
    repo.register_company("S5123", "Delhivery Limited")

    merge = [c for c in repo._mock_session.run.call_args_list if "MERGE (c:NewsCompany" in c.args[0]]
    assert merge[0].kwargs["name"] == "Delhivery"


def test_a_name_that_normalises_to_nothing_is_rejected(repo):
    with pytest.raises(ValueError):
        repo.register_company("S5122", "Ltd.")


# ---------------------------------------------------------------------------
# Request validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("company_id", ["5122", "X5122", "S", "", "abc"])
def test_malformed_reference_is_rejected(company_id):
    with pytest.raises(ValueError):
        RegisterCompanyRequest(company_id=company_id, company_name="Zoho")


@pytest.mark.parametrize(
    "sent, stored", [("s5122", "S5122"), ("S-5122", "S5122"), (" S5122 ", "S5122")]
)
def test_reference_is_normalised_to_one_canonical_form(sent, stored):
    """Done Deal sending 's5122' must not create a second, unreachable link."""
    assert RegisterCompanyRequest(company_id=sent, company_name="Zoho").company_id == stored


def test_blank_company_name_is_rejected():
    with pytest.raises(ValueError):
        RegisterCompanyRequest(company_id="S5122", company_name="   ")


# ---------------------------------------------------------------------------
# The routes
# ---------------------------------------------------------------------------

class RecordingExecutor:
    """Captures the background callable instead of running it."""

    def __init__(self):
        self.submitted = []

    def submit(self, fn, *args, **kwargs):
        self.submitted.append(fn)


def build_client(registered=REGISTERED):
    app = FastAPI()
    app.include_router(tracked_companies.router, prefix="/api/news")
    app.state.settings = {"scraping": {}, "groq": {}}
    app.state.config = AppConfig()
    app.state.sources_config = {"sources": [{"name": "Entrackr News", "search_url": "x{query}"}]}
    app.state.executor = RecordingExecutor()
    app.state.repo = MagicMock()
    app.state.repo.register_company.return_value = dict(registered)
    app.dependency_overrides[get_connection] = lambda: object()
    app.dependency_overrides[get_job_manager] = lambda: JobManager()
    # The real app identifies the caller through an app-level dependency this
    # bare app does not carry; the news route needs one to scope bookmarks.
    app.dependency_overrides[current_user_id] = lambda: 50
    return TestClient(app), app


def test_registering_returns_202_and_a_backfill_job():
    client, app = build_client()

    response = client.post(
        "/api/news/tracked-companies",
        json={"company_id": "S5122", "company_name": "Zoho"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["company_id"] == "S5122"
    assert body["graph_name"] == "Zoho"
    assert body["job_id"]
    assert body["deal_count"] == 1
    assert len(app.state.executor.submitted) == 1, "backfill must run in background"


def test_a_new_node_with_no_deals_is_reported_so_a_bad_name_is_visible():
    """created + 0 deals is the signature of a name the extractor has never
    seen. The caller needs to see it, not a bare success."""
    client, _ = build_client({**REGISTERED, "created": True, "deal_count": 0})

    body = client.post(
        "/api/news/tracked-companies",
        json={"company_id": "S5124", "company_name": "Fashnear Technologies Private Limited"},
    ).json()

    assert body["created"] is True
    assert body["deal_count"] == 0


def test_scrape_false_records_the_link_without_scraping():
    client, app = build_client()

    response = client.post(
        "/api/news/tracked-companies",
        json={"company_id": "S5122", "company_name": "Zoho", "scrape": False},
    )

    assert response.status_code == 202
    assert response.json().get("job_id") is None
    assert app.state.executor.submitted == []


def test_news_is_looked_up_by_reference_not_by_name():
    client, _ = build_client()

    with patch.object(
        tracked_companies.queries, "get_registered_company", return_value=dict(REGISTERED)
    ), patch.object(
        tracked_companies.queries, "get_news_by_external_id", return_value=(1, [DEAL_ROW])
    ) as news:
        response = client.get("/api/news/tracked-companies/S5122/news")

    assert response.status_code == 200
    assert news.call_args.args[1] == "S5122"
    body = response.json()
    assert body["total"] == 1
    assert body["company"]["company_id"] == "S5122"


def test_unregistered_reference_is_404_not_an_empty_feed():
    """The caller must be able to tell "never registered" from "no deals yet"."""
    client, _ = build_client()

    with patch.object(tracked_companies.queries, "get_registered_company", return_value=None):
        response = client.get("/api/news/tracked-companies/S9999/news")

    assert response.status_code == 404


def test_registered_company_with_no_deals_is_an_empty_200():
    client, _ = build_client()

    with patch.object(
        tracked_companies.queries, "get_registered_company", return_value=dict(REGISTERED)
    ), patch.object(
        tracked_companies.queries, "get_news_by_external_id", return_value=(0, [])
    ):
        response = client.get("/api/news/tracked-companies/S5122/news")

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["company"]["company_id"] == "S5122"


def test_filters_and_paging_reach_the_query():
    client, _ = build_client()

    with patch.object(
        tracked_companies.queries, "get_registered_company", return_value=dict(REGISTERED)
    ), patch.object(
        tracked_companies.queries, "get_news_by_external_id", return_value=(0, [])
    ) as news:
        client.get(
            "/api/news/tracked-companies/S5122/news",
            params={"page": 2, "page_size": 5, "bookmarked": "true", "date_from": "2026-01-01"},
        )

    assert news.call_args.kwargs["offset"] == 5
    assert news.call_args.kwargs["limit"] == 5
    assert news.call_args.kwargs["bookmarked"] is True
    assert news.call_args.kwargs["user_id"] == 50, "bookmarks are scoped to the caller"
    assert str(news.call_args.kwargs["date_from"]) == "2026-01-01"


def test_lookup_is_case_insensitive_on_the_reference():
    client, _ = build_client()

    with patch.object(
        tracked_companies.queries, "get_registered_company", return_value=dict(REGISTERED)
    ) as lookup:
        client.get("/api/news/tracked-companies/s5122")

    assert lookup.call_args.args[1] == "S5122"


# ---------------------------------------------------------------------------
# The Cypher behind the feed
# ---------------------------------------------------------------------------

def capture_cypher(**kwargs):
    """Run get_news_by_external_id against a fake session; return its Cypher."""
    statements = []
    session = MagicMock()

    def run(cypher, **params):
        statements.append(cypher)
        result = MagicMock()
        result.single.return_value = {"total": 0}
        result.__iter__ = lambda self: iter([])
        return result

    session.run.side_effect = run
    conn = MagicMock()
    conn.session.return_value.__enter__ = MagicMock(return_value=session)
    conn.session.return_value.__exit__ = MagicMock(return_value=False)

    tracked_companies.queries.get_news_by_external_id(conn, "S5122", **kwargs)
    return statements


@pytest.mark.parametrize(
    "filters",
    [
        {"date_from": date(2026, 1, 1)},
        {"date_to": date(2026, 8, 1)},
        {"bookmarked": True, "user_id": 50},
        {"bookmarked": False, "user_id": 50},
    ],
    ids=["date_from", "date_to", "bookmarked", "not_bookmarked"],
)
def test_a_filtered_feed_puts_a_with_between_the_call_and_the_where(filters):
    """A bare WHERE cannot follow a CALL subquery — Neo4j rejects the statement
    outright, so every filtered feed was a 500 until the WITH went in. Only the
    unfiltered path is legal without it, which is why it stayed hidden."""
    for cypher in capture_cypher(**filters):
        assert "} WITH d, art WHERE" in " ".join(cypher.split())


def test_an_unfiltered_feed_adds_no_where_at_all():
    for cypher in capture_cypher():
        assert "WHERE art.searched_company" in cypher, "the UNION leg keeps its own"
        assert "WITH d, art WHERE" not in " ".join(cypher.split())
