"""
Create and seed a test copy of the company MySQL database.

Loads `migrations/mysql_test_schema.sql` — the `company`, `buyer`, and `leads`
tables that `src/db/mysql_queries.py` reads — with real company names, then
reports what the active filters return.

This is the one place that writes to MySQL, so it opens its own connection
instead of going through `MySQLDAO` (which is read-only by construction).

Safety: the target database name must end in `_test`, and must not be the
configured `--mysql-database`, unless `--force` is passed. The schema file drops
its three tables before recreating them.

Usage:
    python scripts/seed_test_company_db.py --mysql-user root --mysql-password ""
    python scripts/seed_test_company_db.py --database company_db_test
    python scripts/seed_test_company_db.py --verify-only

The server to connect to comes from `src/config.py` under `mysql`, overridable
with --mysql-host/--mysql-port/--mysql-user/--mysql-password. The target
database defaults to company_db_test; --database picks another.
"""
import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pymysql

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import add_config_arguments, get_config, load_config
from src.db import mysql_queries as mq
from src.db.mysql_dao import MySQLConfig, MySQLDAO

SCHEMA_FILE = ROOT / "migrations" / "mysql_test_schema.sql"


def split_statements(sql: str) -> list[str]:
    """Split a script into statements on semicolons.

    Comments are dropped and quoted strings are respected, so a `;` or a `'`
    inside either one does not end a statement. Assumes `--` and `#` always
    start a comment outside quotes, which holds for DDL/DML but not for
    arbitrary expressions.
    """
    statements: list[str] = []
    buffer: list[str] = []
    quote: str | None = None
    index = 0
    length = len(sql)

    while index < length:
        char = sql[index]

        if quote:
            buffer.append(char)
            if char == "\\" and index + 1 < length:
                # Backslash escape inside a literal: keep both, skip ahead.
                buffer.append(sql[index + 1])
                index += 2
                continue
            if char == quote:
                # `''` inside a literal is an escaped quote, not a terminator.
                if index + 1 < length and sql[index + 1] == quote:
                    buffer.append(sql[index + 1])
                    index += 2
                    continue
                quote = None
            index += 1
            continue

        if sql.startswith("--", index) or char == "#":
            newline = sql.find("\n", index)
            index = length if newline == -1 else newline + 1
            buffer.append("\n")
            continue

        if sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            index = length if end == -1 else end + 2
            buffer.append(" ")
            continue

        if char in ("'", '"'):
            quote = char
            buffer.append(char)
        elif char == ";":
            statements.append("".join(buffer))
            buffer = []
        else:
            buffer.append(char)
        index += 1

    statements.append("".join(buffer))
    return [s.strip() for s in statements if s.strip()]


def _server_kwargs() -> dict:
    mysql = get_config().mysql
    if not mysql.user or mysql.password is None:
        raise SystemExit("error: --mysql-user and --mysql-password must be given")
    return {
        "host": mysql.host or "127.0.0.1",
        "port": mysql.port or 3306,
        "user": mysql.user,
        "password": mysql.password,
        "charset": "utf8mb4",
        "autocommit": True,
    }


def load_schema(database: str) -> tuple[int, int]:
    """Create the database if needed and run the schema file. Returns
    (statements_run, rows_inserted)."""
    statements = split_statements(SCHEMA_FILE.read_text(encoding="utf-8"))
    conn = pymysql.connect(**_server_kwargs())
    rows = 0
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{database}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            cur.execute(f"USE `{database}`")
            for statement in statements:
                affected = cur.execute(statement)
                if statement.lstrip().upper().startswith("INSERT"):
                    rows += affected or 0
    finally:
        conn.close()
    return len(statements), rows


def verify(database: str) -> None:
    """Report what the production queries return against the seeded data."""
    mysql = get_config().mysql
    config = MySQLConfig(
        host=mysql.host or "127.0.0.1",
        port=mysql.port or 3306,
        user=mysql.user,
        password=mysql.password,
        database=database,
    )
    dao = MySQLDAO(config)
    try:
        print(f"\n== active entities in `{database}` ==")
        for entity_type in mq.ENTITY_TYPES:
            total = dao.count_rows({"seller": "company", "buyer": "buyer", "lead": "leads"}[entity_type])
            active = mq.count_entities(dao, entity_types=[entity_type])
            print(f"{entity_type:<7} {active:>4} active / {total:>4} rows")
        print(f"{'total':<7} {mq.count_entities(dao):>4} active")

        recent = mq.fetch_watchlist(dao, created_since=datetime.now() - timedelta(hours=24))
        print(f"\n{len(recent)} added in the last 24h (the nightly watchlist slice):")
        for row in recent:
            print(f"  [{row['entity_type']}] {row['company_name']}")

        names = mq.fetch_entity_names(dao)
        print(f"\n{len(names)} distinct names for scrape runs, first 10:")
        for name in names[:10]:
            print(f"  {name}")

        print("\nsearch 'coffee':")
        for row in mq.search_entities_by_name(dao, "coffee"):
            print(f"  [{row['entity_type']}] {row['company_name']} ({row['website']})")
    finally:
        dao.close()


def main() -> int:
    default_db = "company_db_test"
    parser = argparse.ArgumentParser(description="Seed a test company MySQL database")
    parser.add_argument("--database", default=default_db, help=f"Target database (default {default_db})")
    parser.add_argument("--verify-only", action="store_true", help="Skip loading, just report counts")
    parser.add_argument("--force", action="store_true", help="Allow a database name not ending in _test")
    add_config_arguments(parser, only=("mysql",))
    args = parser.parse_args()
    config = load_config(args)

    database = args.database
    if not args.force:
        if not database.endswith("_test"):
            print(
                f"error: refusing to write to {database!r}: name does not end in '_test'. "
                "Pass --force if this really is a scratch database.",
                file=sys.stderr,
            )
            return 2
        if database == config.mysql.database:
            print(
                f"error: {database!r} is the configured --mysql-database; refusing to overwrite it.",
                file=sys.stderr,
            )
            return 2

    if not args.verify_only:
        if not SCHEMA_FILE.exists():
            print(f"error: {SCHEMA_FILE} not found", file=sys.stderr)
            return 2
        statements, rows = load_schema(database)
        print(f"ran {statements} statements, inserted {rows} rows into `{database}`")

    verify(database)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
