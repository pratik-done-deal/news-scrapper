"""Offline tests for the deals list route, its search predicate and bookmarks.

The Neo4j read is stubbed — what matters at the route level is that the search
term and the caller's identity reach the query. The predicates themselves are
asserted directly, since a malformed fragment only fails against a live graph.
"""
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import BookmarkUser, current_user_id, require_bookmark_user
from src.api.dependencies import get_connection
from src.api.routes import deals
from src.db.queries import _bookmark_condition, _search_condition

DEAL_ID = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"

DEAL_ROW = {
    "id": DEAL_ID,
    "article_id": "3f2504e0-4f89-11d3-9a0c-0305e82c3302",
    "deal_value": "Rs 5 crore",
    "sector": "Logistics",
    "deal_type": "funding",
    "summary": "HighLeaf leads Rs 5 Cr pre-Series A round in FreightFox.",
    "is_bookmarked": False,
    "article": None,
}

CALLER = BookmarkUser(user_id=50, profile_id="3c89e8b8-8286", user_type=2)


def build_client(caller: BookmarkUser | None = CALLER):
    """A client for the deals router, standing in for the caller's session.

    The real app validates sessions through an app-level dependency; this app
    has no such dependency, so the two identity dependencies are overridden
    directly. `caller=None` is the unidentified reader.
    """
    app = FastAPI()
    app.include_router(deals.router, prefix="/api/news")
    app.dependency_overrides[get_connection] = lambda: object()
    app.dependency_overrides[current_user_id] = lambda: caller.user_id if caller else None
    app.dependency_overrides[require_bookmark_user] = lambda: caller
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
    assert kwargs["user_id"] == 50
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
    condition, params = _search_condition("freightfox")

    assert params == {"q0": "freightfox"}
    assert "toLower(art.title) CONTAINS $q0" in condition
    assert "toLower(art.source) CONTAINS $q0" in condition
    assert "toLower(d.summary) CONTAINS $q0" in condition
    # The party leg must not multiply the row: a deal with a buyer and a seller
    # would otherwise be counted twice in `total`.
    assert "EXISTS {" in condition
    assert "(sc:NewsCompany)-[:BOUGHT|SOLD|INVESTED_IN|INVOLVED_IN|ABOUT]->(d)" in condition


def test_every_word_must_match_but_not_as_one_phrase():
    """"Ayati Inflexor" has four words between it in the headline, so the words
    are required separately — a single CONTAINS on the phrase would find nothing."""
    condition, params = _search_condition("Ayati Inflexor")

    assert params == {"q0": "ayati", "q1": "inflexor"}
    assert " AND " in condition
    assert "$q0" in condition and "$q1" in condition


def test_terms_are_lowercased_for_the_parameter():
    _, params = _search_condition("FreightFox")

    assert params == {"q0": "freightfox"}


def test_a_long_query_is_capped():
    _, params = _search_condition(" ".join(f"w{i}" for i in range(20)))

    assert len(params) == 8


def test_a_blank_term_is_not_a_filter():
    """An empty box must list everything, not match every row's empty string."""
    assert _search_condition(None) == ("", {})
    assert _search_condition("") == ("", {})
    assert _search_condition("   ") == ("", {})


# ---------------------------------------------------------------------------
# Bookmarks — a bookmark belongs to one user, not to the deal
# ---------------------------------------------------------------------------

def test_the_bookmark_predicate_is_scoped_to_the_caller():
    """The filter must key off the user's own edge.

    A predicate on the deal alone is the bug this replaced: it made one
    person's bookmark everyone's.
    """
    condition, params = _bookmark_condition(True, 50)

    assert params == {"bookmark_user_id": 50}
    assert "(u:NewsUser)-[:BOOKMARKED]->(d)" in condition
    assert "u.user_id = $bookmark_user_id" in condition
    assert "d.is_bookmarked" not in condition
    # EXISTS rather than a traversal: a MATCH would multiply the row per
    # bookmark and inflate `total`.
    assert condition.startswith("EXISTS {")


def test_excluding_bookmarks_negates_the_same_predicate():
    condition, params = _bookmark_condition(False, 50)

    assert params == {"bookmark_user_id": 50}
    assert condition.startswith("NOT EXISTS {")


def test_not_filtering_binds_nothing():
    """`bookmarked` absent must list everything, bookmarked or not."""
    assert _bookmark_condition(None, 50) == ("", {})
    assert _bookmark_condition(None, None) == ("", {})


def test_an_unidentified_caller_holds_no_bookmarks():
    """A null user id compares false, so the filter needs no special case."""
    condition, params = _bookmark_condition(True, None)

    assert params == {"bookmark_user_id": None}
    assert "u.user_id = $bookmark_user_id" in condition


def test_bookmarking_is_attributed_to_the_calling_user():
    client = build_client()

    with patch(
        "src.api.routes.deals.queries.set_deal_bookmark",
        return_value={**DEAL_ROW, "is_bookmarked": True},
    ) as set_bookmark:
        response = client.post(
            "/api/news/deals/bookmark", json={"deal_id": DEAL_ID, "bookmark": True}
        )

    assert response.status_code == 200
    assert response.json()["is_bookmarked"] is True
    kwargs = set_bookmark.call_args.kwargs
    assert kwargs["user_id"] == 50
    assert kwargs["profile_id"] == "3c89e8b8-8286"
    assert kwargs["user_type"] == 2


def test_one_users_bookmark_is_invisible_to_another():
    """The regression test for the original bug.

    User 50 bookmarks a deal; user 51 lists the same deal and must not see it
    bookmarked. The isolation lives in the query parameter, so what is asserted
    here is that each caller's own id is the one that reaches it.
    """
    with patch(
        "src.api.routes.deals.queries.list_deals", return_value=(1, [DEAL_ROW])
    ) as list_deals:
        build_client(CALLER).get("/api/news/deals")
        mine = list_deals.call_args.kwargs["user_id"]

        other = BookmarkUser(user_id=51, profile_id="other", user_type=2)
        build_client(other).get("/api/news/deals")
        theirs = list_deals.call_args.kwargs["user_id"]

    assert (mine, theirs) == (50, 51)


def test_an_unidentified_reader_still_gets_the_list():
    """A missing user id must not turn a listing into a 401 — it just means
    nothing shows as bookmarked."""
    client = build_client(caller=None)

    with patch(
        "src.api.routes.deals.queries.list_deals", return_value=(1, [DEAL_ROW])
    ) as list_deals:
        response = client.get("/api/news/deals")

    assert response.status_code == 200
    assert list_deals.call_args.kwargs["user_id"] is None
