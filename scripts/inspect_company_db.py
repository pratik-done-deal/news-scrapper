"""
Inspect the company MySQL database schema.

Read-only. Lists tables, shows column definitions and row counts, and can print
a few sample rows so domain DAO methods can be written against the real schema.

Usage:
    python scripts/inspect_company_db.py                      # list tables
    python scripts/inspect_company_db.py --table company      # columns for one table
    python scripts/inspect_company_db.py --table company --sample 5
    python scripts/inspect_company_db.py --entities           # sellers + buyers + leads
    python scripts/inspect_company_db.py --entities --type seller --limit 20
    python scripts/inspect_company_db.py --search "acme"      # name lookup across sources
    python scripts/inspect_company_db.py --names              # distinct names for scrape runs
    python scripts/inspect_company_db.py --query "SELECT id, name FROM company LIMIT 5"

Env (read from .env / environment):
    MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.paths import ENV_PATH, load_settings

try:
    from dotenv import load_dotenv
    load_dotenv(ENV_PATH)
except Exception:
    pass

from src.db import mysql_queries as mq
from src.db.mysql_dao import MySQLConfig, MySQLDAO, MySQLNotConfigured, ReadOnlyViolation


def _load_settings() -> dict:
    try:
        return load_settings()
    except FileNotFoundError:
        return {}


def _print_rows(rows: list[dict]) -> None:
    """Print rows as an aligned table, truncating wide values."""
    if not rows:
        print("(no rows)")
        return
    headers = list(rows[0].keys())
    values = [[_cell(row.get(h)) for h in headers] for row in rows]
    widths = [
        min(40, max(len(h), *(len(v[i]) for v in values)))
        for i, h in enumerate(headers)
    ]
    print("  ".join(h[:w].ljust(w) for h, w in zip(headers, widths)))
    print("  ".join("-" * w for w in widths))
    for row in values:
        print("  ".join(v[:w].ljust(w) for v, w in zip(row, widths)))


def _cell(value) -> str:
    text = "NULL" if value is None else str(value)
    return text.replace("\n", " ").replace("\r", " ")


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect the company MySQL schema (read-only)")
    parser.add_argument("--table", help="Show columns for this table")
    parser.add_argument("--sample", type=int, default=0, help="Print N sample rows from --table")
    parser.add_argument("--query", help="Run one read-only SQL statement")
    parser.add_argument("--counts", action="store_true", help="Include row counts when listing tables")
    parser.add_argument(
        "--entities", action="store_true", help="List active sellers, buyers, and leads"
    )
    parser.add_argument("--search", help="Search sellers/buyers/leads by company name")
    parser.add_argument("--names", action="store_true", help="Print distinct company/brand names")
    parser.add_argument(
        "--type",
        action="append",
        choices=list(mq.ENTITY_TYPES),
        help="Restrict --entities/--names to one entity type (repeatable)",
    )
    parser.add_argument("--limit", type=int, default=20, help="Row cap for --entities/--search")
    args = parser.parse_args()

    try:
        dao = MySQLDAO(MySQLConfig.from_env(_load_settings()))
    except MySQLNotConfigured as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        if not dao.health_check():
            print("error: could not reach the company MySQL database", file=sys.stderr)
            return 1

        if args.query:
            try:
                _print_rows(dao.fetch_all(args.query))
            except ReadOnlyViolation as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
            return 0

        if args.search:
            rows = mq.search_entities_by_name(dao, args.search, limit=args.limit)
            print(f"== {len(rows)} matches for {args.search!r} ==")
            _print_rows(rows)
            return 0

        if args.names:
            names = mq.fetch_entity_names(dao, entity_types=args.type)
            print(f"== {len(names)} distinct names ==")
            for name in names:
                print(name)
            return 0

        if args.entities:
            total = mq.count_entities(dao, entity_types=args.type)
            rows = mq.fetch_entities(dao, entity_types=args.type, limit=args.limit)
            print(f"== {len(rows)} of {total} entities ==")
            _print_rows(rows)
            return 0

        if args.table:
            print(f"== {args.table} columns ==")
            _print_rows(dao.describe_table(args.table))
            print(f"\nrows: {dao.count_rows(args.table)}")
            if args.sample:
                print(f"\n== {args.table} sample ==")
                _print_rows(dao.sample_rows(args.table, args.sample))
            return 0

        tables = dao.list_tables()
        print(f"== {len(tables)} tables ==")
        for name in tables:
            if args.counts:
                print(f"{name}  ({dao.count_rows(name)} rows)")
            else:
                print(name)
        return 0
    finally:
        dao.close()


if __name__ == "__main__":
    raise SystemExit(main())
