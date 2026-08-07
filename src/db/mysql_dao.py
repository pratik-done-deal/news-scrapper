"""Read-only DAO for the company MySQL database.

The company DB is owned by another system: this service only reads from it.
Every statement passes `_assert_read_only()` before execution, and connections
are opened in a server-side read-only session, so a stray write fails here
rather than in production data.

Mirrors the Neo4j layer's split — this module owns the pool and the raw-SQL
helpers; business logic and API routes call the helpers instead of holding a
connection themselves. SQL is parameterized with `%s`; identifiers (table and
column names) cannot be parameterized and go through `_quote_identifier()`.
"""

import logging
import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from queue import Empty, LifoQueue
from typing import Any, Optional, Sequence, Union

import pymysql
from pymysql.cursors import DictCursor

from ..config import AppConfig, get_config

logger = logging.getLogger(__name__)

# Statements the DAO is allowed to run. Anything else — INSERT, UPDATE, DELETE,
# DDL, CALL, LOAD — is rejected before it reaches the server.
_READ_ONLY_VERBS = ("select", "show", "describe", "desc", "explain", "with")

# Leading comments (`-- ...`, `# ...`, `/* ... */`) and whitespace, stripped
# before the verb check so a comment cannot hide the real statement.
_LEADING_NOISE_RE = re.compile(r"^(?:\s+|--[^\n]*\n?|#[^\n]*\n?|/\*.*?\*/)+", re.DOTALL)

# Quoted string literals, removed before the stacked-statement check so a
# semicolon inside a value (`WHERE note = 'a;b'`) is not read as a separator.
_STRING_LITERAL_RE = re.compile(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"", re.DOTALL)

# Leading whitespace and opening parens, so `(SELECT ...)` resolves to SELECT.
_VERB_PREFIX_RE = re.compile(r"^[(\s]+")

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_$]+$")

ParamsType = Union[Sequence[Any], dict, None]


class ReadOnlyViolation(ValueError):
    """Raised when a non-read statement is passed to the read-only DAO."""


class MySQLNotConfigured(RuntimeError):
    """Raised when MySQL access is requested but no connection settings exist."""


def _strip_leading_noise(sql: str) -> str:
    return _LEADING_NOISE_RE.sub("", sql).lstrip()


def _assert_read_only(sql: str) -> None:
    """Reject writes and stacked statements before they reach the server."""
    stripped = _strip_leading_noise(sql)
    if not stripped:
        raise ReadOnlyViolation("Empty SQL statement")

    body = stripped.rstrip().rstrip(";").rstrip()
    if ";" in _STRING_LITERAL_RE.sub("''", body):
        raise ReadOnlyViolation("Multiple statements are not allowed; run one query per call")

    verb = re.split(r"[\s(;]+", _VERB_PREFIX_RE.sub("", body), maxsplit=1)[0].lower()
    if verb not in _READ_ONLY_VERBS:
        raise ReadOnlyViolation(
            f"Statement type '{verb.upper()}' is not permitted: the company MySQL DAO is read-only"
        )


def _quote_identifier(name: str) -> str:
    """Backtick-quote a table/column name after validating it, since identifiers
    cannot be bound as parameters."""
    if not name or not _IDENTIFIER_RE.match(name):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return f"`{name}`"


