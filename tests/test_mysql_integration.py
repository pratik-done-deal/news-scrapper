"""Integration tests against a seeded test copy of the company MySQL DB.

Skipped unless a reachable test database is configured — the offline suite must
still pass on a machine with no MySQL:

    python scripts/seed_test_company_db.py
    MYSQL_HOST=127.0.0.1 MYSQL_USER=root MYSQL_PASSWORD=... python -m pytest tests/test_mysql_integration.py

Expected counts come from `migrations/mysql_test_schema.sql`; update both
together.
"""
import os
from datetime import datetime, timedelta

import pytest

from src.db import mysql_queries as mq
from src.db.mysql_dao import MySQLConfig, MySQLDAO
from src.processor.entity_link import resolve_entity, resolve_ref
from src.processor.watchlist import WatchlistMatcher, build_entries, build_gate_terms

TEST_DATABASE = os.environ.get("TEST_MYSQL_DATABASE", "company_db_test")

# 33 auto-numbered sellers plus the 10 seeded with explicit Done Deal ids
# (S5123 Delhivery … S5132 Zoho), which the entity news flow resolves against.
ACTIVE_SELLERS = 43
ACTIVE_BUYERS = 28
ACTIVE_LEADS = 26

# The fixture backdates everything by 30 days, then marks a named handful as
# added 2 hours ago — 3 sellers, 2 buyers and 2 leads that survive the active
# filters, plus one Inactive seller and one DROPPED lead that must not.
RECENT_SELLERS = 3
RECENT_BUYERS = 2
RECENT_LEADS = 2


@pytest.fixture(scope="module")
def dao():
    if not os.environ.get("MYSQL_HOST"):
        pytest.skip("MYSQL_HOST not set; skipping company MySQL integration tests")

    config = MySQLConfig(
        host=os.environ["MYSQL_HOST"],
        port=int(os.environ.get("MYSQL_PORT", 3306)),
        user=os.environ.get("MYSQL_USER", ""),
        password=os.environ.get("MYSQL_PASSWORD", ""),
        database=TEST_DATABASE,
    )
    connection = MySQLDAO(config)
    if not connection.health_check():
        connection.close()
        pytest.skip(f"cannot reach MySQL database {TEST_DATABASE!r}")
    if "company" not in connection.list_tables():
        connection.close()
        pytest.skip(f"{TEST_DATABASE!r} is not seeded; run scripts/seed_test_company_db.py")

    yield connection
    connection.close()


# --------------------------------------------------------------------------
# The SQL runs and the active filters exclude what they should
# --------------------------------------------------------------------------

def test_active_counts_match_the_fixture(dao):
    assert mq.count_entities(dao, entity_types=[mq.SELLER]) == ACTIVE_SELLERS
    assert mq.count_entities(dao, entity_types=[mq.BUYER]) == ACTIVE_BUYERS
    assert mq.count_entities(dao, entity_types=[mq.LEAD]) == ACTIVE_LEADS
    assert mq.count_entities(dao) == ACTIVE_SELLERS + ACTIVE_BUYERS + ACTIVE_LEADS


def test_count_matches_fetch(dao):
    assert len(mq.fetch_entities(dao)) == mq.count_entities(dao)


def test_inactive_sellers_are_excluded(dao):
    names = {row["company_name"] for row in mq.fetch_sellers(dao)}
    assert "Think and Learn Private Limited" not in names   # Inactive
    assert "Dunzo Digital Private Limited" not in names     # Inactive
    assert "Stayzilla Hospitality Private Limited" not in names  # archived
    assert "Koinex Solutions Private Limited" not in names  # delist
    assert "Test Entry Do Not Use" not in names             # junk
    assert "Bundl Technologies Private Limited" in names


def test_null_status_sellers_are_kept(dao):
    names = {row["company_name"] for row in mq.fetch_sellers(dao)}
    assert "Razorpay Software Private Limited" in names


def test_blank_and_null_names_are_excluded_everywhere(dao):
    for row in mq.fetch_entities(dao):
        assert row["company_name"] is not None
        assert row["company_name"].strip() != ""


def test_terminal_and_out_of_scope_leads_are_excluded(dao):
    names = {row["company_name"] for row in mq.fetch_leads(dao)}
    assert "Sula Vineyards Limited" not in names          # DROPPED
    assert "Manyavar (Vedant Fashions Limited)" not in names  # CONVERTED
    assert "Kotak Mahindra Bank Limited" not in names     # investor_lead
    assert "Deloitte India" not in names                  # advisor_lead
    assert "The Whole Truth Foods" in names


def test_null_status_leads_are_excluded(dao):
    # `status NOT IN (...)` is NULL for a NULL status, so the row drops out.
    names = {row["company_name"] for row in mq.fetch_leads(dao)}
    assert "Unnamed Referral 2291" not in names


