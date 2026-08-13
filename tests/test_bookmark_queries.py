"""The graph write behind a bookmark, and the row it hands back.

A bookmark is an edge from the caller — `(:NewsUser)-[:BOOKMARKED]->(:NewsDeal)`
— rather than a flag on the deal, which is what keeps one person's bookmark out
of everyone else's feed. The Cypher is asserted directly because a wrong edge
only shows up against a live graph, and by then it has already leaked.
"""
from unittest.mock import MagicMock

import pytest

from src.db import queries
from src.db.models import SCHEMA_CONSTRAINTS, SCHEMA_INDEXES

DEAL_ID = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"


class FakeNode(dict):
    """Stands in for a neo4j Node — `dict(node)` is all the row builders do."""


def make_conn(record):
    """A Neo4jConnection whose session returns one record, and records the run."""
    session = MagicMock()
    session.run.return_value.single.return_value = record
    conn = MagicMock()
    conn.session.return_value.__enter__ = MagicMock(return_value=session)
    conn.session.return_value.__exit__ = MagicMock(return_value=False)
    conn.mock_session = session
    return conn


def deal_record(**overrides):
    record = {
        "d": FakeNode({"id": DEAL_ID, "summary": "Zoho backs Ultraviolette."}),
        "article_id": "3f2504e0-4f89-11d3-9a0c-0305e82c3302",
        "article": None,
    }
    record.update(overrides)
    # neo4j's Record exposes .get(); a plain dict already does.
    return record


def cypher_of(conn):
    return conn.mock_session.run.call_args.args[0]


def params_of(conn):
    return conn.mock_session.run.call_args.kwargs


# ---------------------------------------------------------------------------
# Writing a bookmark
# ---------------------------------------------------------------------------

def test_setting_a_bookmark_creates_the_user_and_the_edge():
    conn = make_conn(deal_record(is_bookmarked=True))

    deal = queries.set_deal_bookmark(
        conn, DEAL_ID, True, user_id=50, profile_id="3c89e8b8", user_type=2
    )

    cypher = cypher_of(conn)
    assert "MERGE (u:NewsUser {user_id: $user_id})" in cypher
    assert "MERGE (u)-[b:BOOKMARKED]->(d)" in cypher
    # The deal itself must not be touched — that was the global-bookmark bug.
    assert "SET d." not in cypher
    assert params_of(conn)["user_id"] == 50
    assert params_of(conn)["profile_id"] == "3c89e8b8"
    assert params_of(conn)["user_type"] == 2
    assert deal["is_bookmarked"] is True


def test_the_user_node_carries_the_identity_from_the_session():
    conn = make_conn(deal_record(is_bookmarked=True))

    queries.set_deal_bookmark(conn, DEAL_ID, True, user_id=50, profile_id="p", user_type=4)

    cypher = cypher_of(conn)
    assert "u.profile_id = $profile_id" in cypher
    assert "u.user_type = $user_type" in cypher
    # Refreshed on every write: company-service owns these, not us.
    assert "SET u.profile_id" in cypher


def test_clearing_a_bookmark_deletes_only_the_edge():
    conn = make_conn(deal_record(is_bookmarked=False))

    deal = queries.set_deal_bookmark(conn, DEAL_ID, False, user_id=50)

    cypher = cypher_of(conn)
    assert "DELETE b" in cypher
    assert "MERGE (u:NewsUser" not in cypher, "unbookmarking must not create a user"
    assert "DELETE u" not in cypher and "DETACH" not in cypher
    assert deal["is_bookmarked"] is False


def test_clearing_matches_optionally_so_the_deal_still_comes_back():
    """Removing a bookmark that was never set is a no-op, not a 404."""
    conn = make_conn(deal_record(is_bookmarked=False))

    queries.set_deal_bookmark(conn, DEAL_ID, False, user_id=50)

    assert "OPTIONAL MATCH (u:NewsUser)-[b:BOOKMARKED]->(d)" in cypher_of(conn)


@pytest.mark.parametrize("bookmarked", [True, False])
def test_a_missing_deal_returns_none_so_the_route_can_404(bookmarked):
    conn = make_conn(None)

    assert queries.set_deal_bookmark(conn, DEAL_ID, bookmarked, user_id=50) is None


# ---------------------------------------------------------------------------
# Reading the flag back
# ---------------------------------------------------------------------------

def test_the_flag_comes_from_the_row_not_the_deal_node():
    """The row builder must read the per-caller projection."""
    deal = queries._deal_row_with_article(deal_record(is_bookmarked=True))

    assert deal["is_bookmarked"] is True


def test_a_stale_property_on_the_deal_is_ignored():
    """A graph that has not run scripts/drop_global_bookmarks.py still carries
    the old shared flag. Reading it would hand one person's bookmark to
    everyone — exactly the bug — so it is discarded."""
    record = deal_record(is_bookmarked=False)
    record["d"]["is_bookmarked"] = True

    deal = queries._deal_row_with_article(record)

    assert deal["is_bookmarked"] is False


def test_the_flag_defaults_to_false_where_no_caller_is_projected():
    """Queries that do not identify the caller omit the projection entirely."""
    record = deal_record()
    record["d"]["is_bookmarked"] = True

    assert queries._deal_row_with_article(record)["is_bookmarked"] is False


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def test_the_user_id_is_unique():
    """Two NewsUser nodes sharing an id would split one person's bookmarks in
    half depending on which one MERGE found."""
    assert any(
        "NewsUser" in stmt and "u.user_id IS UNIQUE" in stmt for stmt in SCHEMA_CONSTRAINTS
    )


def test_the_old_bookmark_index_is_gone():
    assert not any("is_bookmarked" in stmt for stmt in SCHEMA_INDEXES)
