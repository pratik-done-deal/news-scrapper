"""Offline tests for the company MySQL DAO — no live MySQL required."""
import pytest
from conftest import FakeConnection, FakeCursor, make_dao

from src.db.mysql_dao import (
    MySQLConfig,
    MySQLDAO,
    MySQLNotConfigured,
    ReadOnlyViolation,
    _assert_read_only,
    _quote_identifier,
)


# --------------------------------------------------------------------------
# Read-only guard
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "select id from companies",
        "  SHOW TABLES",
        "DESCRIBE companies",
        "EXPLAIN SELECT * FROM companies",
        "WITH x AS (SELECT 1) SELECT * FROM x",
        "(SELECT 1)",
        "SELECT 1;",
    ],
)
def test_read_statements_pass(sql):
    _assert_read_only(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO companies (name) VALUES ('x')",
        "UPDATE companies SET name = 'x'",
        "DELETE FROM companies",
        "DROP TABLE companies",
        "TRUNCATE companies",
        "CALL some_proc()",
        "LOAD DATA INFILE '/tmp/x' INTO TABLE companies",
        "  ",
    ],
)
def test_write_statements_rejected(sql):
    with pytest.raises(ReadOnlyViolation):
        _assert_read_only(sql)


def test_stacked_statements_rejected():
    with pytest.raises(ReadOnlyViolation):
        _assert_read_only("SELECT 1; DROP TABLE companies")


def test_leading_comment_cannot_hide_a_write():
    with pytest.raises(ReadOnlyViolation):
        _assert_read_only("-- SELECT 1\nDELETE FROM companies")
    with pytest.raises(ReadOnlyViolation):
        _assert_read_only("/* SELECT */ UPDATE companies SET name = 'x'")


def test_leading_comment_before_select_is_allowed():
    _assert_read_only("-- daily report\nSELECT id FROM companies")


def test_semicolon_inside_a_string_literal_is_not_a_second_statement():
    _assert_read_only("SELECT id FROM companies WHERE note = 'a;b'")


def test_dao_helpers_enforce_read_only():
    dao, _ = make_dao()
    with pytest.raises(ReadOnlyViolation):
        dao.fetch_all("DELETE FROM companies")
    with pytest.raises(ReadOnlyViolation):
        dao.fetch_one("UPDATE companies SET name = 'x'")


# --------------------------------------------------------------------------
# Identifier quoting
# --------------------------------------------------------------------------

def test_quote_identifier_accepts_plain_names():
    assert _quote_identifier("companies") == "`companies`"
    assert _quote_identifier("deal_2024$x") == "`deal_2024$x`"


@pytest.mark.parametrize("name", ["comp anies", "companies; DROP TABLE x", "`companies`", "", "a-b"])
def test_quote_identifier_rejects_injection(name):
    with pytest.raises(ValueError):
        _quote_identifier(name)


# --------------------------------------------------------------------------
# Fetch helpers
# --------------------------------------------------------------------------

def test_fetch_all_returns_rows_and_passes_params():
    conn = FakeConnection(rows=[{"id": 1}, {"id": 2}])
    dao, _ = make_dao(connections=[conn])
    rows = dao.fetch_all("SELECT id FROM companies WHERE id > %s", (0,))
    assert rows == [{"id": 1}, {"id": 2}]
    assert conn.executed[-1] == ("SELECT id FROM companies WHERE id > %s", (0,))


def test_fetch_one_returns_none_when_empty():
    dao, _ = make_dao(connections=[FakeConnection(rows=[])])
    assert dao.fetch_one("SELECT id FROM companies") is None


def test_fetch_value_returns_first_column():
    dao, _ = make_dao(connections=[FakeConnection(rows=[{"total": 7, "other": 9}])])
    assert dao.fetch_value("SELECT COUNT(*) AS total FROM companies") == 7


def test_fetch_value_returns_default_when_no_rows():
    dao, _ = make_dao(connections=[FakeConnection(rows=[])])
    assert dao.fetch_value("SELECT COUNT(*) FROM companies", default=0) == 0


def test_health_check_true_on_round_trip():
    dao, _ = make_dao(connections=[FakeConnection(rows=[{"ok": 1}])])
    assert dao.health_check() is True


def test_health_check_false_when_connect_fails():
    def factory(**kwargs):
        raise OSError("connection refused")

    config = MySQLConfig(host="h", user="u", password="p", database="d")
    dao = MySQLDAO(config, connect_factory=factory)
    assert dao.health_check() is False


# --------------------------------------------------------------------------
# Introspection
# --------------------------------------------------------------------------

def test_list_tables_scopes_to_configured_database():
    conn = FakeConnection(rows=[{"table_name": "companies"}, {"table_name": "deals"}])
    dao, _ = make_dao(connections=[conn])
    assert dao.list_tables() == ["companies", "deals"]
    sql, params = conn.executed[-1]
    assert params == ("company_db",)
    assert "information_schema.TABLES" in sql


def test_describe_table_binds_schema_and_table():
    conn = FakeConnection(rows=[{"column_name": "id"}])
    dao, _ = make_dao(connections=[conn])
    dao.describe_table("companies")
    assert conn.executed[-1][1] == ("company_db", "companies")


def test_sample_rows_clamps_limit_and_quotes_table():
    conn = FakeConnection(rows=[])
    dao, _ = make_dao(connections=[conn])
    dao.sample_rows("companies", limit=99999)
    assert conn.executed[-1][0] == "SELECT * FROM `companies` LIMIT 1000"