# --------------------------------------------------------------------------
# Row shape and identity
# --------------------------------------------------------------------------

def test_rows_have_the_normalized_shape(dao):
    row = mq.fetch_entities(dao, limit=1)[0]
    assert set(row) == {"entity_type", "entity_id", "company_name", "brand_name", "website"}
    assert row["entity_type"] in mq.ENTITY_TYPES


def test_only_sellers_carry_a_brand_name(dao):
    for row in mq.fetch_entities(dao):
        if row["entity_type"] != mq.SELLER:
            assert row["brand_name"] is None


def test_entity_id_is_unique_within_a_type(dao):
    keys = [(row["entity_type"], row["entity_id"]) for row in mq.fetch_entities(dao)]
    assert len(keys) == len(set(keys))


def test_results_are_name_ordered(dao):
    names = [row["company_name"] for row in mq.fetch_entities(dao)]
    assert names == sorted(names, key=lambda n: n.lower()) or names == sorted(names)


# --------------------------------------------------------------------------
# Paging, search, names
# --------------------------------------------------------------------------

def test_paging_walks_the_result_set_without_gaps_or_repeats(dao):
    everything = mq.fetch_entities(dao)
    page_size = 20
    paged = []
    for offset in range(0, len(everything), page_size):
        paged.extend(mq.fetch_entities(dao, limit=page_size, offset=offset))
    assert paged == everything


def test_search_matches_across_all_three_sources(dao):
    rows = mq.search_entities_by_name(dao, "limited", limit=200)
    assert {row["entity_type"] for row in rows} == set(mq.ENTITY_TYPES)


def test_search_is_a_substring_match(dao):
    rows = mq.search_entities_by_name(dao, "coffee")
    names = {row["company_name"] for row in rows}
    assert "Rage Coffee" in names
    assert "Sleepy Owl Coffee" in names
    assert "Third Wave Coffee Roasters" in names


def test_search_finds_a_seller_by_its_brand_name(dao):
    # News coverage says "Ola", not the registered entity name.
    rows = mq.search_entities_by_name(dao, "Ola")
    names = {row["company_name"] for row in rows}
    assert "ANI Technologies Private Limited" in names
    assert "Ola Electric Mobility Limited" in names

    swiggy = mq.search_entities_by_name(dao, "Swiggy")
    assert [row["company_name"] for row in swiggy] == ["Bundl Technologies Private Limited"]


def test_search_escapes_wildcards(dao):
    # '%' must match a literal percent sign, not everything.
    assert mq.search_entities_by_name(dao, "%") == []


def test_search_respects_the_limit(dao):
    assert len(mq.search_entities_by_name(dao, "limited", limit=3)) == 3


def test_entity_names_include_brands_and_are_deduped(dao):
    names = mq.fetch_entity_names(dao)
    assert "Swiggy" in names                                  # brand
    assert "Bundl Technologies Private Limited" in names      # registered name
    assert len(names) == len({n.casefold() for n in names})


# --------------------------------------------------------------------------
# The incremental watchlist slice
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def cutoff():
    return datetime.now() - timedelta(hours=24)


def test_created_since_returns_only_recently_added_rows(dao, cutoff):
    assert mq.count_entities(dao, entity_types=[mq.SELLER], created_since=cutoff) == RECENT_SELLERS
    assert mq.count_entities(dao, entity_types=[mq.BUYER], created_since=cutoff) == RECENT_BUYERS
    assert mq.count_entities(dao, entity_types=[mq.LEAD], created_since=cutoff) == RECENT_LEADS


def test_created_since_composes_with_the_active_filters(dao, cutoff):
    # Dunzo (Inactive) and Go Colors (DROPPED) were added recently too, and must
    # still be excluded — the cutoff narrows the active set, it does not replace it.
    names = {row["company_name"] for row in mq.fetch_watchlist(dao, created_since=cutoff)}
    assert "Dunzo Digital Private Limited" not in names
    assert "Go Colors (Go Fashion India Limited)" not in names
    assert "Kiranakart Technologies Private Limited" in names


def test_an_old_cutoff_returns_the_whole_active_universe(dao):
    old = datetime.now() - timedelta(days=365)
    assert mq.count_entities(dao, created_since=old) == mq.count_entities(dao)


def test_a_future_cutoff_returns_nothing(dao):
    assert mq.fetch_watchlist(dao, created_since=datetime.now() + timedelta(days=1)) == []


def test_watchlist_without_a_cutoff_is_the_full_universe(dao):
    assert len(mq.fetch_watchlist(dao)) == ACTIVE_SELLERS + ACTIVE_BUYERS + ACTIVE_LEADS


# --------------------------------------------------------------------------
# Rows -> search terms -> gate, against real data
# --------------------------------------------------------------------------

