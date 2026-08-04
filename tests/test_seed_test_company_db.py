"""Offline tests for the test-DB seeder — SQL splitting and fixture integrity."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from seed_test_company_db import SCHEMA_FILE, split_statements  # noqa: E402


# --------------------------------------------------------------------------
# Splitter
# --------------------------------------------------------------------------

def test_splits_on_plain_semicolons():
    assert split_statements("SELECT 1; SELECT 2;") == ["SELECT 1", "SELECT 2"]


def test_trailing_statement_without_semicolon_is_kept():
    assert split_statements("SELECT 1; SELECT 2") == ["SELECT 1", "SELECT 2"]


def test_semicolon_inside_a_line_comment_does_not_split():
    statements = split_statements("-- many columns; these are the ones used\nSELECT 1;")
    assert statements == ["SELECT 1"]


def test_semicolon_inside_a_block_comment_does_not_split():
    assert split_statements("/* a; b */ SELECT 1;") == ["SELECT 1"]


def test_semicolon_inside_a_string_literal_does_not_split():
    statements = split_statements("INSERT INTO t VALUES ('a;b');")
    assert statements == ["INSERT INTO t VALUES ('a;b')"]


def test_doubled_quote_inside_a_literal_is_not_a_terminator():
    statements = split_statements("INSERT INTO t VALUES ('BYJU''S'); SELECT 1;")
    assert statements == ["INSERT INTO t VALUES ('BYJU''S')", "SELECT 1"]


def test_backslash_escaped_quote_inside_a_literal():
    statements = split_statements("INSERT INTO t VALUES ('a\\'b;c'); SELECT 1;")
    assert len(statements) == 2


def test_apostrophe_in_a_comment_does_not_open_a_literal():
    # A comment is skipped wholesale, so `don't` cannot corrupt quote state.
    assert split_statements("# don't split here\nSELECT 1;") == ["SELECT 1"]


def test_comment_only_input_yields_no_statements():
    assert split_statements("-- nothing here\n\n-- or here\n") == []


# --------------------------------------------------------------------------
# Fixture integrity — guards the seed file against a corrupting edit
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def statements() -> list[str]:
    return split_statements(SCHEMA_FILE.read_text(encoding="utf-8"))


def test_schema_file_creates_the_three_queried_tables(statements):
    created = [s for s in statements if s.upper().startswith("CREATE TABLE")]
    assert len(created) == 3
    for table in ("company", "buyer", "leads"):
        assert any(s.startswith(f"CREATE TABLE {table} ") for s in created)


def test_schema_file_drops_before_creating(statements):
    dropped = [s for s in statements if s.upper().startswith("DROP TABLE")]
    assert len(dropped) == 3
    assert statements.index(dropped[-1]) < statements.index(
        next(s for s in statements if s.upper().startswith("CREATE TABLE"))
    )


def test_every_column_the_queries_read_is_defined(statements):
    ddl = {
        table: next(s for s in statements if s.startswith(f"CREATE TABLE {table} "))
        for table in ("company", "buyer", "leads")
    }
    for column in ("id", "name", "brand_name", "website", "status"):
        assert column in ddl["company"]
    for column in ("id", "company_name", "website"):
        assert column in ddl["buyer"]
    for column in ("id", "name", "website", "primary_id_type", "status"):
        assert column in ddl["leads"]


def test_seed_covers_every_excluded_case(statements):
    script = "\n".join(statements)
    for excluded in ("junk", "archived", "delist", "Inactive", "DROPPED", "CONVERTED"):
        assert f"'{excluded}'" in script, f"seed data never exercises status {excluded!r}"
    assert "investor_lead" in script  # a primary_id_type outside the two in scope
    assert "NULL" in script


def test_seed_inserts_into_all_three_tables(statements):
    inserts = [s for s in statements if s.upper().startswith("INSERT INTO")]
    for table in ("company", "buyer", "leads"):
        assert any(s.startswith(f"INSERT INTO {table} ") for s in inserts)