def test_sample_rows_rejects_bad_table_name():
    dao, _ = make_dao()
    with pytest.raises(ValueError):
        dao.sample_rows("companies; DROP TABLE x")


def test_count_rows_returns_int():
    dao, _ = make_dao(connections=[FakeConnection(rows=[{"total": 42}])])
    assert dao.count_rows("companies") == 42


# --------------------------------------------------------------------------
# Pooling
# --------------------------------------------------------------------------

def test_connection_is_reused_from_pool():
    conn = FakeConnection(rows=[{"ok": 1}])
    dao, created = make_dao(connections=[conn])
    dao.fetch_all("SELECT 1")
    dao.fetch_all("SELECT 1")
    assert len(created) == 1
    assert conn.ping_calls == 1  # first checkout opens fresh, second pings


def test_failed_statement_discards_connection():
    class ExplodingCursor(FakeCursor):
        def execute(self, sql, params=None):
            raise RuntimeError("server gone away")

    class ExplodingConnection(FakeConnection):
        def cursor(self):
            return ExplodingCursor(self)

    bad = ExplodingConnection()
    good = FakeConnection(rows=[{"ok": 1}])
    dao, created = make_dao(connections=[bad, good])

    with pytest.raises(RuntimeError):
        dao.fetch_all("SELECT 1")
    assert bad.closed is True

    assert dao.fetch_value("SELECT 1 AS ok") == 1
    assert len(created) == 2


def test_stale_connection_is_replaced_on_ping_failure():
    stale = FakeConnection(rows=[{"ok": 1}])
    fresh = FakeConnection(rows=[{"ok": 1}])
    dao, created = make_dao(connections=[stale, fresh])

    dao.fetch_all("SELECT 1")            # opens `stale`, returns it to the pool
    stale._ping_error = OSError("gone")  # simulate wait_timeout drop
    dao.fetch_all("SELECT 1")            # ping fails -> discard, open `fresh`

    assert stale.closed is True
    assert created == [stale, fresh]


def test_close_closes_pooled_connections_and_blocks_reuse():
    conn = FakeConnection(rows=[{"ok": 1}])
    dao, _ = make_dao(connections=[conn])
    dao.fetch_all("SELECT 1")
    dao.close()
    assert conn.closed is True
    with pytest.raises(RuntimeError):
        dao.fetch_all("SELECT 1")


def test_connect_kwargs_use_config_values():
    conn = FakeConnection(rows=[{"ok": 1}])
    dao, _ = make_dao(connections=[conn])
    dao.fetch_all("SELECT 1")
    kwargs = conn.connect_kwargs
    assert kwargs["host"] == "db.internal"
    assert kwargs["database"] == "company_db"
    assert kwargs["autocommit"] is True
    assert conn.executed[0][0] == "SET SESSION TRANSACTION READ ONLY"


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

def test_is_configured_requires_host_and_database(monkeypatch):
    monkeypatch.delenv("MYSQL_HOST", raising=False)
    monkeypatch.delenv("MYSQL_DATABASE", raising=False)
    assert MySQLConfig.is_configured() is False
    monkeypatch.setenv("MYSQL_HOST", "db.internal")
    assert MySQLConfig.is_configured() is False
    monkeypatch.setenv("MYSQL_DATABASE", "company_db")
    assert MySQLConfig.is_configured() is True


def test_from_env_merges_settings_defaults(monkeypatch):
    monkeypatch.setenv("MYSQL_HOST", "db.internal")
    monkeypatch.setenv("MYSQL_DATABASE", "company_db")
    monkeypatch.setenv("MYSQL_USER", "reader")
    monkeypatch.setenv("MYSQL_PASSWORD", "secret")
    monkeypatch.delenv("MYSQL_PORT", raising=False)

    config = MySQLConfig.from_env(
        {"company_mysql": {"port": 3307, "pool_size": 9, "read_timeout": 15}}
    )
    assert (config.host, config.database, config.user) == ("db.internal", "company_db", "reader")
    assert config.port == 3307
    assert config.pool_size == 9
    assert config.read_timeout == 15


def test_from_env_env_port_wins_over_settings(monkeypatch):
    monkeypatch.setenv("MYSQL_HOST", "db.internal")
    monkeypatch.setenv("MYSQL_DATABASE", "company_db")
    monkeypatch.setenv("MYSQL_USER", "reader")
    monkeypatch.setenv("MYSQL_PASSWORD", "secret")
    monkeypatch.setenv("MYSQL_PORT", "3310")
    assert MySQLConfig.from_env({"company_mysql": {"port": 3307}}).port == 3310


def test_from_env_accepts_an_empty_password(monkeypatch):
    # Local dev servers commonly run with a blank root password.
    monkeypatch.setenv("MYSQL_HOST", "127.0.0.1")
    monkeypatch.setenv("MYSQL_DATABASE", "company_db_test")
    monkeypatch.setenv("MYSQL_USER", "root")
    monkeypatch.setenv("MYSQL_PASSWORD", "")
    assert MySQLConfig.from_env().password == ""


def test_from_env_reports_missing_settings(monkeypatch):
    monkeypatch.setenv("MYSQL_HOST", "db.internal")
    monkeypatch.delenv("MYSQL_DATABASE", raising=False)
    monkeypatch.delenv("MYSQL_USER", raising=False)
    monkeypatch.delenv("MYSQL_PASSWORD", raising=False)
    with pytest.raises(MySQLNotConfigured) as exc:
        MySQLConfig.from_env()
    assert "MYSQL_DATABASE" in str(exc.value)
