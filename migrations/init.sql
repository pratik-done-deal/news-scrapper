CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS articles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    url TEXT UNIQUE NOT NULL,
    url_hash TEXT NOT NULL,
    source TEXT NOT NULL,
    title TEXT,
    content TEXT,
    scraped_at TIMESTAMPTZ DEFAULT NOW(),
    is_ma_relevant BOOLEAN DEFAULT NULL,
    is_processed BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_articles_url_hash ON articles(url_hash);
CREATE INDEX IF NOT EXISTS idx_articles_is_processed ON articles(is_processed);
CREATE INDEX IF NOT EXISTS idx_articles_scraped_at ON articles(scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_source ON articles(source);

CREATE TABLE IF NOT EXISTS deals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    article_id UUID NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    buyer TEXT,
    seller TEXT,
    deal_value TEXT,
    sector TEXT,
    country TEXT,
    deal_type TEXT,
    summary TEXT,
    extracted_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_deals_article_id ON deals(article_id);
CREATE INDEX IF NOT EXISTS idx_deals_extracted_at ON deals(extracted_at DESC);
CREATE INDEX IF NOT EXISTS idx_deals_deal_type ON deals(deal_type);
CREATE INDEX IF NOT EXISTS idx_deals_sector ON deals(sector);
