"""Shared fakes for the offline MySQL tests — no live MySQL required."""

from src.db.mysql_dao import MySQLConfig, MySQLDAO


class FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self.closed = False

    def execute(self, sql, params=None):
        self._conn.executed.append((sql, params))

    def fetchall(self):
        return self._conn.rows

    def fetchone(self):
        return self._conn.rows[0] if self._conn.rows else None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True
        return False


class FakeConnection:
    def __init__(self, rows=None, ping_error=None):
        self.rows = rows if rows is not None else []
        self.executed = []
        self.closed = False
        self.ping_calls = 0
        self._ping_error = ping_error

    def cursor(self):
        return FakeCursor(self)

    def ping(self, reconnect=True):
        self.ping_calls += 1
        if self._ping_error:
            raise self._ping_error

    def close(self):
        self.closed = True


def make_dao(connections=None, rows=None, pool_size=2):
    """DAO wired to fake connections; returns (dao, list_of_created_connections)."""
    created = []
    queue = list(connections or [])

    def factory(**kwargs):
        conn = queue.pop(0) if queue else FakeConnection(rows=rows)
        conn.connect_kwargs = kwargs
        created.append(conn)
        return conn

    config = MySQLConfig(
        host="db.internal",
        user="reader",
        password="secret",
        database="company_db",
        pool_size=pool_size,
    )
    return MySQLDAO(config, connect_factory=factory), created


def last_statement(conn) -> tuple:
    """The most recent (sql, params) executed on a fake connection.

    Connections open with `SET SESSION TRANSACTION READ ONLY`, so index 0 is
    never the query under test.
    """
    return conn.executed[-1]
