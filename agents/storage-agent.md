# Storage Agent

## Role
All Neo4j read/write operations. Manages the graph schema, article persistence, deal creation, and company merging. Runs in the consumer (P2) subprocess.

## Context
- Lives in `src/db/repository.py`.
- Class: `NewsRepository`. One instance per process, backed by a Neo4j driver connection pool.
- Schema constraints and indexes are applied on every `__init__()` call — safe to re-run (all use `IF NOT EXISTS`).
- Read-only queries for the API layer live separately in `src/db/queries.py`.

## Graph Schema

**Nodes:**

| Label | Identity | Key Properties |
|-------|----------|---------------|
| `Article` | `uuid4` | `url`, `url_hash` (sha256), `source`, `title`, `content`, `scraped_at`, `published_at`, `is_ma_funding_relevant`, `is_processed` |
| `Deal` | `uuid4` | `deal_value`, `sector`, `sub_sector`, `country`, `deal_type`, `summary`, `extracted_at` |
| `Company` | `uuid5(name)` | `name` (normalized) |

**Relationships:**

| Relationship | From → To | Meaning |
|-------------|-----------|---------|
| `HAS_DEAL` | Article → Deal | Article is the source of this deal |
| `BOUGHT` | Company → Deal | Company is the acquirer |
| `SOLD` | Company → Deal | Company is the acquisition target or divestor |
| `INVESTED_IN` | Company → Deal | Company is the VC/PE investor |
| `INVOLVED_IN` | Company → Deal | Company is the startup receiving investment |
| `ABOUT` | Company → Deal | Company is the deal's subject but not a party to it — e.g. the listed company whose shares a VC sold in a block deal |

## Skills

### `url_exists(url) → bool`
SHA-256 hash check. Called before scraping and before saving — prevents duplicate processing.

### `save_article(url, source, title, content, published_at) → _ArticleRef`
Creates an `Article` node. Returns a reference with `.id` for chaining.

### `mark_ma_funding_relevant(article_id, is_relevant)`
Sets `Article.is_ma_funding_relevant` after filter evaluation.

### `save_deal(article_id, buyer, seller, deal_value, sector, sub_sector, country, deal_type, summary)`
Creates a `Deal` node, links it to the `Article`, and `MERGE`s `Company` nodes for all buyer and seller names (comma-separated). Sets `Article.is_processed = true`.

## Company Normalization
`_normalize_company_name(name)` strips legal suffixes (`Pvt. Ltd.`, `Inc.`, `Corp.`, `LLP`, etc.) and applies `.title()`. `_company_id(name)` returns a deterministic `uuid5` keyed on the normalized name — companies with different capitalizations or legal suffixes resolve to the same node.

## Cypher Conventions
- All queries use `$param` parameterized inputs. Never interpolate user-controlled strings into Cypher.
- `MERGE` on `Company.name` (normalized). `CREATE` on `Article` and `Deal`.
- When adding new relationships, add the type to `_ROLE_TO_REL` dict and update `_roles_for_deal_type()`.
