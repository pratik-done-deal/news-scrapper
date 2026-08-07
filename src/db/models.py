# Maps company role → Cypher relationship type. Shared by the write path
# (repository) and the read path (queries) so the two never drift apart.
ROLE_TO_REL = {
    "buyer": "BOUGHT",
    "seller": "SOLD",
    "investor": "INVESTED_IN",
    "company": "INVOLVED_IN",
    # The deal's subject rather than a party to it: the company whose shares or
    # assets changed hands. A stake sale links its investor as SOLD and the
    # purchasers as BOUGHT, so the listed company itself only reaches the graph
    # through this relationship.
    "target": "ABOUT",
}

# Every way a Company can attach to a Deal. Query sites that mean "any company
# on this deal" must use this, or they silently drop whichever role is missing.
COMPANY_DEAL_RELS = "|".join(ROLE_TO_REL.values())

SCHEMA_CONSTRAINTS = [
    "CREATE CONSTRAINT article_id IF NOT EXISTS FOR (a:Article) REQUIRE a.id IS UNIQUE",
    "CREATE CONSTRAINT article_url IF NOT EXISTS FOR (a:Article) REQUIRE a.url IS UNIQUE",
    "CREATE CONSTRAINT deal_id IF NOT EXISTS FOR (d:Deal) REQUIRE d.id IS UNIQUE",
    "CREATE CONSTRAINT deal_article_id IF NOT EXISTS FOR (d:Deal) REQUIRE d.article_id IS UNIQUE",
    "CREATE CONSTRAINT company_name IF NOT EXISTS FOR (c:Company) REQUIRE c.name IS UNIQUE",
    # The Done Deal reference (e.g. "S5122"). Unique because it is the key the
    # frontend reads news by — two companies sharing one ref would merge their
    # feeds silently.
    "CREATE CONSTRAINT company_external_id IF NOT EXISTS FOR (c:Company) REQUIRE c.external_id IS UNIQUE",
    "CREATE CONSTRAINT company_signal_id IF NOT EXISTS FOR (s:CompanySignal) REQUIRE s.id IS UNIQUE",
]

SCHEMA_INDEXES = [
    "CREATE INDEX article_url_hash IF NOT EXISTS FOR (a:Article) ON (a.url_hash)",
    "CREATE INDEX article_source IF NOT EXISTS FOR (a:Article) ON (a.source)",
    "CREATE INDEX article_is_processed IF NOT EXISTS FOR (a:Article) ON (a.is_processed)",
    "CREATE INDEX article_is_ma_funding_relevant IF NOT EXISTS FOR (a:Article) ON (a.is_ma_funding_relevant)",
    "CREATE INDEX article_scraped_at IF NOT EXISTS FOR (a:Article) ON (a.scraped_at)",
    "CREATE INDEX article_duplicate_of IF NOT EXISTS FOR (a:Article) ON (a.duplicate_of)",
    "CREATE INDEX article_searched_company IF NOT EXISTS FOR (a:Article) ON (a.searched_company)",
    "CREATE INDEX deal_sector IF NOT EXISTS FOR (d:Deal) ON (d.sector)",
    "CREATE INDEX deal_deal_type IF NOT EXISTS FOR (d:Deal) ON (d.deal_type)",
    "CREATE INDEX deal_extracted_at IF NOT EXISTS FOR (d:Deal) ON (d.extracted_at)",
    "CREATE INDEX deal_is_bookmarked IF NOT EXISTS FOR (d:Deal) ON (d.is_bookmarked)",
    "CREATE INDEX company_id IF NOT EXISTS FOR (c:Company) ON (c.id)",
    "CREATE INDEX company_signal_generated_at IF NOT EXISTS FOR (s:CompanySignal) ON (s.generated_at)",
]
