SCHEMA_CONSTRAINTS = [
    "CREATE CONSTRAINT article_id IF NOT EXISTS FOR (a:Article) REQUIRE a.id IS UNIQUE",
    "CREATE CONSTRAINT article_url IF NOT EXISTS FOR (a:Article) REQUIRE a.url IS UNIQUE",
    "CREATE CONSTRAINT deal_id IF NOT EXISTS FOR (d:Deal) REQUIRE d.id IS UNIQUE",
    "CREATE CONSTRAINT company_name IF NOT EXISTS FOR (c:Company) REQUIRE c.name IS UNIQUE",
]

SCHEMA_INDEXES = [
    "CREATE INDEX article_url_hash IF NOT EXISTS FOR (a:Article) ON (a.url_hash)",
    "CREATE INDEX article_source IF NOT EXISTS FOR (a:Article) ON (a.source)",
    "CREATE INDEX article_is_processed IF NOT EXISTS FOR (a:Article) ON (a.is_processed)",
    "CREATE INDEX article_is_ma_funding_relevant IF NOT EXISTS FOR (a:Article) ON (a.is_ma_funding_relevant)",
    "CREATE INDEX article_scraped_at IF NOT EXISTS FOR (a:Article) ON (a.scraped_at)",
    "CREATE INDEX deal_sector IF NOT EXISTS FOR (d:Deal) ON (d.sector)",
    "CREATE INDEX deal_deal_type IF NOT EXISTS FOR (d:Deal) ON (d.deal_type)",
    "CREATE INDEX deal_extracted_at IF NOT EXISTS FOR (d:Deal) ON (d.extracted_at)",
    "CREATE INDEX company_id IF NOT EXISTS FOR (c:Company) ON (c.id)",
]