@dataclass(frozen=True)
class MySQLConfig:
    """Connection settings for the company MySQL database.

    Credentials come from `src/config.py` under `mysql` (overridable with
    --mysql-host and friends); tuning knobs default from
    `config/settings.yaml` under `company_mysql`.
    """

    host: str
    user: str
    password: str
    database: str
    port: int = 3306
    pool_size: int = 5
    connect_timeout: int = 10
    read_timeout: int = 30
    charset: str = "utf8mb4"

    @staticmethod
    def is_configured(config: Optional[AppConfig] = None) -> bool:
        """True when the minimum settings for a connection are present."""
        return (config or get_config()).mysql.is_configured()

    @classmethod
    def from_config(
        cls,
        settings: Optional[dict] = None,
        config: Optional[AppConfig] = None,
    ) -> "MySQLConfig":
        """Credentials from `src/config.py`, tuning from `config/settings.yaml`.

        The two are not interchangeable: host/user/password/database identify a
        deployment and come in on the command line, while pool size and
        timeouts are the same everywhere and stay in the YAML.
        """
        cfg = (settings or {}).get("company_mysql", {}) or {}
        mysql = (config or get_config()).mysql

        host = mysql.host or cfg.get("host")
        database = mysql.database or cfg.get("database")
        user = mysql.user or cfg.get("username")
        password = mysql.password

        missing = [
            name
            for name, value in (
                ("--mysql-host", host),
                ("--mysql-database", database),
                ("--mysql-user", user),
            )
            if not value
        ]
        # An empty password is valid (local dev servers often have one), so only
        # an unset one counts as missing.
        if password is None:
            missing.append("--mysql-password")
        if missing:
            raise MySQLNotConfigured(f"Missing MySQL settings: {', '.join(missing)}")

        return cls(
            host=host,
            user=user,
            password=password,
            database=database,
            port=mysql.port or int(cfg.get("port", 3306)),
            pool_size=int(cfg.get("pool_size", 5)),
            connect_timeout=int(cfg.get("connect_timeout", 10)),
            read_timeout=int(cfg.get("read_timeout", 30)),
            charset=cfg.get("charset", "utf8mb4"),
        )


