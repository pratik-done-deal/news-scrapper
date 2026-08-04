"""Offline tests for the company MySQL read queries — no live MySQL required."""
from datetime import datetime

import pytest
from conftest import FakeConnection, last_statement, make_dao

from src.db import mysql_queries as mq
from src.db.mysql_dao import _assert_read_only


def run(rows, fn, *args, **kwargs):
    """Run a query function against a fake connection; return (result, sql, params)."""
    conn = FakeConnection(rows=rows)
    dao, _ = make_dao(connections=[conn])
    result = fn(dao, *args, **kwargs)
    sql, params = last_statement(conn)
    return result, sql, params


SELLER_ROW = {
    "entity_type": "seller",
    "entity_id": 1,
    "company_name": "Acme Foods",
    "brand_name": "Acme",
    "website": "acme.example",
}


# --------------------------------------------------------------------------
# Source filters
# --------------------------------------------------------------------------

def test_all_three_sources_are_unioned_by_default():
    _, sql, _ = run([], mq.fetch_entities)
    assert "FROM company c" in sql
    assert "FROM buyer b" in sql
    assert "FROM leads l" in sql
    assert sql.count("UNION ALL") == 2


def test_seller_filter_keeps_null_status_and_excludes_junk():
    _, sql, params = run([], mq.fetch_sellers)
    assert "c.status IS NULL OR c.status NOT IN" in sql
    assert params[:4] == ["junk", "archived", "delist", "Inactive"]
    assert "TRIM(COALESCE(c.name, '')) <> ''" in sql


def test_buyer_filter_requires_a_company_name():
    _, sql, params = run([], mq.fetch_buyers)
    assert "TRIM(COALESCE(b.company_name, '')) <> ''" in sql
    assert "FROM company c" not in sql
    assert params == []


def test_lead_filter_binds_id_types_and_excluded_statuses():
    _, sql, params = run([], mq.fetch_leads)
    assert "l.primary_id_type IN" in sql
    assert params == ["seller_lead", "buyer_lead", "DROPPED", "CONVERTED"]


def test_buyer_and_lead_branches_project_a_null_brand_name():
    _, sql, _ = run([], mq.fetch_entities)
    assert sql.count("NULL      AS brand_name") + sql.count("NULL           AS brand_name") == 2


def test_entity_types_can_be_narrowed():
    _, sql, _ = run([], mq.fetch_entities, entity_types=[mq.SELLER, mq.LEAD])
    assert "FROM company c" in sql
    assert "FROM leads l" in sql
    assert "FROM buyer b" not in sql


def test_unknown_entity_type_is_rejected():
    dao, _ = make_dao()
    with pytest.raises(ValueError):
        mq.fetch_entities(dao, entity_types=["vendor"])


def test_empty_entity_types_is_rejected():
    dao, _ = make_dao()
    with pytest.raises(ValueError):
        mq.fetch_entities(dao, entity_types=[])


# --------------------------------------------------------------------------
# Name filtering and paging
# --------------------------------------------------------------------------

def test_name_filter_binds_one_wildcard_param_per_searched_column():
    _, sql, params = run([], mq.fetch_entities, name_like="acme")
    assert sql.count("LIKE %s") == 4  # seller name + brand, buyer name, lead name
    assert params.count("%acme%") == 4


def test_name_filter_targets_underlying_columns_not_the_alias():
    _, sql, _ = run([], mq.fetch_entities, name_like="acme")
    assert "c.name LIKE" in sql
    assert "b.company_name LIKE" in sql
    assert "l.name LIKE" in sql
    assert "company_name LIKE %s\n        )" not in sql  # never filters on the alias


def test_seller_search_also_matches_the_brand_name():
    _, sql, _ = run([], mq.fetch_sellers, name_like="ola")
    assert "c.brand_name LIKE" in sql
    assert " OR " in sql


def test_buyer_and_lead_search_have_no_brand_column():
    _, sql, _ = run([], mq.fetch_buyers, name_like="acme")
    assert "brand_name LIKE" not in sql
    _, sql, _ = run([], mq.fetch_leads, name_like="acme")
    assert "brand_name LIKE" not in sql


def test_like_wildcards_in_user_input_are_escaped():
    _, _, params = run([], mq.fetch_entities, entity_types=[mq.BUYER], name_like="50%_off")
    assert params == [r"%50\%\_off%"]


def test_escaped_term_is_reused_for_every_searched_column():
    _, _, params = run([], mq.fetch_sellers, name_like="a_b")
    assert params[-2:] == [r"%a\_b%", r"%a\_b%"]


def test_limit_and_offset_are_bound_as_params():
    _, sql, params = run([], mq.fetch_entities, entity_types=[mq.BUYER], limit=10, offset=20)
    assert sql.rstrip().endswith("LIMIT %s OFFSET %s")
    assert params[-2:] == [10, 20]


def test_no_limit_clause_when_limit_is_none():
    _, sql, _ = run([], mq.fetch_entities, entity_types=[mq.BUYER])
    assert "LIMIT" not in sql


