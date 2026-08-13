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
    "CREATE CONSTRAINT news_article_id IF NOT EXISTS FOR (a:NewsArticle) REQUIRE a.id IS UNIQUE",
    "CREATE CONSTRAINT news_article_url IF NOT EXISTS FOR (a:NewsArticle) REQUIRE a.url IS UNIQUE",
    "CREATE CONSTRAINT news_deal_id IF NOT EXISTS FOR (d:NewsDeal) REQUIRE d.id IS UNIQUE",
    "CREATE CONSTRAINT news_deal_article_id IF NOT EXISTS FOR (d:NewsDeal) REQUIRE d.article_id IS UNIQUE",
    "CREATE CONSTRAINT news_company_name IF NOT EXISTS FOR (c:NewsCompany) REQUIRE c.name IS UNIQUE",
    # The Done Deal reference (e.g. "S5122"). Unique because it is the key the
    # frontend reads news by — two companies sharing one ref would merge their
    # feeds silently.
    "CREATE CONSTRAINT news_company_external_id IF NOT EXISTS FOR (c:NewsCompany) REQUIRE c.external_id IS UNIQUE",
    "CREATE CONSTRAINT news_company_signal_id IF NOT EXISTS FOR (s:NewsCompanySignal) REQUIRE s.id IS UNIQUE",
    # The Done Deal user id from token/validate. Unique because it is the
    # identity a bookmark hangs off — two nodes sharing one id would split a
    # user's bookmarks in half depending on which one MERGE happened to find.
    "CREATE CONSTRAINT news_user_user_id IF NOT EXISTS FOR (u:NewsUser) REQUIRE u.user_id IS UNIQUE",
]

SCHEMA_INDEXES = [
    "CREATE INDEX news_article_url_hash IF NOT EXISTS FOR (a:NewsArticle) ON (a.url_hash)",
    "CREATE INDEX news_article_source IF NOT EXISTS FOR (a:NewsArticle) ON (a.source)",
    "CREATE INDEX news_article_is_processed IF NOT EXISTS FOR (a:NewsArticle) ON (a.is_processed)",
    "CREATE INDEX news_article_is_ma_funding_relevant IF NOT EXISTS FOR (a:NewsArticle) ON (a.is_ma_funding_relevant)",
    "CREATE INDEX news_article_scraped_at IF NOT EXISTS FOR (a:NewsArticle) ON (a.scraped_at)",
    "CREATE INDEX news_article_duplicate_of IF NOT EXISTS FOR (a:NewsArticle) ON (a.duplicate_of)",
    "CREATE INDEX news_article_searched_company IF NOT EXISTS FOR (a:NewsArticle) ON (a.searched_company)",
    "CREATE INDEX news_deal_sector IF NOT EXISTS FOR (d:NewsDeal) ON (d.sector)",
    "CREATE INDEX news_deal_deal_type IF NOT EXISTS FOR (d:NewsDeal) ON (d.deal_type)",
    "CREATE INDEX news_deal_extracted_at IF NOT EXISTS FOR (d:NewsDeal) ON (d.extracted_at)",
    "CREATE INDEX news_company_id IF NOT EXISTS FOR (c:NewsCompany) ON (c.id)",
    "CREATE INDEX news_company_signal_generated_at IF NOT EXISTS FOR (s:NewsCompanySignal) ON (s.generated_at)",
]
