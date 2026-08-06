"""Offline tests for the entity news routes.

The app is assembled without the real lifespan. The DAO is the fake pooled
connection from conftest, so the real SQL builder and term derivation run; the
Neo4j read is stubbed, since what matters here is that the resolved search term
is what reaches the graph.
"""
from unittest.mock import patch

import pytest
from conftest import make_dao
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.dependencies import get_connection, get_mysql_dao
from src.api.routes import entities

SELLER_ROW = {
    "entity_type": "seller",
    "entity_id": 5123,
    "company_name": "Delhivery Limited",
    "brand_name": None,
    "website": "delhivery.com",
}

DEAL_ROW = {
    "id": "3f2504e0-4f89-11d3-9a0c-0305e82c3301",
    "article_id": "3f2504e0-4f89-11d3-9a0c-0305e82c3302",
    "deal_value": "Rs 530 crore",
    "sector": "Others",
    "deal_type": "divestiture",
    "summary": "Nexus sold Delhivery shares via block deals.",
    "is_bookmarked": False,
    "article": None,
}


def build_client(rows):
    app = FastAPI()
    app.include_router(entities.router, prefix="/api/v1")
    dao, _ = make_dao(rows=rows)
    app.dependency_overrides[get_mysql_dao] = lambda: dao
    app.dependency_overrides[get_connection] = lambda: object()
    return TestClient(app)


def test_news_feed_is_looked_up_by_the_resolved_name():
    """The UI sends S5123; the graph must be searched for "Delhivery" — the
    registered name minus its legal suffix, not the raw column value."""
    client = build_client([SELLER_ROW])

    with patch(
        "src.api.routes.entities.queries.search_articles_by_company_name",
        return_value=(1, [DEAL_ROW]),
    ) as search:
        response = client.get("/api/v1/entities/S5123/news")

    assert response.status_code == 200
    assert search.call_args.args[1] == "Delhivery"

    body = response.json()
    assert body["entity"]["ref"] == "S5123"
    assert body["entity"]["company_name"] == "Delhivery Limited"
    assert body["entity"]["search_term"] == "Delhivery"
    assert body["total"] == 1
    assert len(body["items"]) == 1


def test_paging_and_filters_reach_the_query():
    client = build_client([SELLER_ROW])

    with patch(
        "src.api.routes.entities.queries.search_articles_by_company_name",
        return_value=(0, []),
    ) as search:
        response = client.get(
            "/api/v1/entities/S5123/news",
            params={"page": 3, "page_size": 10, "bookmarked": "true"},
        )

    assert response.status_code == 200
    assert search.call_args.kwargs["offset"] == 20
    assert search.call_args.kwargs["limit"] == 10
    assert search.call_args.kwargs["bookmarked"] is True


def test_a_company_with_no_deals_returns_an_empty_feed_not_an_error():
    """Deals-only means real coverage can still yield nothing — the entity block
    is what tells the UI the lookup itself succeeded."""
    client = build_client([SELLER_ROW])

    with patch(
        "src.api.routes.entities.queries.search_articles_by_company_name",
        return_value=(0, []),
    ):
        response = client.get("/api/v1/entities/S5123/news")

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["entity"]["ref"] == "S5123"


def test_untracked_entity_is_a_404():
    client = build_client([])

    response = client.get("/api/v1/entities/S9999/news")

    assert response.status_code == 404


@pytest.mark.parametrize("ref", ["5123", "X5123", "S"])
def test_malformed_reference_is_a_400(ref):
    client = build_client([SELLER_ROW])

    response = client.get(f"/api/v1/entities/{ref}/news")

    assert response.status_code == 400


def test_entity_lookup_without_fetching_news():
    client = build_client([SELLER_ROW])

    response = client.get("/api/v1/entities/S5123")

    assert response.status_code == 200
    assert response.json() == {
        "ref": "S5123",
        "entity_type": "seller",
        "entity_id": 5123,
        "company_name": "Delhivery Limited",
        "website": "delhivery.com",
        "search_term": "Delhivery",
    }
