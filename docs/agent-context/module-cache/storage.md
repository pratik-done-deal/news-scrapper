# Storage Module Cache

Last refreshed: 2026-06-23

- Owners: `src/db/repository.py`, `src/db/models.py`.
- Runtime doc: `agents/storage-agent.md`.
- Source anchors: `NewsRepository`; `_normalize_company_name()`; `_company_id()`; `_roles_for_deal_type()`; constraints/index setup in `src/db/models.py`.
- Writes: repository creates articles, marks relevance, creates deals, merges companies, and adds role relationships.
- Reads: API read queries live separately in `src/db/queries.py`.
- Company IDs: deterministic UUID5 based on normalized company name.
- Cypher rule: keep user-controlled data in `$param` values.
- Verification: unit-test helpers offline; use Neo4j only for integration smoke checks.