def test_search_terms_use_brands_and_strip_legal_suffixes(dao):
    terms = {
        entry.company_name: entry.search_term
        for entry in build_entries(mq.fetch_watchlist(dao))
    }
    assert terms["Bundl Technologies Private Limited"] == "Swiggy"
    assert terms["ANI Technologies Private Limited"] == "Ola"
    assert terms["Nestle India Limited"] == "Nestle India"
    assert terms["Zerodha Broking Limited"] == "Zerodha"


def test_no_search_term_still_carries_a_legal_suffix(dao):
    for entry in build_entries(mq.fetch_watchlist(dao)):
        assert not entry.search_term.lower().endswith((" limited", " ltd", " pvt ltd", " llp"))


def test_the_incremental_slice_yields_the_expected_terms(dao, cutoff):
    entries = build_entries(mq.fetch_watchlist(dao, created_since=cutoff))
    assert sorted(e.search_term for e in entries) == [
        "Farmley",
        "Mankind Pharma",
        "Peak XV Partners",
        "Rare Rabbit",
        "Reliance Retail Ventures",
        "Swiggy",
        "Zepto",
    ]


def test_gate_terms_cover_more_names_than_search_terms(dao):
    rows = mq.fetch_watchlist(dao)
    # One search per company, but the gate recognises brand *and* registered name.
    assert len(build_entries(rows)) == ACTIVE_SELLERS + ACTIVE_BUYERS + ACTIVE_LEADS
    assert len(build_gate_terms(rows)) > len(build_entries(rows))


def test_gate_matches_the_registered_name_a_search_would_never_use(dao):
    matcher = WatchlistMatcher(build_gate_terms(mq.fetch_watchlist(dao)))
    # The search term for this company is "Swiggy"; an article naming the legal
    # entity instead must still be recognised as being about a tracked company.
    assert matcher.match("Bundl Technologies reports revenue growth", None) == [
        "Bundl Technologies"
    ]


def test_gate_built_from_the_full_watchlist_matches_real_coverage(dao):
    matcher = WatchlistMatcher(build_gate_terms(mq.fetch_watchlist(dao)))

    matched = matcher.match(
        "Swiggy and Zepto raise fresh capital",
        "Nestle India was not part of the round, but Peak XV Partners led it.",
    )
    assert sorted(matched) == ["Nestle India", "Peak XV Partners", "Swiggy", "Zepto"]


def test_gate_drops_an_article_about_no_tracked_company(dao):
    matcher = WatchlistMatcher(build_gate_terms(mq.fetch_watchlist(dao)))
    assert matcher.match("Monsoon rainfall above average this week", "No companies here.") == []


# --------------------------------------------------------------------------
# Entity references — the UI's "S5123" resolving to a real row
# --------------------------------------------------------------------------

def test_seller_reference_resolves_to_the_expected_company(dao):
    """S5123 is Delhivery in the fixture, and must stay so across reseeds — the
    entity news flow keys off exactly this."""
    entity = resolve_ref(dao, "S5123")

    assert entity is not None
    assert entity.entity_type == "seller"
    assert entity.entity_id == 5123
    assert entity.company_name == "Delhivery Limited"
    assert entity.search_term == "Delhivery"
    assert entity.ref == "S5123"


def test_registered_name_falls_back_to_its_suffix_stripped_form(dao):
    """Oracle has no brand_name, so the term is the registered name minus the
    legal suffix — "Oracle", which is what the press writes."""
    assert resolve_ref(dao, "S5131").search_term == "Oracle"


def test_unknown_reference_resolves_to_none(dao):
    assert resolve_ref(dao, "S999999") is None


def test_prefix_selects_the_table(dao):
    """Seller 5123 exists; buyer 5123 does not. The prefix is what disambiguates."""
    assert resolve_ref(dao, "S5123") is not None
    assert resolve_ref(dao, "B5123") is None


def test_excluded_seller_does_not_resolve(dao):
    """A row the active filter drops must not serve news."""
    inactive_id = dao.fetch_value(
        "SELECT id FROM company WHERE status = %s LIMIT 1", ("Inactive",)
    )
    assert inactive_id is not None, "fixture should contain an Inactive seller"
    assert resolve_entity(dao, mq.SELLER, int(inactive_id)) is None


# --------------------------------------------------------------------------
# Read-only enforcement, against a real server
# --------------------------------------------------------------------------

def test_server_rejects_a_write_on_a_dao_connection(dao):
    import pymysql

    with pytest.raises(pymysql.err.MySQLError):
        with dao.cursor() as cur:  # bypasses the client-side guard on purpose
            cur.execute("INSERT INTO buyer (company_name) VALUES ('should not persist')")


def test_no_row_was_written_by_the_rejected_insert(dao):
    assert dao.fetch_value(
        "SELECT COUNT(*) FROM buyer WHERE company_name = %s", ("should not persist",)
    ) == 0