def test_results_are_ordered_for_stable_paging():
    _, sql, _ = run([], mq.fetch_entities)
    assert "ORDER BY company_name, entity_type, entity_id" in sql


# --------------------------------------------------------------------------
# created_since — the incremental watchlist slice
# --------------------------------------------------------------------------

CUTOFF = datetime(2026, 8, 4, 0, 0, 0)


def test_created_since_binds_one_predicate_per_source():
    _, sql, params = run([], mq.fetch_entities, created_since=CUTOFF)
    assert sql.count(">= %s") == 3
    assert params.count(CUTOFF) == 3


def test_created_since_targets_each_branch_column():
    _, sql, _ = run([], mq.fetch_entities, created_since=CUTOFF)
    assert "c.created_at >= %s" in sql
    assert "b.created_at >= %s" in sql
    assert "l.created_at >= %s" in sql


def test_no_created_predicate_when_not_filtering():
    _, sql, _ = run([], mq.fetch_entities)
    assert "created_at" not in sql


def test_created_since_composes_with_the_active_filters():
    _, sql, params = run([], mq.fetch_sellers, created_since=CUTOFF)
    assert "c.status IS NULL OR c.status NOT IN" in sql
    assert params == ["junk", "archived", "delist", "Inactive", CUTOFF]


def test_created_since_precedes_the_name_filter_in_params():
    _, _, params = run([], mq.fetch_buyers, created_since=CUTOFF, name_like="acme")
    assert params == [CUTOFF, "%acme%"]


def test_count_entities_accepts_created_since():
    total, sql, params = run([{"total": 7}], mq.count_entities, created_since=CUTOFF)
    assert total == 7
    assert params.count(CUTOFF) == 3
    assert "COUNT(*)" in sql


def test_fetch_watchlist_passes_created_since_through():
    _, sql, params = run([], mq.fetch_watchlist, created_since=CUTOFF)
    assert "c.created_at >= %s" in sql
    assert params.count(CUTOFF) == 3


def test_fetch_watchlist_without_a_cutoff_returns_everything():
    _, sql, _ = run([], mq.fetch_watchlist)
    assert "created_at" not in sql
    assert sql.count("UNION ALL") == 2


def test_fetch_watchlist_narrows_entity_types_and_pages():
    _, sql, params = run(
        [], mq.fetch_watchlist, entity_types=[mq.LEAD], limit=5, offset=10
    )
    assert "FROM leads l" in sql
    assert "FROM company c" not in sql
    assert params[-2:] == [5, 10]


# --------------------------------------------------------------------------
# Counting and searching
# --------------------------------------------------------------------------

def test_count_entities_returns_total():
    total, sql, _ = run([{"total": 137}], mq.count_entities)
    assert total == 137
    assert "COUNT(*)" in sql


def test_count_entities_returns_zero_when_no_row():
    total, _, _ = run([], mq.count_entities)
    assert total == 0


def test_search_returns_rows_and_caps_the_limit():
    rows, sql, params = run([SELLER_ROW], mq.search_entities_by_name, "acme", limit=5)
    assert rows == [SELLER_ROW]
    assert params[-2:] == [5, 0]


def test_search_short_circuits_on_blank_input():
    conn = FakeConnection(rows=[SELLER_ROW])
    dao, _ = make_dao(connections=[conn])
    assert mq.search_entities_by_name(dao, "   ") == []
    assert conn.executed == []  # not even a connection checkout


# --------------------------------------------------------------------------
# Name list
# --------------------------------------------------------------------------

def test_entity_names_include_brand_names_and_drop_duplicates():
    rows = [
        SELLER_ROW,
        {"entity_type": "buyer", "entity_id": 2, "company_name": "acme foods", "brand_name": None},
        {"entity_type": "lead", "entity_id": 3, "company_name": " Zeta ", "brand_name": ""},
    ]
    names, _, _ = run(rows, mq.fetch_entity_names)
    assert names == ["Acme Foods", "Acme", "Zeta"]


def test_entity_names_skip_missing_values():
    rows = [{"entity_type": "buyer", "entity_id": 9, "company_name": None, "brand_name": None}]
    names, _, _ = run(rows, mq.fetch_entity_names)
    assert names == []


# --------------------------------------------------------------------------
# Generated SQL stays within the read-only guard
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "call",
    [
        lambda dao: mq.fetch_entities(dao),
        lambda dao: mq.fetch_entities(dao, name_like="a'b;c", limit=5, offset=5),
        lambda dao: mq.count_entities(dao, name_like="acme"),
        lambda dao: mq.fetch_sellers(dao),
        lambda dao: mq.fetch_buyers(dao),
        lambda dao: mq.fetch_leads(dao),
    ],
)
def test_generated_sql_passes_the_read_only_guard(call):
    conn = FakeConnection(rows=[])
    dao, _ = make_dao(connections=[conn])
    call(dao)  # would raise ReadOnlyViolation inside the DAO if rejected
    _assert_read_only(last_statement(conn)[0])
