-- idx_companies_name is redundant: the UNIQUE constraint on companies.name
-- already creates an equivalent B-tree index. Keeping both wastes write
-- overhead and disk space on every INSERT/UPDATE.
DROP INDEX IF EXISTS idx_companies_name;
