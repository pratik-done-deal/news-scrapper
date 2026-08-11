"""Offline tests for the deals list route and its search predicate.

The Neo4j read is stubbed — what matters at the route level is that the search
term reaches the query. The predicate itself is asserted directly, since a
malformed fragment only fails against a live graph.
"""
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.dependencies import get_connection
from src.api.routes import deals
from src.db.queries import _search_condition

DEAL_ROW = {
    "id": "3f2504e0-4f89-11d3-9a0c-0305e82c3301",
    "article_id": "3f2504e0-4f89-11d3-9a0c-0305e82c3302",
    "deal_value": "Rs 5 crore",
    "sector": "Logistics",
    "deal_type": "funding",
    "summary": "HighLeaf leads Rs 5 Cr pre-Series A round in FreightFox.",
    "is_bookmarked": False,
    "article": None,
}


def build_client():
    app = FastAPI()
    app.include_router(deals.router, prefix="/api/news")
    app.dependency_overrides[get_connection] = lambda: object()
    return TestClient(app)


def test_search_term_reaches_the_query():
    client = build_client()

    with patch(
        "src.api.routes.deals.queries.list_deals", return_value=(1, [DEAL_ROW])
    ) as list_deals:
        response = client.get("/api/news/deals", params={"q": "FreightFox"})

    assert response.status_code == 200
    assert list_deals.call_args.kwargs["q"] == "FreightFox"
    assert response.json()["total"] == 1


def test_search_composes_with_the_existing_filters():
    """The box is used while a range and the bookmark toggle are active, so the
    term has to travel alongside them rather than replace them."""
    client = build_client()

    with patch(
        "src.api.routes.deals.queries.list_deals", return_value=(0, [])
    ) as list_deals:
        response = client.get(
            "/api/news/deals",
            params={"q": "Ayati", "days": 7, "bookmarked": "true", "page": 2},
        )

    assert response.status_code == 200
    kwargs = list_deals.call_args.kwargs
    assert kwargs["q"] == "Ayati"
    assert kwargs["days"] == 7
    assert kwargs["bookmarked"] is True
    assert kwargs["offset"] == 20


def test_omitting_the_term_lists_everything():
    client = build_client()

    with patch(
        "src.api.routes.deals.queries.list_deals", return_value=(1, [DEAL_ROW])
    ) as list_deals:
        response = client.get("/api/news/deals")

    assert response.status_code == 200
    assert list_deals.call_args.kwargs["q"] is None


def test_predicate_covers_headline_source_summary_and_parties():
    condition = _search_condition("freightfox")

    assert "toLower(art.title) CONTAINS toLower($q)" in condition
    assert "toLower(art.source) CONTAINS toLower($q)" in condition
    assert "toLower(d.summary) CONTAINS toLower($q)" in condition
    # The party leg must not multiply the row: a deal with a buyer and a seller
    # would otherwise be counted twice in `total`.
    assert "EXISTS {" in condition
    assert "(sc:NewsCompany)-[:BOUGHT|SOLD|INVESTED_IN|INVOLVED_IN|ABOUT]->(d)" in condition


def test_a_blank_term_is_not_a_filter():
    """An empty box must list everything, not match every row's empty string."""
    assert _search_condition(None) == ""
    assert _search_condition("") == ""
    assert _search_condition("   ") == ""
