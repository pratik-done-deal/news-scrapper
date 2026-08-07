# Company MySQL Module Cache

Last refreshed: 2026-08-04

- Owners: `src/db/mysql_dao.py` (connection layer), `src/db/mysql_queries.py` (business reads).
- Wiring: `src/api/app.py` (`_build_mysql_dao`, `app.state.mysql_dao`), `src/api/dependencies.py` (`get_mysql_dao`).
- Source anchors: `MySQLConfig`; `MySQLDAO`; `_assert_read_only()`; `_quote_identifier()`; `build_dao()`.
- Purpose: read-only access to the externally-owned company MySQL DB, alongside (not replacing) Neo4j. Neo4j remains the pipeline's store of record.
- Driver: PyMySQL with `DictCursor`, `autocommit=True`, plus a best-effort `SET SESSION TRANSACTION READ ONLY` per connection.
- Read-only rule: every statement passed to `fetch_all`/`fetch_one`/`fetch_value` must start with SELECT/SHOW/DESCRIBE/DESC/EXPLAIN/WITH. Writes, DDL, `CALL`, and stacked statements raise `ReadOnlyViolation`. `cursor()` bypasses the guard by design — use the fetch helpers unless cursor-level control is needed.
- SQL rule: bind values with `%s`; identifiers cannot be bound, so table/column names go through `_quote_identifier()`.
- Pooling: lazy LIFO pool capped at `pool_size`; checked-out connections are pinged with `reconnect=True`, and a connection whose statement raised is discarded rather than reused.
- Config: credentials from `src/config.py` -> `mysql` (`--mysql-host/-port/-user/-password/-database`); tuning defaults from `config/settings.yaml` -> `company_mysql`. A passed flag wins over YAML; `MySQLConfig.from_config()` merges the two.
- Optional by design: when `--mysql-host`/`--mysql-database` are unset the API starts normally with `app.state.mysql_dao = None`, and `get_mysql_dao` returns 503.
- Introspection: `list_tables()`, `describe_table()`, `count_rows()`, `sample_rows()`; CLI wrapper is `scripts/inspect_company_db.py`.

## Business Entities (`src/db/mysql_queries.py`)

- Three tracked-company sources, each with its own active-record filter, unioned onto one row shape `{entity_type, entity_id, company_name, brand_name, website}`:
  - `seller` -> `company`: non-empty `name`; `status` NULL or not in (junk, archived, delist, Inactive).
  - `buyer` -> `buyer`: non-empty `company_name`.
  - `lead` -> `leads`: `primary_id_type` in (seller_lead, buyer_lead); non-empty `name`; `status` not in (DROPPED, CONVERTED).
- `entity_id` is unique only within its table — identity is the `(entity_type, entity_id)` pair.
- `brand_name` exists only on `company`; the other branches project NULL.
- Entry points: `fetch_entities()`, `count_entities()`, `fetch_sellers/buyers/leads()`, `search_entities_by_name()`, `fetch_entity_names()` (names + differing brand names, deduped case-insensitively), and `fetch_watchlist()` (the entities a news run is restricted to — see `module-cache/watchlist.md`).
- `created_since` filters each UNION branch on its `created_at` (`_CREATED_COLUMNS`), which is how a nightly run picks up only newly added companies. It composes with the active filters rather than replacing them.
- Name search filters the underlying columns in each UNION branch (not the projection alias, which is not usable in WHERE) and escapes `%`/`_` in user input via `_escape_like()`. Searched columns are in `_NAME_COLUMNS`: sellers match on `name` OR `brand_name` because coverage uses the brand ("Ola", not "ANI Technologies Private Limited"); buyers and leads have no brand column.
- Verification: `python -m pytest tests/test_mysql_dao.py tests/test_mysql_queries.py` (offline, fake connections from `tests/conftest.py`). Live check: `python scripts/inspect_company_db.py --entities`.

## Test Database

- Fixture: `migrations/mysql_test_schema.sql` recreates `company`, `buyer`, and `leads` with the queried columns only, seeded with real Indian company names.
- Loader: `scripts/seed_test_company_db.py` (the only MySQL writer in the repo — uses a raw PyMySQL connection because `MySQLDAO` is read-only). Refuses any target database not ending in `_test`, and refuses the database named in `MYSQL_DATABASE`, unless `--force`.
- Seeded totals: 43 company rows / 35 active, 30 buyer / 28 active, 35 leads / 26 active — 89 active entities, 124 distinct names. The excluded rows deliberately cover every filter branch (blank/NULL names, junk/archived/delist/Inactive, DROPPED/CONVERTED, out-of-scope `primary_id_type`, NULL lead status).
- Integration tests: `tests/test_mysql_integration.py`, skipped unless `MYSQL_HOST` is set and the test DB is seeded. Verified against Homebrew MySQL 9.7.1 on 2026-08-04, including that the server rejects a write on a DAO connection with error 1792.
- Expected counts live in both the fixture header and the test constants — update them together.