class MySQLDAO:
    """Pooled, read-only access to the company MySQL database.

    The pool is lazy: connections are opened on demand up to `pool_size` and
    returned to a LIFO queue for reuse. A checked-out connection is pinged and
    transparently reconnected, so idle-timeout drops (MySQL `wait_timeout`)
    surface as a reconnect rather than an error.
    """

    def __init__(self, config: MySQLConfig, connect_factory=pymysql.connect) -> None:
        self._config = config
        self._connect = connect_factory
        self._pool: LifoQueue = LifoQueue(maxsize=config.pool_size)
        self._lock = threading.Lock()
        self._opened = 0
        self._closed = False

    # -- connection management ------------------------------------------------

    def _new_connection(self):
        conn = self._connect(
            host=self._config.host,
            port=self._config.port,
            user=self._config.user,
            password=self._config.password,
            database=self._config.database,
            charset=self._config.charset,
            connect_timeout=self._config.connect_timeout,
            read_timeout=self._config.read_timeout,
            cursorclass=DictCursor,
            autocommit=True,
        )
        self._set_session_read_only(conn)
        return conn

    def _set_session_read_only(self, conn) -> None:
        """Server-side backstop for the read-only guard (MySQL 5.6.5+).

        Best effort: older servers and some managed proxies reject it, and the
        client-side guard still applies.
        """
        try:
            with conn.cursor() as cur:
                cur.execute("SET SESSION TRANSACTION READ ONLY")
        except Exception as exc:  # pragma: no cover - depends on server version
            logger.debug("Could not set read-only session on company MySQL: %s", exc)

    def _acquire(self):
        if self._closed:
            raise RuntimeError("MySQLDAO is closed")
        try:
            conn = self._pool.get_nowait()
        except Empty:
            with self._lock:
                if self._opened < self._config.pool_size:
                    self._opened += 1
                    open_new = True
                else:
                    open_new = False
            if open_new:
                try:
                    return self._new_connection()
                except Exception:
                    with self._lock:
                        self._opened -= 1
                    raise
            # Pool is saturated: wait for whoever is using a connection.
            conn = self._pool.get(timeout=self._config.connect_timeout)

        try:
            conn.ping(reconnect=True)
        except Exception:
            self._discard(conn)
            with self._lock:
                self._opened += 1
            try:
                return self._new_connection()
            except Exception:
                with self._lock:
                    self._opened -= 1
                raise
        return conn

    def _release(self, conn) -> None:
        if self._closed:
            self._discard(conn)
            return
        try:
            self._pool.put_nowait(conn)
        except Exception:
            self._discard(conn)

    def _discard(self, conn) -> None:
        with self._lock:
            self._opened = max(0, self._opened - 1)
        try:
            conn.close()
        except Exception:
            pass

    @contextmanager
    def connection(self):
        """Check a connection out of the pool for the duration of the block."""
        conn = self._acquire()
        try:
            yield conn
        except Exception:
            # A failed statement can leave the connection in an unknown state.
            self._discard(conn)
            raise
        else:
            self._release(conn)

    @contextmanager
    def cursor(self):
        """Yield a dict cursor on a pooled connection.

        Statements run through this cursor bypass `_assert_read_only()`; prefer
        `fetch_all()` / `fetch_one()` unless you need cursor-level control.
        """
        with self.connection() as conn:
            with conn.cursor() as cur:
                yield cur

    def close(self) -> None:
        """Close every pooled connection. The DAO is unusable afterwards."""
        self._closed = True
        while True:
            try:
                conn = self._pool.get_nowait()
            except Empty:
                break
            try:
                conn.close()
            except Exception:
                pass
        with self._lock:
            self._opened = 0

    # -- read helpers ---------------------------------------------------------

    def fetch_all(self, sql: str, params: ParamsType = None) -> list[dict]:
        """Run a read statement and return every row as a dict."""
        _assert_read_only(sql)
        with self.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall() or [])

    def fetch_one(self, sql: str, params: ParamsType = None) -> Optional[dict]:
        """Run a read statement and return the first row, or None."""
        _assert_read_only(sql)
        with self.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    def fetch_value(self, sql: str, params: ParamsType = None, default: Any = None) -> Any:
        """Return the first column of the first row — for COUNT(*)-style reads."""
        row = self.fetch_one(sql, params)
        if not row:
            return default
        return next(iter(row.values()), default)

    def health_check(self) -> bool:
        """True when a pooled connection can round-trip a trivial query."""
        try:
            return self.fetch_value("SELECT 1 AS ok") == 1
        except Exception as exc:
            logger.warning("Company MySQL health check failed: %s", exc)
            return False

    # -- schema introspection -------------------------------------------------

    def list_tables(self) -> list[str]:
        """Table and view names in the configured database."""
        rows = self.fetch_all(
            """
            SELECT TABLE_NAME AS table_name
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = %s
            ORDER BY TABLE_NAME
            """,
            (self._config.database,),
        )
        return [row["table_name"] for row in rows]

    def describe_table(self, table: str) -> list[dict]:
        """Column definitions for one table: name, type, nullability, key, default."""
        return self.fetch_all(
            """
            SELECT COLUMN_NAME    AS column_name,
                   COLUMN_TYPE    AS column_type,
                   IS_NULLABLE    AS is_nullable,
                   COLUMN_KEY     AS column_key,
                   COLUMN_DEFAULT AS column_default,
                   EXTRA          AS extra
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
            ORDER BY ORDINAL_POSITION
            """,
            (self._config.database, table),
        )

    def count_rows(self, table: str) -> int:
        """Exact row count for one table."""
        sql = f"SELECT COUNT(*) AS total FROM {_quote_identifier(table)}"
        return int(self.fetch_value(sql, default=0) or 0)

    def sample_rows(self, table: str, limit: int = 5) -> list[dict]:
        """First `limit` rows of a table, for shape-checking an unfamiliar schema."""
        limit = max(1, min(int(limit), 1000))
        sql = f"SELECT * FROM {_quote_identifier(table)} LIMIT {limit}"
        return self.fetch_all(sql)


def build_dao(settings: Optional[dict] = None) -> MySQLDAO:
    """Construct a DAO from `src/config.py` plus `config/settings.yaml` defaults."""
    return MySQLDAO(MySQLConfig.from_config(settings))
